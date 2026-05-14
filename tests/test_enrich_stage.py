"""Behavioral tests for `src/ohbm2026/enrich_stage.py`.

Stage 2 orchestrator. Tests cover the six per-stage contract elements
(`docs/per-stage-pattern.md`) plus the US2/US3/US4 acceptance scenarios
from `specs/003-enrich-abstracts/spec.md`. Per Principle IV these land
before `enrich_stage.py` is implemented and MUST initially fail.

The fixture provides synthetic accepted abstracts with deterministic
content hashes. All LLM / HTTP calls are mocked at the orchestrator's
component-runner seam (`_run_figure_component`, `_run_claims_component`,
`_run_references_component`) so no live API call is possible.
"""

from __future__ import annotations

import contextlib
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import unittest
import zlib
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock


# ----- Fixtures -------------------------------------------------------


def _abstract(aid: int, *, withdrawn: bool = False, n_figs: int = 1, n_refs: int = 2) -> dict:
    """Synthetic Stage 1 abstract record. Field shape matches what
    Stage 1's normalize_abstract produces (see assets.py)."""
    return {
        "id": aid,
        "poster_id": f"P-{aid:04d}",
        "title": f"Synthetic abstract {aid}",
        "accepted_for": "Withdrawn" if withdrawn else "Poster",
        "authors": [
            {"author_order": 1, "first_name": "Test", "last_name": f"P{aid}"}
        ],
        "responses": [
            {"question_name": "Introduction", "value": f"Intro text {aid}"},
            {"question_name": "Methods", "value": f"Methods text {aid}"},
            {"question_name": "Results", "value": f"Results text {aid}"},
            {"question_name": "Conclusion", "value": f"Conclusion text {aid}"},
            {
                "question_name": "References",
                "value": "\n".join(f"Ref {aid}.{i} (Author et al. 2024)" for i in range(n_refs)),
            },
        ],
        "external_urls": [],
        "figure_urls": [
            {"question_name": "Methods Figure (Optional)", "url": f"https://figs.example/{aid}.png"}
        ][:n_figs],
        "program_sessions": [],
        "local_assets": [
            {"figure_url": f"https://figs.example/{aid}.png", "local_path": f"data/primary/assets/{aid}.png"}
        ][:n_figs],
    }


def _write_source_corpus(tmp: Path, abstracts: list[dict]) -> Path:
    primary = tmp / "data" / "primary"
    primary.mkdir(parents=True, exist_ok=True)
    corpus_path = primary / "abstracts.json"
    corpus_path.write_text(
        json.dumps({"abstract_count": len(abstracts), "abstracts": abstracts}),
        encoding="utf-8",
    )
    return corpus_path


class _RepoFixture(unittest.TestCase):
    """Subclass-able mixin that yields a tmp repo root per test method
    and cleans it up via addCleanup. Use `self.tmp_repo()` to obtain
    the root."""

    def tmp_repo(self) -> Path:
        root = Path(tempfile.mkdtemp(prefix="ohbm-enrich-stage-"))
        for sub in (
            "data/primary",
            "data/inputs",
            "data/cache/figure_analysis",
            "data/cache/claim_analysis",
            "data/cache/reference_metadata",
        ):
            (root / sub).mkdir(parents=True, exist_ok=True)
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        return root


@contextlib.contextmanager
def _tmp_repo() -> "Path":
    """(Deprecated context-manager form retained only for tests that
    truly want a hard-bounded lifetime. New tests should subclass
    `_RepoFixture` and use `self.tmp_repo()`.)"""
    with TemporaryDirectory() as name:
        root = Path(name)
        for sub in (
            "data/primary",
            "data/inputs",
            "data/cache/figure_analysis",
            "data/cache/claim_analysis",
            "data/cache/reference_metadata",
        ):
            (root / sub).mkdir(parents=True, exist_ok=True)
        yield root


# ----- Synthetic component-runner fakes -------------------------------


def _fake_figure_record(figure_url: str, model_id: str, *, local_path: str | None = None) -> dict:
    return {
        "figure_url": figure_url,
        "local_path": local_path or f"data/primary/assets/{figure_url.rsplit('/', 1)[-1]}",
        "question_name": "Methods Figure (Optional)",
        "interpretation": f"interp[{model_id}]({figure_url})",
        "keywords": ["fmri", "bold"],
        "ocr_text": None,
        "model_quality_estimate": "high",
        "local_quality_estimate": {
            "laplacian_variance": 500.0,
            "mean_brightness": 200.0,
            "native_max_dim": 1024,
            "compression_ratio": 0.2,
        },
        "model_id": model_id,
        "cache_key": _sha256_of(f"{figure_url}||{model_id}"),
    }


def _fake_claim_record(model_id: str, abstract_id: int, index: int, manuscript: str) -> dict:
    # Pick a source_quote that exists as a substring of the manuscript
    # so the orchestrator's post-response verification accepts it.
    sentinel = f"Methods text {abstract_id}"
    source_quote = sentinel if sentinel in manuscript else manuscript[:20].strip() or "Synthetic abstract"
    return {
        "claim_text": f"claim[{model_id}][{abstract_id}].{index}",
        "source_quote": source_quote,
        "source_quote_verified": True,
        "claim_type": "explicit",
        "evidence_eco_codes": ["ECO:0000006"],
        "confidence": 0.85,
        "model_id": model_id,
        "cache_key": _sha256_of(f"{abstract_id}||{model_id}||claim.{index}"),
    }


def _fake_reference_record(raw_ref: str, strategy_id: str) -> dict:
    return {
        "raw_reference": raw_ref,
        "doi": "10.1234/synth",
        "pmid": None,
        "openalex_id": None,
        "title": f"resolved[{strategy_id}]({raw_ref[:20]})",
        "authors": ["Author A"],
        "year": 2024,
        "resolution_status": "resolved",
        "resolution_source": "doi",
        "strategy_id": strategy_id,
        "cache_key": _sha256_of(f"{raw_ref}||{strategy_id}"),
    }


def _sha256_of(text: str) -> str:
    import hashlib
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _stage2_synthetic_manuscript(abstract: dict) -> str:
    # Mirrors what stage2_claims._build_manuscript_markdown produces.
    aid = abstract.get("id", 0)
    parts = [f"# Synthetic abstract {aid}"]
    for response in abstract.get("responses", []) or []:
        name = (response.get("question_name") or "").strip()
        value = (response.get("value") or "").strip()
        if name and value:
            parts.append(f"## {name}\n\n{value}")
    return "\n\n".join(parts)


def _patch_components(
    *,
    figure_runner=None,
    claims_runner=None,
    reference_runner=None,
    backend_availability=None,
):
    """Patch the three Stage 2.1 per-abstract production seams + the
    backend-availability classifier on `ohbm2026.enrich_stage`. Each
    runner is a callable that takes a per-abstract signature and
    returns a `(records_list, RunSummary)` tuple."""
    from ohbm2026 import enrich_stage

    patches = []
    if figure_runner is not None:
        patches.append(mock.patch.object(enrich_stage, "_call_figures_for_abstract", side_effect=figure_runner))
    if claims_runner is not None:
        patches.append(mock.patch.object(enrich_stage, "_call_claims_for_abstract", side_effect=claims_runner))
    if reference_runner is not None:
        patches.append(mock.patch.object(enrich_stage, "_call_references_for_abstract", side_effect=reference_runner))
    if backend_availability is not None:
        patches.append(
            mock.patch.object(
                enrich_stage, "_classify_backend_availability", return_value=backend_availability
            )
        )
    return patches


class _StackedPatches:
    def __init__(self, patches):
        self._patches = patches
        self._started = []

    def __enter__(self):
        for p in self._patches:
            self._started.append(p.start())
        return self._started

    def __exit__(self, *exc_info):
        for p in reversed(self._patches):
            p.stop()


def _default_backend_availability():
    from ohbm2026 import enrich_stage

    return enrich_stage.BackendAvailability(
        figures_backend="openai",
        claims_backend="openai",
        references_backend="openai+openalex",
    )


def _figure_count(record: dict) -> int:
    return len(record.get("figure_urls", []))


def _ref_count(record: dict) -> int:
    for q in record.get("responses", []):
        if q.get("question_name") == "References":
            return len([line for line in (q.get("value") or "").splitlines() if line.strip()])
    return 0


def _default_runners():
    """Standard per-abstract runners that return deterministic synthetic
    `(records_list, RunSummary)` tuples for the new Stage 2.1 seams."""
    from ohbm2026 import stage2_figures, stage2_claims, stage2_references

    figure_calls = []
    claims_calls = []
    reference_calls = []

    def figure_runner(abstract, *, model_id, flex_enabled, cwd, client, **_kw):
        figure_calls.append((abstract.get("id"), model_id, flex_enabled))
        local_assets_by_url = {
            a.get("figure_url"): a.get("local_path")
            for a in (abstract.get("local_assets") or [])
        }
        records = []
        for entry in abstract.get("figure_urls", []) or []:
            url = entry.get("url") or entry.get("figure_url") or ""
            records.append(_fake_figure_record(url, model_id, local_path=local_assets_by_url.get(url)))
        summary = stage2_figures.FigureRunSummary(
            figure_count=len(records),
            flex_timed_out=False,
            tier_used="flex" if flex_enabled else "standard",
            attempts=1,
            latency_ms=5.0,
            prompt_tokens_cached=0,
            prompt_tokens_uncached=2000,
            completion_tokens=400,
        )
        return records, summary

    def claims_runner(abstract, *, model_id, flex_enabled, figure_interpretations, client, **_kw):
        claims_calls.append((abstract.get("id"), model_id, flex_enabled))
        manuscript = _stage2_synthetic_manuscript(abstract)
        records = [
            _fake_claim_record(model_id, int(abstract.get("id", 0)), i, manuscript)
            for i in range(2)
        ]
        summary = stage2_claims.ClaimsRunSummary(
            claims_count=len(records),
            flex_timed_out=False,
            tier_used="flex" if flex_enabled else "standard",
            attempts=1,
            latency_ms=6.0,
            prompt_tokens_cached=0,
            prompt_tokens_uncached=3000,
            completion_tokens=600,
        )
        return records, summary

    def reference_runner(abstract, *, strategy_id, resolver=None, **_kw):
        reference_calls.append((abstract.get("id"), strategy_id))
        # Mirror the orchestrator's per-line split of the references block.
        block = ""
        for response in abstract.get("responses", []) or []:
            name = (response.get("question_name") or "").lower()
            if "reference" in name:
                block = response.get("value") or ""
                break
        refs = [line.strip() for line in block.splitlines() if line.strip()]
        records = [_fake_reference_record(raw, strategy_id) for raw in refs]
        summary = stage2_references.ReferencesRunSummary(
            reference_count=len(records),
            resolved_count=len(records),
            unresolved_count=0,
            latency_ms=2.0,
        )
        return records, summary

    return figure_runner, claims_runner, reference_runner, figure_calls, claims_calls, reference_calls


def _seed_assets(tmp: Path, abstracts: list[dict]) -> None:
    assets_dir = tmp / "data" / "primary" / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)
    for ab in abstracts:
        for asset in ab.get("local_assets", []):
            target = tmp / asset["local_path"]
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b"PNG-bytes-" + str(ab["id"]).encode("ascii"))


def _run_and_capture(tmp: Path, argv: list[str], env: dict[str, str] | None = None) -> int:
    from ohbm2026 import enrich_stage

    env = env or {"OPENAI_API_KEY": "fake-key", "OPENALEX_API": "fake-alex"}
    with mock.patch.dict(os.environ, env, clear=False):
        with mock.patch("ohbm2026.enrich_stage.Path.cwd", return_value=tmp):
            return enrich_stage.main(argv)


def _read_provenance(tmp: Path) -> dict:
    paths = list((tmp / "data" / "inputs").glob("abstracts_enrich_provenance__*.json"))
    assert len(paths) == 1, f"expected one provenance file, got {paths}"
    return json.loads(paths[0].read_text(encoding="utf-8"))


def _read_enriched(tmp: Path, abstract_id: int) -> dict:
    db_path = tmp / "data" / "primary" / "abstracts_enriched.sqlite"
    con = sqlite3.connect(db_path)
    try:
        row = con.execute("SELECT payload FROM abstracts WHERE id = ?", (abstract_id,)).fetchone()
    finally:
        con.close()
    assert row is not None
    return json.loads(zlib.decompress(row[0]))


# ----- Contract 1: Input ----------------------------------------------


class InputContractTests(_RepoFixture):
    def test_missing_source_corpus_exits_non_zero_with_typed_error(self) -> None:
        tmp = self.tmp_repo()
        # No abstracts.json created.
        rc = _run_and_capture(tmp, [])
        self.assertNotEqual(rc, 0)

    def test_ohbm2026_api_is_not_consulted_by_stage_2(self) -> None:
        """FR-015: Stage 2 does NOT need OHBM2026_API (that's a Stage 1
        env var). Provenance records env-var NAMES consulted; OHBM2026_API
        MUST NOT appear there."""
        tmp = self.tmp_repo()
        _write_source_corpus(tmp, [_abstract(1)])
        _seed_assets(tmp, [_abstract(1)])
        fr, cr, rr, *_ = _default_runners()
        with _StackedPatches(_patch_components(
            figure_runner=fr, claims_runner=cr, reference_runner=rr,
            backend_availability=_default_backend_availability(),
        )):
            rc = _run_and_capture(tmp, [])
        self.assertEqual(rc, 0)
        prov = _read_provenance(tmp)
        self.assertNotIn("OHBM2026_API", prov["env_vars_consulted"])

    def test_missing_required_api_key_exits_non_zero(self) -> None:
        """A configured backend that needs OPENAI_API_KEY MUST refuse to
        run with no key (Principle VI: fail loudly, no fallback)."""
        from ohbm2026 import enrich_stage

        tmp = self.tmp_repo()
        _write_source_corpus(tmp, [_abstract(1)])
        _seed_assets(tmp, [_abstract(1)])
        # Force discovery to report all backends as unavailable.
        unavailable = enrich_stage.BackendAvailability(
            figures_backend=None, claims_backend=None, references_backend=None,
        )
        with _StackedPatches(_patch_components(backend_availability=unavailable)):
            with mock.patch.dict(os.environ, {}, clear=True):
                with mock.patch("ohbm2026.enrich_stage.Path.cwd", return_value=tmp):
                    rc = enrich_stage.main([])
        self.assertNotEqual(rc, 0)


# ----- Contract 2: Output ---------------------------------------------


class OutputContractTests(_RepoFixture):
    def test_clean_run_writes_enriched_sqlite_and_provenance(self) -> None:
        tmp = self.tmp_repo()
        abstracts = [_abstract(1), _abstract(2)]
        _write_source_corpus(tmp, abstracts)
        _seed_assets(tmp, abstracts)

        fr, cr, rr, *_ = _default_runners()
        with _StackedPatches(_patch_components(
            figure_runner=fr, claims_runner=cr, reference_runner=rr,
            backend_availability=_default_backend_availability(),
        )):
            rc = _run_and_capture(tmp, [])
        self.assertEqual(rc, 0)

        enriched = tmp / "data" / "primary" / "abstracts_enriched.sqlite"
        provenance = list((tmp / "data" / "inputs").glob("abstracts_enrich_provenance__*.json"))
        self.assertTrue(enriched.exists())
        self.assertEqual(len(provenance), 1)

        # Records are queryable and well-formed.
        for aid in (1, 2):
            rec = _read_enriched(tmp, aid)
            self.assertEqual(rec["id"], aid)
            self.assertEqual(len(rec["figure_interpretation"]), 1)
            self.assertEqual(len(rec["claims"]), 2)
            self.assertEqual(len(rec["references"]), 2)

    def test_stage_1_outputs_are_not_modified_by_stage_2_run(self) -> None:
        """FR-015: Stage 2 MUST NOT alter Stage 1 outputs. Snapshot
        mtimes of every Stage 1 artifact before; assert unchanged after."""
        tmp = self.tmp_repo()
        abstracts = [_abstract(1)]
        corpus_path = _write_source_corpus(tmp, abstracts)
        _seed_assets(tmp, abstracts)
        # Land sibling Stage 1 outputs.
        (tmp / "data" / "primary" / "abstracts_withdrawn.json").write_text(
            json.dumps({"abstract_count": 0, "abstracts": []}), encoding="utf-8",
        )
        (tmp / "data" / "primary" / "authors.json").write_text(
            json.dumps({"author_count": 0, "authors": []}), encoding="utf-8",
        )
        schema = tmp / "data" / "inputs" / "abstracts_graphql_schema__deadbeef0001.json"
        schema.write_text(json.dumps({"state_key": "deadbeef0001"}), encoding="utf-8")

        stage1_paths = [
            corpus_path,
            tmp / "data" / "primary" / "abstracts_withdrawn.json",
            tmp / "data" / "primary" / "authors.json",
            schema,
        ] + [tmp / a["local_assets"][0]["local_path"] for a in abstracts]
        stage1_mtimes = {p: p.stat().st_mtime_ns for p in stage1_paths}

        fr, cr, rr, *_ = _default_runners()
        with _StackedPatches(_patch_components(
            figure_runner=fr, claims_runner=cr, reference_runner=rr,
            backend_availability=_default_backend_availability(),
        )):
            rc = _run_and_capture(tmp, [])
        self.assertEqual(rc, 0)

        for p, before in stage1_mtimes.items():
            self.assertEqual(
                p.stat().st_mtime_ns, before,
                f"FR-015 violation: Stage 1 artifact {p} was modified",
            )

    def test_corpus_metadata_table_reflects_run(self) -> None:
        tmp = self.tmp_repo()
        abstracts = [_abstract(1)]
        _write_source_corpus(tmp, abstracts)
        _seed_assets(tmp, abstracts)
        fr, cr, rr, *_ = _default_runners()
        with _StackedPatches(_patch_components(
            figure_runner=fr, claims_runner=cr, reference_runner=rr,
            backend_availability=_default_backend_availability(),
        )):
            rc = _run_and_capture(tmp, [])
        self.assertEqual(rc, 0)

        from ohbm2026 import enrich_storage
        meta = enrich_storage.corpus_metadata(tmp / "data" / "primary" / "abstracts_enriched.sqlite")
        self.assertEqual(meta["storage_version"], enrich_storage.STORAGE_VERSION)
        self.assertEqual(meta["corpus_kind"], "accepted")


# ----- Contract 3: Provenance -----------------------------------------


class ProvenanceContractTests(_RepoFixture):
    def test_required_fields_present_and_paths_project_relative(self) -> None:
        tmp = self.tmp_repo()
        _write_source_corpus(tmp, [_abstract(1)])
        _seed_assets(tmp, [_abstract(1)])
        fr, cr, rr, *_ = _default_runners()
        with _StackedPatches(_patch_components(
            figure_runner=fr, claims_runner=cr, reference_runner=rr,
            backend_availability=_default_backend_availability(),
        )):
            rc = _run_and_capture(tmp, [])
        self.assertEqual(rc, 0)

        prov = _read_provenance(tmp)
        for required in (
            "provenance_version", "run_id", "state_key", "run_timestamp",
            "code_revision", "command_line", "env_vars_consulted",
            "source_corpus_path", "source_corpus_hash",
            "enriched_corpus_path", "corpus_kind", "abstract_count",
            "components", "delta_vs_previous",
            "figure_failure_count", "claim_failure_count",
            "reference_failure_count", "parquet_export_path",
        ):
            self.assertIn(required, prov, f"missing required field {required}")

        for path_field in ("source_corpus_path", "enriched_corpus_path"):
            value = prov[path_field]
            self.assertFalse(value.startswith("/"), f"{path_field} must be project-relative")
            self.assertFalse(value.startswith("~"), f"{path_field} must not be home-prefixed")

    def test_env_vars_consulted_lists_names_only(self) -> None:
        secret = "sk-" + "x" * 32
        tmp = self.tmp_repo()
        _write_source_corpus(tmp, [_abstract(1)])
        _seed_assets(tmp, [_abstract(1)])
        fr, cr, rr, *_ = _default_runners()
        with _StackedPatches(_patch_components(
            figure_runner=fr, claims_runner=cr, reference_runner=rr,
            backend_availability=_default_backend_availability(),
        )):
            rc = _run_and_capture(tmp, [], env={"OPENAI_API_KEY": secret, "OPENALEX_API": "alex-secret"})
        self.assertEqual(rc, 0)

        prov_path = list((tmp / "data" / "inputs").glob("abstracts_enrich_provenance__*.json"))[0]
        body = prov_path.read_text(encoding="utf-8")
        self.assertNotIn(secret, body, "secret value MUST NOT appear in provenance")
        prov = json.loads(body)
        self.assertIn("OPENAI_API_KEY", prov["env_vars_consulted"])
        for v in prov["env_vars_consulted"]:
            self.assertNotIn(secret, v)

    def test_parquet_export_path_is_null_when_flag_absent(self) -> None:
        tmp = self.tmp_repo()
        _write_source_corpus(tmp, [_abstract(1)])
        _seed_assets(tmp, [_abstract(1)])
        fr, cr, rr, *_ = _default_runners()
        with _StackedPatches(_patch_components(
            figure_runner=fr, claims_runner=cr, reference_runner=rr,
            backend_availability=_default_backend_availability(),
        )):
            rc = _run_and_capture(tmp, [])
        self.assertEqual(rc, 0)
        prov = _read_provenance(tmp)
        self.assertIsNone(prov["parquet_export_path"])

    def test_components_block_has_three_entries(self) -> None:
        tmp = self.tmp_repo()
        _write_source_corpus(tmp, [_abstract(1)])
        _seed_assets(tmp, [_abstract(1)])
        fr, cr, rr, *_ = _default_runners()
        with _StackedPatches(_patch_components(
            figure_runner=fr, claims_runner=cr, reference_runner=rr,
            backend_availability=_default_backend_availability(),
        )):
            _run_and_capture(tmp, [])
        prov = _read_provenance(tmp)
        names = {c["component"] for c in prov["components"]}
        self.assertEqual(names, {"figures", "claims", "references"})


# ----- Contract 4: Error ----------------------------------------------


class ErrorContractTests(_RepoFixture):
    def test_figure_failure_threshold_exceeded_exits_five(self) -> None:
        from ohbm2026 import exceptions as exc_mod  # noqa: F401

        tmp = self.tmp_repo()
        abstracts = [_abstract(i) for i in range(1, 11)]
        _write_source_corpus(tmp, abstracts)
        _seed_assets(tmp, abstracts)

        def failing_figure(*_a, **_kw):
            raise exc_mod.EnrichmentError("synthetic figure failure")

        _, cr, rr, *_ = _default_runners()
        with _StackedPatches(_patch_components(
            figure_runner=failing_figure, claims_runner=cr, reference_runner=rr,
            backend_availability=_default_backend_availability(),
        )):
            rc = _run_and_capture(tmp, ["--figure-failure-threshold", "0.05"])
        self.assertEqual(rc, 5)

    def test_claim_failure_threshold_exceeded_exits_five(self) -> None:
        from ohbm2026 import exceptions as exc_mod

        tmp = self.tmp_repo()
        abstracts = [_abstract(i) for i in range(1, 11)]
        _write_source_corpus(tmp, abstracts)
        _seed_assets(tmp, abstracts)

        def failing_claims(*_a, **_kw):
            raise exc_mod.EnrichmentError("synthetic claims failure")

        fr, _, rr, *_ = _default_runners()
        with _StackedPatches(_patch_components(
            figure_runner=fr, claims_runner=failing_claims, reference_runner=rr,
            backend_availability=_default_backend_availability(),
        )):
            rc = _run_and_capture(tmp, ["--claim-failure-threshold", "0.05"])
        self.assertEqual(rc, 5)

    def test_generic_enrichment_error_below_threshold_completes(self) -> None:
        """Per-record failures BELOW threshold are tolerated (FR-010)."""
        from ohbm2026 import exceptions as exc_mod

        tmp = self.tmp_repo()
        abstracts = [_abstract(i) for i in range(1, 21)]
        _write_source_corpus(tmp, abstracts)
        _seed_assets(tmp, abstracts)

        calls = {"n": 0}
        fr_default, cr, rr, *_ = _default_runners()

        def maybe_fail_figure(abstract, **kw):
            calls["n"] += 1
            if calls["n"] == 1:
                raise exc_mod.EnrichmentError("one-shot")
            return fr_default(abstract, **kw)
        with _StackedPatches(_patch_components(
            figure_runner=maybe_fail_figure, claims_runner=cr, reference_runner=rr,
            backend_availability=_default_backend_availability(),
        )):
            rc = _run_and_capture(tmp, ["--figure-failure-threshold", "0.5"])
        self.assertEqual(rc, 0)

    def test_absolute_export_parquet_path_raises_provenance_boundary(self) -> None:
        tmp = self.tmp_repo()
        _write_source_corpus(tmp, [_abstract(1)])
        _seed_assets(tmp, [_abstract(1)])
        fr, cr, rr, *_ = _default_runners()
        with _StackedPatches(_patch_components(
            figure_runner=fr, claims_runner=cr, reference_runner=rr,
            backend_availability=_default_backend_availability(),
        )):
            rc = _run_and_capture(tmp, ["--export-parquet", "/tmp/oops.parquet"])
        self.assertEqual(rc, 4)

    def test_cache_version_mismatch_exits_seven(self) -> None:
        from ohbm2026 import enrich_storage

        tmp = self.tmp_repo()
        abstracts = [_abstract(1)]
        _write_source_corpus(tmp, abstracts)
        _seed_assets(tmp, abstracts)
        # Seed a cache file with a wrong cache_version.
        cache_dir = tmp / "data" / "cache" / "figure_analysis"
        cache_dir.mkdir(parents=True, exist_ok=True)
        # We don't know the exact cache_key yet — but we can write
        # one entry with the wrong version that will be discovered
        # by the orchestrator on first lookup. The orchestrator
        # MUST raise CacheVersionError on a `cache_version`
        # mismatch (research.md §3 + spec FR-010 / CA-006).
        # Approach: write a wildcard entry that the orchestrator
        # tries to load OR provide a config-level cache_version
        # override. We use the latter via a hidden test seam.
        from ohbm2026 import enrich_stage

        fr, cr, rr, *_ = _default_runners()
        patches = _patch_components(
            figure_runner=fr, claims_runner=cr, reference_runner=rr,
            backend_availability=_default_backend_availability(),
        )
        # Force the cache reader to encounter a mismatched
        # cache_version by monkeypatching the helper to return one.
        patches.append(
            mock.patch.object(
                enrich_stage,
                "_load_cache_entry",
                side_effect=__import__("ohbm2026").exceptions.CacheVersionError("stale cache"),
            )
        )
        with _StackedPatches(patches):
            rc = _run_and_capture(tmp, [])
        self.assertEqual(rc, 7)


# ----- Contract 5: Resumability ---------------------------------------


class ResumabilityContractTests(_RepoFixture):
    def test_partial_run_aborts_without_writing_sqlite_then_resumes_using_cache(self) -> None:
        """SC-009: start a run; raise mid-loop; no partial enriched
        corpus on disk. Re-invoke; the second run reuses every
        already-cached entry."""
        from ohbm2026 import exceptions as exc_mod

        tmp = self.tmp_repo()
        abstracts = [_abstract(i) for i in range(1, 11)]
        _write_source_corpus(tmp, abstracts)
        _seed_assets(tmp, abstracts)

        calls = {"figures": 0, "claims": 0, "references": 0}
        fr_default, cr_default, rr_default, *_ = _default_runners()

        def figure_runner(abstract, **kw):
            calls["figures"] += 1
            if calls["figures"] == 5:
                raise exc_mod.EnrichmentError("simulated mid-run failure")
            return fr_default(abstract, **kw)

        def claims_runner(abstract, **kw):
            calls["claims"] += 1
            return cr_default(abstract, **kw)

        def reference_runner(abstract, **kw):
            calls["references"] += 1
            return rr_default(abstract, **kw)

        with _StackedPatches(_patch_components(
            figure_runner=figure_runner, claims_runner=claims_runner, reference_runner=reference_runner,
            backend_availability=_default_backend_availability(),
        )):
            rc = _run_and_capture(tmp, ["--figure-failure-threshold", "0.05"])
        self.assertEqual(rc, 5)

        # No enriched SQLite was written.
        enriched = tmp / "data" / "primary" / "abstracts_enriched.sqlite"
        self.assertFalse(enriched.exists(), "partial run must NOT write the canonical SQLite")

        partial_figures = calls["figures"]

        # Re-invoke with non-failing figure runner; cached entries
        # should short-circuit, so total figure calls grow only by
        # the abstracts not yet cached.
        calls_before_second = dict(calls)

        def figure_runner_clean(abstract, **kw):
            calls["figures"] += 1
            return fr_default(abstract, **kw)

        with _StackedPatches(_patch_components(
            figure_runner=figure_runner_clean, claims_runner=claims_runner, reference_runner=reference_runner,
            backend_availability=_default_backend_availability(),
        )):
            rc = _run_and_capture(tmp, [])
        self.assertEqual(rc, 0)

        self.assertTrue(enriched.exists())
        # The figure-runner was invoked again only for the
        # abstracts whose cache was NOT populated by the first
        # (failed) run.
        new_figure_calls = calls["figures"] - calls_before_second["figures"]
        self.assertLessEqual(new_figure_calls, 10 - 4, "resume must reuse cached figure entries")


# ----- Contract 6: Discovery ------------------------------------------


class DiscoveryContractTests(_RepoFixture):
    def test_malformed_figure_response_raises_enrichment_error(self) -> None:
        """CA-007: LLM-response schema drift surfaces loudly."""
        from ohbm2026 import exceptions as exc_mod

        tmp = self.tmp_repo()
        _write_source_corpus(tmp, [_abstract(1)])
        _seed_assets(tmp, [_abstract(1)])

        def malformed_figure(*_a, **_kw):
            # Missing the required 'interpretation' / 'model_id' fields.
            raise exc_mod.EnrichmentError("schema drift: missing 'interpretation' in LLM response")

        _, cr, rr, *_ = _default_runners()
        with _StackedPatches(_patch_components(
            figure_runner=malformed_figure, claims_runner=cr, reference_runner=rr,
            backend_availability=_default_backend_availability(),
        )):
            rc = _run_and_capture(tmp, ["--figure-failure-threshold", "0.05"])
        # Per-component threshold exceeded → exit 5 with the typed
        # error chain.
        self.assertEqual(rc, 5)

    def test_classify_backend_availability_returns_typed_dataclass(self) -> None:
        from ohbm2026 import enrich_stage

        result = enrich_stage._classify_backend_availability(
            env={"OPENAI_API_KEY": "k"}, dotenv_path=None,
        )
        self.assertIsInstance(result, enrich_stage.BackendAvailability)
        for attr in ("figures_backend", "claims_backend", "references_backend"):
            self.assertTrue(hasattr(result, attr))


# ----- US2: Idempotency -----------------------------------------------


class IdempotencyContractTests(_RepoFixture):
    def test_second_run_with_same_inputs_uses_caches_and_no_llm_calls(self) -> None:
        tmp = self.tmp_repo()
        abstracts = [_abstract(1), _abstract(2)]
        _write_source_corpus(tmp, abstracts)
        _seed_assets(tmp, abstracts)

        fr1, cr1, rr1, f_calls1, c_calls1, r_calls1 = _default_runners()
        with _StackedPatches(_patch_components(
            figure_runner=fr1, claims_runner=cr1, reference_runner=rr1,
            backend_availability=_default_backend_availability(),
        )):
            rc = _run_and_capture(tmp, [])
        self.assertEqual(rc, 0)

        # Capture first-run payloads.
        first_payloads = {
            aid: zlib.compress(json.dumps(_read_enriched(tmp, aid), sort_keys=True).encode("utf-8"))
            for aid in (1, 2)
        }

        fr2, cr2, rr2, f_calls2, c_calls2, r_calls2 = _default_runners()
        with _StackedPatches(_patch_components(
            figure_runner=fr2, claims_runner=cr2, reference_runner=rr2,
            backend_availability=_default_backend_availability(),
        )):
            rc = _run_and_capture(tmp, [])
        self.assertEqual(rc, 0)

        # Second run made ZERO LLM calls.
        self.assertEqual(f_calls2, [], "second run must hit figure cache; zero LLM calls")
        self.assertEqual(c_calls2, [], "second run must hit claims cache; zero LLM calls")
        self.assertEqual(r_calls2, [], "second run must hit references cache; zero LLM calls")

        # Second run provenance: 100% cache hits per component.
        prov = _read_provenance(tmp)
        for comp in prov["components"]:
            self.assertEqual(comp["cache_miss_count"], 0, f"{comp['component']} had misses on the second run")
            self.assertGreater(comp["cache_hit_count"] + comp["cache_miss_count"], 0)

        # Second run payloads byte-identical to first.
        for aid in (1, 2):
            rec_after = zlib.compress(json.dumps(_read_enriched(tmp, aid), sort_keys=True).encode("utf-8"))
            self.assertEqual(first_payloads[aid], rec_after, f"abstract {aid} drifted across runs")


# ----- US3: Component invalidation -------------------------------------


class ComponentInvalidationTests(_RepoFixture):
    def test_changing_figure_model_invalidates_only_figures(self) -> None:
        tmp = self.tmp_repo()
        abstracts = [_abstract(i) for i in range(1, 4)]
        _write_source_corpus(tmp, abstracts)
        _seed_assets(tmp, abstracts)

        # Baseline run.
        fr1, cr1, rr1, *_ = _default_runners()
        with _StackedPatches(_patch_components(
            figure_runner=fr1, claims_runner=cr1, reference_runner=rr1,
            backend_availability=_default_backend_availability(),
        )):
            rc = _run_and_capture(tmp, [])
        self.assertEqual(rc, 0)

        # Change only the figure model id.
        fr2, cr2, rr2, f_calls2, c_calls2, r_calls2 = _default_runners()
        with _StackedPatches(_patch_components(
            figure_runner=fr2, claims_runner=cr2, reference_runner=rr2,
            backend_availability=_default_backend_availability(),
        )):
            rc = _run_and_capture(tmp, ["--figure-model-id", "gpt-4o"])
        self.assertEqual(rc, 0)

        self.assertEqual(len(f_calls2), 3, "every figure must miss when model changes")
        self.assertEqual(c_calls2, [], "claims must hit cache when only figure model changes")
        self.assertEqual(r_calls2, [], "references must hit cache when only figure model changes")

    def test_invalidate_claims_only(self) -> None:
        tmp = self.tmp_repo()
        abstracts = [_abstract(i) for i in range(1, 4)]
        _write_source_corpus(tmp, abstracts)
        _seed_assets(tmp, abstracts)

        fr1, cr1, rr1, *_ = _default_runners()
        with _StackedPatches(_patch_components(
            figure_runner=fr1, claims_runner=cr1, reference_runner=rr1,
            backend_availability=_default_backend_availability(),
        )):
            _run_and_capture(tmp, [])

        fr2, cr2, rr2, f_calls2, c_calls2, r_calls2 = _default_runners()
        with _StackedPatches(_patch_components(
            figure_runner=fr2, claims_runner=cr2, reference_runner=rr2,
            backend_availability=_default_backend_availability(),
        )):
            _run_and_capture(tmp, ["--invalidate", "claims"])

        self.assertEqual(len(c_calls2), 3)
        self.assertEqual(f_calls2, [])
        self.assertEqual(r_calls2, [])


# ----- US4: Movement handling -----------------------------------------


class MovementHandlingTests(_RepoFixture):
    def test_dropped_abstract_no_longer_in_enriched_corpus(self) -> None:
        tmp = self.tmp_repo()
        run1 = [_abstract(1), _abstract(2), _abstract(3)]
        _write_source_corpus(tmp, run1)
        _seed_assets(tmp, run1)

        fr1, cr1, rr1, *_ = _default_runners()
        with _StackedPatches(_patch_components(
            figure_runner=fr1, claims_runner=cr1, reference_runner=rr1,
            backend_availability=_default_backend_availability(),
        )):
            _run_and_capture(tmp, [])

        # Run 2: drop abstract 1.
        run2 = [_abstract(2), _abstract(3)]
        _write_source_corpus(tmp, run2)

        fr2, cr2, rr2, *_ = _default_runners()
        with _StackedPatches(_patch_components(
            figure_runner=fr2, claims_runner=cr2, reference_runner=rr2,
            backend_availability=_default_backend_availability(),
        )):
            _run_and_capture(tmp, [])

        db_path = tmp / "data" / "primary" / "abstracts_enriched.sqlite"
        con = sqlite3.connect(db_path)
        try:
            ids = {row[0] for row in con.execute("SELECT id FROM abstracts")}
        finally:
            con.close()
        self.assertEqual(ids, {2, 3}, "dropped abstract MUST be absent from run-2 corpus")

    def test_re_accepted_abstract_uses_cache_zero_llm_calls(self) -> None:
        tmp = self.tmp_repo()
        run1 = [_abstract(1), _abstract(2)]
        _write_source_corpus(tmp, run1)
        _seed_assets(tmp, run1)
        fr1, cr1, rr1, *_ = _default_runners()
        with _StackedPatches(_patch_components(
            figure_runner=fr1, claims_runner=cr1, reference_runner=rr1,
            backend_availability=_default_backend_availability(),
        )):
            _run_and_capture(tmp, [])

        # Run 2: drop 1.
        run2 = [_abstract(2)]
        _write_source_corpus(tmp, run2)
        fr2, cr2, rr2, *_ = _default_runners()
        with _StackedPatches(_patch_components(
            figure_runner=fr2, claims_runner=cr2, reference_runner=rr2,
            backend_availability=_default_backend_availability(),
        )):
            _run_and_capture(tmp, [])

        # Run 3: re-accept abstract 1 — its content hash is the
        # same so cache should hit and no LLM call should happen.
        run3 = [_abstract(1), _abstract(2)]
        _write_source_corpus(tmp, run3)
        fr3, cr3, rr3, f_calls3, c_calls3, r_calls3 = _default_runners()
        with _StackedPatches(_patch_components(
            figure_runner=fr3, claims_runner=cr3, reference_runner=rr3,
            backend_availability=_default_backend_availability(),
        )):
            _run_and_capture(tmp, [])

        self.assertEqual(f_calls3, [], "re-accepted abstract MUST hit figure cache")
        self.assertEqual(c_calls3, [], "re-accepted abstract MUST hit claims cache")
        self.assertEqual(r_calls3, [], "re-accepted abstract MUST hit reference cache")

        db_path = tmp / "data" / "primary" / "abstracts_enriched.sqlite"
        con = sqlite3.connect(db_path)
        try:
            ids = {row[0] for row in con.execute("SELECT id FROM abstracts")}
        finally:
            con.close()
        self.assertEqual(ids, {1, 2})


# ----- Parquet export (T033) ------------------------------------------


class TestParquetExport(_RepoFixture):
    """FR-017 — `--export-parquet PATH` writes a Parquet copy after the
    canonical SQLite atomic commit. The module's top-level imports
    stay stdlib-only when the flag is absent."""

    def _ensure_pyarrow(self) -> None:
        try:
            import pyarrow  # noqa: F401
        except ImportError as exc:
            self.fail(
                f"pyarrow is required for the Parquet-export test. "
                f"Install via `pip install ohbm2026[parquet]`. (ImportError: {exc})"
            )

    def test_export_parquet_writes_both_artifacts(self) -> None:
        self._ensure_pyarrow()
        tmp = self.tmp_repo()
        abstracts = [_abstract(1), _abstract(2)]
        _write_source_corpus(tmp, abstracts)
        _seed_assets(tmp, abstracts)
        fr, cr, rr, *_ = _default_runners()
        with _StackedPatches(_patch_components(
            figure_runner=fr, claims_runner=cr, reference_runner=rr,
            backend_availability=_default_backend_availability(),
        )):
            rc = _run_and_capture(tmp, ["--export-parquet", "data/primary/abstracts_enriched.parquet"])
        self.assertEqual(rc, 0)
        self.assertTrue((tmp / "data/primary/abstracts_enriched.sqlite").exists())
        self.assertTrue((tmp / "data/primary/abstracts_enriched.parquet").exists())
        prov = _read_provenance(tmp)
        self.assertEqual(prov["parquet_export_path"], "data/primary/abstracts_enriched.parquet")

    def test_no_pyarrow_import_when_flag_absent(self) -> None:
        # Drop pyarrow from sys.modules so we can detect re-import.
        for mod in list(sys.modules):
            if mod.startswith("pyarrow"):
                del sys.modules[mod]

        tmp = self.tmp_repo()
        _write_source_corpus(tmp, [_abstract(1)])
        _seed_assets(tmp, [_abstract(1)])
        fr, cr, rr, *_ = _default_runners()
        with _StackedPatches(_patch_components(
            figure_runner=fr, claims_runner=cr, reference_runner=rr,
            backend_availability=_default_backend_availability(),
        )):
            rc = _run_and_capture(tmp, [])
        self.assertEqual(rc, 0)
        self.assertNotIn("pyarrow", sys.modules, "pyarrow MUST NOT be imported when --export-parquet is absent")
        # And no Parquet file emitted.
        self.assertEqual(list((tmp / "data/primary").glob("*.parquet")), [])


if __name__ == "__main__":
    unittest.main()
