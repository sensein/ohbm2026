"""Tests for `ohbm2026.analyze.stage`.

Per spec FR-001 / FR-002 / FR-003 / FR-013, the Stage 4 orchestrator
must:
- Resolve the full `(model, input, kind)` matrix into a deterministic
  plan with auto-skip for dim-incompatible `(model, neuroscape_clusters)`.
- Refuse to overwrite a bundle whose recorded `corpus_state_key`
  differs from the current run's.
- Honor `--dry-run` by emitting the plan + writing nothing.
- Honor `--strict-matrix` by escalating auto-skips to typed errors.

All tests chdir into a tmpdir before running so cache/output/provenance
paths can be project-relative (CA-008 / Principle VIII).
"""

from __future__ import annotations

import io
import json
import os
import shutil
import tempfile
import unittest
from contextlib import contextmanager, redirect_stdout
from pathlib import Path
from unittest import mock

import numpy as np


@contextmanager
def _isolated_cwd():
    """Enter a fresh tmpdir as cwd; restore on exit."""
    original = Path.cwd()
    tmp = tempfile.mkdtemp()
    try:
        os.chdir(tmp)
        yield Path(tmp)
    finally:
        os.chdir(original)
        shutil.rmtree(tmp, ignore_errors=True)

from ohbm2026.analyze import stage as stage_mod
from ohbm2026.analyze.stage import (
    AnalysisConfig,
    DEFAULT_KINDS,
    DEFAULT_MODELS,
    DEFAULT_INPUTS,
    build_plan,
    main,
    register_kind_runner,
    run_matrix,
)
from ohbm2026.exceptions import (
    AnalysisError,
    InputBundleMissing,
)


def _seed_stage3_bundles(
    embeddings_root: Path,
    *,
    models: list[str],
    components: list[str],
    state_key: str,
    n_rows: int = 3,
) -> None:
    """Synthesize Stage 3 bundle directories with `vectors.npy` + `ids.npy`."""
    for model in models:
        for component in components:
            bundle = embeddings_root / model / f"{component}__{state_key}"
            bundle.mkdir(parents=True)
            np.save(bundle / "ids.npy", np.arange(1, n_rows + 1, dtype=np.int64))
            np.save(bundle / "vectors.npy", np.zeros((n_rows, 8), dtype=np.float32))
            (bundle / "metadata.json").write_text(
                json.dumps({"model": model, "component": component, "n_rows": n_rows})
            )


def _baseline_config(*, kinds=None, models=None) -> AnalysisConfig:
    """Build a config using cwd-relative paths so provenance is project-safe."""
    return AnalysisConfig(
        embeddings_root=Path("data/outputs/embeddings"),
        output_root=Path("data/outputs/analysis"),
        cache_root=Path("data/cache/analysis"),
        provenance_root=Path("data/provenance/analysis"),
        corpus_state_key="abc123def456",
        models=tuple(models or DEFAULT_MODELS),
        inputs=DEFAULT_INPUTS,
        kinds=tuple(kinds or DEFAULT_KINDS),
        rollup_path=Path("data/outputs/analysis/annotations__abc123def456.parquet"),
        sqlite_path=Path("data/outputs/analysis/annotations__abc123def456.sqlite"),
        neuroscape_centroids_dir=Path("data/inputs/neuroscape"),
    )


class BuildPlanTests(unittest.TestCase):
    def test_default_matrix_includes_dim_incompat_skips(self) -> None:
        with _isolated_cwd() as tmp:
            _seed_stage3_bundles(
                Path("data/outputs/embeddings"),
                models=list(DEFAULT_MODELS),
                components=["title", "claims"],
                state_key="abc123def456",
            )
            config = _baseline_config()
            plan = build_plan(config)
            # 5 models × 2 inputs × 4 kinds = 40 entries (incl. skips)
            self.assertEqual(len(plan.entries), 40)
            # 3 models × 2 inputs × 1 kind = 6 should be marked skipped
            skipped = [e for e in plan.entries if e.skipped]
            self.assertEqual(len(skipped), 6)
            for entry in skipped:
                self.assertEqual(entry.kind, "neuroscape_clusters")
                self.assertNotIn(entry.model_key, {"voyage", "neuroscape"})
                self.assertEqual(entry.skip_reason, "dim_incompatible")

    def test_strict_matrix_raises_for_dim_incompat(self) -> None:
        with _isolated_cwd() as tmp:
            _seed_stage3_bundles(
                Path("data/outputs/embeddings"),
                models=["minilm"],
                components=["title"],
                state_key="abc123def456",
            )
            config = AnalysisConfig(
                embeddings_root=Path("data/outputs/embeddings"),
                output_root=tmp / "out",
                cache_root=tmp / "cache",
                provenance_root=tmp / "prov",
                corpus_state_key="abc123def456",
                models=("minilm",),
                inputs=("abstract",),
                kinds=("neuroscape_clusters",),
                strict_matrix=True,
            )
            with self.assertRaises(AnalysisError):
                build_plan(config)

    def test_missing_input_bundle_raises(self) -> None:
        with _isolated_cwd() as tmp:
            (Path("data/outputs/embeddings")).mkdir(parents=True)
            config = _baseline_config(kinds=["projections"], models=["voyage"])
            with self.assertRaises(InputBundleMissing):
                build_plan(config)

    def test_run_state_key_deterministic(self) -> None:
        with _isolated_cwd() as tmp:
            _seed_stage3_bundles(
                Path("data/outputs/embeddings"),
                models=["voyage"],
                components=["title", "claims"],
                state_key="abc123def456",
            )
            config = _baseline_config(kinds=["projections"], models=["voyage"])
            plan_a = build_plan(config)
            plan_b = build_plan(config)
            self.assertEqual(plan_a.run_state_key, plan_b.run_state_key)
            self.assertEqual(len(plan_a.run_state_key), 12)


class DryRunTests(unittest.TestCase):
    def test_dry_run_resolves_matrix_without_writing(self) -> None:
        with _isolated_cwd() as tmp:
            _seed_stage3_bundles(
                Path("data/outputs/embeddings"),
                models=["voyage"],
                components=["title", "claims"],
                state_key="abc123def456",
            )
            config = _baseline_config(kinds=["projections"], models=["voyage"])
            object.__setattr__(config, "_dry_run_dummy", None)  # ignore - just to demonstrate
            # Use dataclasses.replace pattern via __dict__
            from dataclasses import replace
            config = replace(config, dry_run=True)

            stdout = io.StringIO()
            with redirect_stdout(stdout):
                rc = run_matrix(config)
            self.assertEqual(rc, 0)
            output = stdout.getvalue()
            event = json.loads([line for line in output.strip().splitlines() if "dry_run_plan" in line][0])
            self.assertEqual(event["event"], "dry_run_plan")
            self.assertEqual(event["n_entries"], 2)  # voyage × 2 inputs × 1 kind
            self.assertEqual(event["n_to_run"], 2)
            # No bundle directory was created
            self.assertFalse(Path("data/outputs/analysis").exists())


class StateKeyCollisionTests(unittest.TestCase):
    def test_corpus_state_key_collision_refused(self) -> None:
        with _isolated_cwd() as tmp:
            _seed_stage3_bundles(
                Path("data/outputs/embeddings"),
                models=["voyage"],
                components=["title", "claims"],
                state_key="abc123def456",
            )
            config = _baseline_config(kinds=["projections"], models=["voyage"])

            # Pre-write a bundle dir with a stale corpus_state_key recorded in its provenance.
            from dataclasses import replace
            from ohbm2026.analyze.stage import _bundle_output_path, _kind_state_key

            entry = stage_mod.PlanEntry(
                model_key="voyage",
                input_source="abstract",
                kind="projections",
                bundle_path=Path("data/outputs/embeddings") / "voyage" / "title__abc123def456",
            )
            collision_path = _bundle_output_path(config, entry)
            collision_path.mkdir(parents=True)
            (collision_path / "provenance.json").write_text(
                json.dumps({"corpus_state_key": "WRONG_KEY_DIFFERENT"})
            )

            # Register a no-op runner so dispatch doesn't fall through to NotImplementedError.
            register_kind_runner("projections", lambda c, e: {"cache": "miss"})
            try:
                stdout = io.StringIO()
                with redirect_stdout(stdout):
                    rc = run_matrix(config)
            finally:
                del stage_mod.KIND_RUNNERS["projections"]

            self.assertEqual(rc, 1)
            events = [json.loads(line) for line in stdout.getvalue().strip().splitlines() if line.startswith("{")]
            skip_events = [e for e in events if e.get("event") == "bundle_skipped"]
            self.assertTrue(
                any(e.get("reason") == "corpus_state_key_collision" for e in skip_events),
                f"expected corpus_state_key_collision event; got {skip_events}",
            )


class MainCLITests(unittest.TestCase):
    def test_dry_run_via_cli(self) -> None:
        with _isolated_cwd() as tmp:
            _seed_stage3_bundles(
                Path("data/outputs/embeddings"),
                models=["voyage"],
                components=["title", "claims"],
                state_key="abc123def456",
            )
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                rc = main(
                    [
                        "--embeddings-root", str(Path("data/outputs/embeddings")),
                        "--output-root", "data/outputs/analysis",
                        "--cache-root", "data/cache/analysis",
                        "--provenance-root", "data/provenance/analysis",
                        "--neuroscape-centroids", "data/inputs/neuroscape",
                        "--models", "voyage",
                        "--inputs", "abstract", "claims",
                        "--kinds", "projections",
                        "--dry-run",
                    ]
                )
            self.assertEqual(rc, 0)
            self.assertIn('"event": "dry_run_plan"', stdout.getvalue())

    def test_missing_input_bundle_returns_2(self) -> None:
        with _isolated_cwd() as tmp:
            (Path("data/outputs/embeddings")).mkdir(parents=True)
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                rc = main(
                    [
                        "--embeddings-root", str(Path("data/outputs/embeddings")),
                        "--output-root", "out",
                        "--cache-root", "cache",
                        "--provenance-root", "prov",
                        "--neuroscape-centroids", "nsc",
                        "--corpus-state-key", "abc123def456",
                        "--models", "voyage",
                        "--inputs", "abstract",
                        "--kinds", "projections",
                    ]
                )
            self.assertEqual(rc, 2)
            events = [json.loads(line) for line in stdout.getvalue().strip().splitlines() if line.startswith("{")]
            self.assertTrue(any(e.get("type") == "InputBundleMissing" for e in events))


if __name__ == "__main__":
    unittest.main()
