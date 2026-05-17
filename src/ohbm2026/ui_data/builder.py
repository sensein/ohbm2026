"""Stage 6 orchestrator — builds the full UI data package (T018).

Calls each sub-builder, runs the 8 cross-shard invariants from data-model.md
§8 (most importantly: accepted-only + positional join + every shard carries
a byte-identical ``build_info`` block), and writes shards atomically to
``--output``.
"""

from __future__ import annotations

import json
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from ohbm2026.ui_data.abstracts import build_abstracts
from ohbm2026.ui_data.authors import build_authors
from ohbm2026.ui_data.cells import build_cells
from ohbm2026.ui_data.manifest import build_manifest, make_build_info
from ohbm2026.ui_data.state_key import (
    Stage6BuildError,
    discover_rollup_state_key,
)
from ohbm2026.ui_data.topics import build_topics


__all__ = ["build_ui_data_package", "Stage6BuildError"]


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w") as fh:
        json.dump(payload, fh, ensure_ascii=False, separators=(",", ":"), sort_keys=False)
        fh.write("\n")
    tmp.replace(path)


def _resolve_rollup(
    *,
    rollup: Path | None,
    analysis_root: Path | None,
    discover: bool,
) -> Path:
    if rollup is not None:
        return Path(rollup)
    if discover and analysis_root is not None:
        state_key = discover_rollup_state_key(Path(analysis_root))
        return Path(analysis_root) / f"annotations__{state_key}.sqlite"
    raise Stage6BuildError(
        "Must pass either --rollup or --discover-rollup with --analysis-root"
    )


def build_ui_data_package(
    *,
    corpus_path: Path,
    withdrawn_path: Path | None,
    authors_path: Path,
    enriched_path: Path | None,
    references_path: Path | None,
    analysis_root: Path | None,
    rollup: Path | None,
    discover_rollup: bool,
    output_dir: Path,
    build_info: Mapping[str, str] | None = None,
) -> int:
    """Run the full Stage 6 build.

    Returns 0 on success, non-zero on any invariant failure (per
    contracts/data-package.md exit codes).
    """

    rollup_db = _resolve_rollup(
        rollup=rollup,
        analysis_root=analysis_root,
        discover=discover_rollup,
    )

    if build_info is None:
        build_info = make_build_info(
            corpus_path=Path(corpus_path),
            rollup_db=rollup_db,
            analysis_root=Path(analysis_root) if analysis_root else None,
        )

    # Build authors first to derive the raw→synthetic id remap; the abstracts
    # builder uses it so `author_ids` references match the authors shard
    # directly (closes invariant 4).
    authors_envelope, author_id_remap = build_authors(
        corpus_path=Path(corpus_path),
        authors_path=Path(authors_path),
        build_info=build_info,
        return_remap=True,
    )

    abstracts_envelope = build_abstracts(
        corpus_path=Path(corpus_path),
        enriched_path=Path(enriched_path) if enriched_path else None,
        references_path=Path(references_path) if references_path else None,
        withdrawn_path=Path(withdrawn_path) if withdrawn_path else None,
        build_info=build_info,
        author_id_remap=author_id_remap,
    )
    abstract_records = abstracts_envelope["abstracts"]
    abstract_ids = [r["abstract_id"] for r in abstract_records]

    # Manifest discovers cells/inputs/models/facets from the rollup + records.
    manifest = build_manifest(
        abstracts=abstract_records,
        rollup_db=rollup_db,
        build_info=build_info,
    )

    cells_envelopes = build_cells(
        rollup_db=rollup_db,
        abstract_ids=abstract_ids,
        build_info=build_info,
        analysis_root=Path(analysis_root) if analysis_root else None,
    )

    topics_envelopes = build_topics(
        rollup_db=rollup_db,
        build_info=build_info,
    )

    # --- 8 cross-shard invariants (data-model.md §8) ---------------------
    _validate_invariants(
        manifest=manifest,
        abstracts=abstracts_envelope,
        authors=authors_envelope,
        cells=cells_envelopes,
        topics=topics_envelopes,
        build_info=build_info,
    )

    # --- Atomic write ----------------------------------------------------
    output = Path(output_dir)
    with tempfile.TemporaryDirectory(prefix=".ui-data-", dir=output.parent if output.parent.exists() else None) as tmp_root:
        staging = Path(tmp_root) / "data"
        staging.mkdir(parents=True, exist_ok=True)
        _write_json(staging / "manifest.json", manifest)
        _write_json(staging / "abstracts.json", abstracts_envelope)
        _write_json(staging / "authors.json", authors_envelope)
        for cell_key, envelope in cells_envelopes.items():
            _write_json(staging / "cells" / f"{cell_key}.json", envelope)
        for (model, inp, kind), envelope in topics_envelopes.items():
            _write_json(staging / "topics" / f"{model}_{inp}_{kind}.json", envelope)
        # Search shards (lexical_index + minilm_vectors) are populated by
        # US3 builders; the skeleton writes placeholder build_info sidecars
        # so the manifest's referenced URLs always 200.
        _write_json(
            staging / "search" / "minilm_vectors.build_info.json",
            {
                "schema_version": "minilm_vectors.v1",
                "build_info": dict(build_info),
                "shape": [len(abstract_ids), 384],
                "dtype": "int8",
                "byte_offset_url": "data/search/minilm_vectors.bin",
            },
        )

        # Move into place atomically (replacing existing data/ if any).
        if output.exists():
            backup = output.with_name(output.name + ".prev")
            if backup.exists():
                import shutil
                shutil.rmtree(backup)
            output.rename(backup)
            staging.rename(output)
            import shutil
            shutil.rmtree(backup)
        else:
            output.parent.mkdir(parents=True, exist_ok=True)
            staging.rename(output)

    return 0


def _validate_invariants(
    *,
    manifest: Mapping[str, Any],
    abstracts: Mapping[str, Any],
    authors: Mapping[str, Any],
    cells: Mapping[str, Mapping[str, Any]],
    topics: Mapping[tuple[str, str, str], Mapping[str, Any]],
    build_info: Mapping[str, str],
) -> None:
    """Enforce the 8 cross-shard invariants from data-model.md §8."""

    expected_count = manifest["corpus_count"]
    abstract_records = abstracts["abstracts"]

    # 1. Corpus count matches.
    if len(abstract_records) != expected_count:
        raise Stage6BuildError(
            f"Invariant 1 violated: manifest.corpus_count={expected_count} but "
            f"abstracts shard has {len(abstract_records)} records"
        )

    # 2. Each cell shard has the same count + positional order.
    abstract_ids = [r["abstract_id"] for r in abstract_records]
    for cell_key, envelope in cells.items():
        rows = envelope["rows"]
        if len(rows) != expected_count:
            raise Stage6BuildError(
                f"Invariant 2 violated: cell {cell_key} has {len(rows)} rows, expected {expected_count}"
            )
        for idx, (aid, row) in enumerate(zip(abstract_ids, rows)):
            if row["abstract_id"] != aid:
                raise Stage6BuildError(
                    f"Invariant 2 violated: cell {cell_key} row {idx} abstract_id={row['abstract_id']} "
                    f"!= abstracts[{idx}].abstract_id={aid}"
                )

    # 3. Accepted-only invariant.
    leaked = [r["abstract_id"] for r in abstract_records if r.get("accepted_for") == "Withdrawn"]
    if leaked:
        raise Stage6BuildError(
            f"Invariant 3 violated: {len(leaked)} withdrawn records leaked into abstracts shard "
            f"(ids: {leaked[:5]}{'...' if len(leaked) > 5 else ''})"
        )

    # 4. Author referential integrity (now enforced — see US1 remap in
    #    abstracts.build_abstracts_records).
    author_ids = {a["author_id"] for a in authors["authors"]}
    missing: set[int] = set()
    for record in abstract_records:
        for aid in record.get("author_ids", []):
            if aid not in author_ids:
                missing.add(aid)
    if missing:
        raise Stage6BuildError(
            f"Invariant 4 violated: {len(missing)} author_id reference(s) on abstracts have no "
            f"matching authors record (ids: {sorted(missing)[:5]}{'...' if len(missing) > 5 else ''})"
        )

    # 5. Cluster id integrity (community / topic / neuroscape) per cell.
    topic_by_key: dict[tuple[str, str, str], set[int]] = {
        triple: {t["cluster_id"] for t in envelope["topics"]}
        for triple, envelope in topics.items()
    }
    for cell_key, envelope in cells.items():
        model, inp = cell_key.split("_", 1)
        comm_topics = topic_by_key.get((model, inp, "communities"), set())
        topic_topics = topic_by_key.get((model, inp, "topic_clusters"), set())
        neuro_topics = topic_by_key.get((model, inp, "neuroscape_clusters"), set())
        for row in envelope["rows"]:
            comm = row.get("community_id")
            if comm is not None and comm >= 0 and comm not in comm_topics:
                raise Stage6BuildError(
                    f"Invariant 5 violated: cell {cell_key} row references community_id={comm} "
                    f"absent from topics/communities shard"
                )
            tc = row.get("topic_cluster_id")
            if tc is not None and tc >= 0 and tc not in topic_topics:
                raise Stage6BuildError(
                    f"Invariant 5 violated: cell {cell_key} row references topic_cluster_id={tc} "
                    f"absent from topics/topic_clusters shard"
                )
            nc = row.get("neuroscape_cluster_id")
            if nc is not None and nc >= 0 and nc not in neuro_topics:
                raise Stage6BuildError(
                    f"Invariant 5 violated: cell {cell_key} row references neuroscape_cluster_id={nc} "
                    f"absent from topics/neuroscape_clusters shard"
                )

    # 6. Every shard carries a byte-identical build_info block.
    reference = dict(build_info)
    _assert_build_info_match(manifest["build_info"], reference, "manifest")
    _assert_build_info_match(abstracts["build_info"], reference, "abstracts")
    _assert_build_info_match(authors["build_info"], reference, "authors")
    for cell_key, envelope in cells.items():
        _assert_build_info_match(envelope["build_info"], reference, f"cells/{cell_key}")
    for triple, envelope in topics.items():
        label = f"topics/{triple[0]}_{triple[1]}_{triple[2]}"
        _assert_build_info_match(envelope["build_info"], reference, label)

    # 7. Link checker — deferred to US7 (T086) so the skeleton build can pass
    #    before the references registry exists.
    # 8. Size budget — checked by the deploy workflow's du/SC-006 step, not
    #    inside the builder.


def _assert_build_info_match(actual: Mapping[str, Any], expected: Mapping[str, Any], label: str) -> None:
    if dict(actual) != dict(expected):
        raise Stage6BuildError(
            f"Invariant 6 violated: build_info mismatch on {label}: {dict(actual)} != {dict(expected)}"
        )
