"""Candidate #5: single-file DuckDB container.

One ``main.duckdb`` file with all tables. Same logical schema as
``sqlite_single`` but using DuckDB's columnar storage + zstd
compression on string columns + dictionary encoding on low-cardinality
columns. No FTS5 (DuckDB ships a separate full-text extension; the
bench measures the no-FTS variant).

The browser-side decoder uses ``@duckdb/duckdb-wasm`` and loads the
file via the WASM ``register_file`` API — DuckDB-WASM does not have
a range-read VFS today, so first-paint cost is dominated by the full
file fetch.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

import duckdb

__all__ = ["write"]


def _sql_safe(name: str) -> str:
    return name.replace("-", "_").replace(" ", "_")


def _emit_cell_table(con, cell_key: str, envelope: Mapping[str, Any]) -> None:
    table = f"cell_{_sql_safe(cell_key)}"
    rows = []
    for r in envelope["rows"]:
        rows.append(
            {
                "abstract_id": int(r["abstract_id"]),
                "umap2d_x": (r.get("umap2d") or [None, None])[0],
                "umap2d_y": (r.get("umap2d") or [None, None])[1],
                "umap3d_x": (r.get("umap3d") or [None, None, None])[0],
                "umap3d_y": (r.get("umap3d") or [None, None, None])[1],
                "umap3d_z": (r.get("umap3d") or [None, None, None])[2],
                "community_id": r.get("community_id"),
                "topic_cluster_id": r.get("topic_cluster_id"),
                "neuroscape_cluster_id": r.get("neuroscape_cluster_id"),
                "umap_missing": bool(r.get("umap_missing", False)),
            }
        )
    if not rows:
        return
    con.execute(f"DROP TABLE IF EXISTS {table}")
    # DuckDB's CREATE TABLE AS infers schema from the first batch.
    con.register("tmp_cell_rows", _to_arrow(rows))
    con.execute(f"CREATE TABLE {table} AS SELECT * FROM tmp_cell_rows")
    con.unregister("tmp_cell_rows")


def _to_arrow(rows: list[dict]):
    import pyarrow as pa
    return pa.Table.from_pylist(rows)


def write(
    *,
    output_dir: Path,
    build_info: Mapping[str, Any],
    conference_id: str,
    manifest: Mapping[str, Any],
    abstracts_envelope: Mapping[str, Any],
    authors_envelope: Mapping[str, Any],
    cells_envelopes: Mapping[str, Mapping[str, Any]],
    topics_envelopes: Mapping[tuple[str, str, str], Mapping[str, Any]],
    neighbors_envelopes: Mapping[str, Mapping[str, Any]],
    enrichment_envelope: Mapping[str, Any],
    minilm_bin: bytes | None,
    minilm_sidecar: Mapping[str, Any],
) -> set[Path]:
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    db_path = out / "main.duckdb"
    if db_path.exists():
        db_path.unlink()

    con = duckdb.connect(str(db_path))
    try:
        # Meta table.
        con.execute(
            """
            CREATE TABLE meta (
                key VARCHAR PRIMARY KEY,
                value VARCHAR
            )
            """
        )
        con.executemany(
            "INSERT INTO meta VALUES (?, ?)",
            [
                ("schema_version", str(manifest.get("schema_version", ""))),
                ("format", "duckdb-single"),
                ("conference_id", conference_id),
                ("build_info_json", json.dumps(dict(build_info), sort_keys=True)),
                ("manifest_json", json.dumps(manifest, sort_keys=True)),
            ],
        )

        # Abstracts: same flat shape as SQLite (JSON columns for the
        # nested structs). DuckDB *does* support STRUCT natively, but
        # the cross-format apples-to-apples comparison wants the same
        # logical schema; the bench measures both raw size + access
        # patterns. Phase 4 may upgrade to native STRUCT once the
        # bench commits to this candidate.
        abstract_rows = []
        for r in abstracts_envelope["abstracts"]:
            abstract_rows.append(
                {
                    "abstract_id": int(r["abstract_id"]),
                    "poster_id": str(r["poster_id"]),
                    "title": str(r.get("title", "")),
                    "accepted_for": str(r.get("accepted_for", "Unknown")),
                    "sections": json.dumps(r.get("sections", {}), sort_keys=True),
                    "topics": json.dumps(r.get("topics", {}), sort_keys=True),
                    "methods_checklist": json.dumps(r.get("methods_checklist", [])),
                    "facets": json.dumps(r.get("facets", {}), sort_keys=True),
                    "author_ids": json.dumps(r.get("author_ids", [])),
                    "reference_dois": json.dumps(r.get("reference_dois", [])),
                    "reference_urls": json.dumps(r.get("reference_urls", [])),
                    "reference_titles": json.dumps(r.get("reference_titles", [])),
                }
            )
        con.register("tmp_abstracts", _to_arrow(abstract_rows))
        con.execute("CREATE TABLE abstracts AS SELECT * FROM tmp_abstracts")
        con.unregister("tmp_abstracts")
        con.execute("CREATE INDEX abstracts_poster_id ON abstracts(poster_id)")

        # Authors.
        author_rows = []
        for a in authors_envelope["authors"]:
            author_rows.append(
                {
                    "author_id": int(a["author_id"]),
                    "name": str(a.get("name", "")),
                    "affiliations": json.dumps(a.get("affiliations", [])),
                    "abstract_ids": json.dumps(a.get("abstract_ids", [])),
                }
            )
        con.register("tmp_authors", _to_arrow(author_rows))
        con.execute("CREATE TABLE authors AS SELECT * FROM tmp_authors")
        con.unregister("tmp_authors")

        # Cells / topics / neighbours — one table each.
        for cell_key, env in cells_envelopes.items():
            _emit_cell_table(con, cell_key, env)
        for triple, env in topics_envelopes.items():
            model, inp, kind = triple
            tbl = f"topic_{_sql_safe(model)}_{_sql_safe(inp)}_{_sql_safe(kind)}"
            rows = [
                {
                    "cluster_id": int(r["cluster_id"]),
                    "title": r.get("title", ""),
                    "description": r.get("description", ""),
                    "focus": r.get("focus", ""),
                    "keywords": json.dumps(r.get("keywords", [])),
                }
                for r in env["topics"]
            ]
            if rows:
                con.register("tmp_topic", _to_arrow(rows))
                con.execute(f"CREATE TABLE {tbl} AS SELECT * FROM tmp_topic")
                con.unregister("tmp_topic")
        for cell_key, env in neighbors_envelopes.items():
            tbl = f"neighbours_{_sql_safe(cell_key)}"
            rows = []
            for idx, aid in enumerate(env["abstract_ids"]):
                rows.append(
                    {
                        "abstract_id": int(aid),
                        "nearest_ids": json.dumps(env["nearest_ids"][idx]),
                        "nearest_distances": json.dumps(env["nearest_distances"][idx]),
                        "farthest_ids": json.dumps(env["farthest_ids"][idx]),
                        "farthest_distances": json.dumps(env["farthest_distances"][idx]),
                    }
                )
            if rows:
                con.register("tmp_nbr", _to_arrow(rows))
                con.execute(f"CREATE TABLE {tbl} AS SELECT * FROM tmp_nbr")
                con.unregister("tmp_nbr")

        # Enrichment.
        claim_rows: list[dict] = []
        figure_rows: list[dict] = []
        for aid_str, rec in enrichment_envelope.get("records", {}).items():
            aid = int(aid_str)
            for i, c in enumerate(rec.get("claims", []) or []):
                claim_rows.append(
                    {
                        "abstract_id": aid,
                        "claim_index": i,
                        "text": c.get("text"),
                        "source": c.get("source"),
                        "evidence": c.get("evidence"),
                        "evidence_eco_codes": json.dumps(
                            c.get("evidence_eco_codes", [])
                        ),
                        "confidence": c.get("confidence"),
                    }
                )
            for i, f in enumerate(rec.get("figures", []) or []):
                figure_rows.append(
                    {
                        "abstract_id": aid,
                        "figure_index": i,
                        "figure_id": f.get("figure_id"),
                        "caption_guess": f.get("caption_guess"),
                        "interpretation": f.get("interpretation"),
                        "ocr_text": f.get("ocr_text"),
                        "keywords": json.dumps(f.get("keywords", [])),
                    }
                )
        if claim_rows:
            con.register("tmp_claims", _to_arrow(claim_rows))
            con.execute("CREATE TABLE enrichment_claims AS SELECT * FROM tmp_claims")
            con.unregister("tmp_claims")
            con.execute(
                "CREATE INDEX enrichment_claims_aid ON enrichment_claims(abstract_id)"
            )
        if figure_rows:
            con.register("tmp_figs", _to_arrow(figure_rows))
            con.execute("CREATE TABLE enrichment_figures AS SELECT * FROM tmp_figs")
            con.unregister("tmp_figs")
            con.execute(
                "CREATE INDEX enrichment_figures_aid ON enrichment_figures(abstract_id)"
            )

        # MiniLM vectors (one BLOB row per abstract).
        con.execute(
            """
            CREATE TABLE vectors_meta (
                key VARCHAR PRIMARY KEY,
                value VARCHAR
            )
            """
        )
        con.executemany(
            "INSERT INTO vectors_meta VALUES (?, ?)",
            [
                ("shape", json.dumps(minilm_sidecar.get("shape", []))),
                ("dtype", minilm_sidecar.get("dtype", "int8")),
                ("metadata_json", json.dumps(minilm_sidecar, sort_keys=True)),
            ],
        )
        con.execute(
            """
            CREATE TABLE vectors (
                abstract_id INTEGER PRIMARY KEY,
                vector_int8 BLOB
            )
            """
        )
        if minilm_bin is not None:
            shape = minilm_sidecar.get("shape") or [0, 384]
            n_rows, dim = int(shape[0]), int(shape[1])
            row_bytes = dim
            if len(minilm_bin) == n_rows * row_bytes:
                abstract_ids = minilm_sidecar.get("abstract_ids") or list(range(n_rows))
                rows = []
                for i, aid in enumerate(abstract_ids[:n_rows]):
                    start = i * row_bytes
                    rows.append((int(aid), minilm_bin[start : start + row_bytes]))
                con.executemany("INSERT INTO vectors VALUES (?, ?)", rows)

        # Cross-conference links (empty for OHBM-only deploy).
        con.execute(
            """
            CREATE TABLE cross_conference_links (
                conf_a VARCHAR NOT NULL,
                id_a VARCHAR NOT NULL,
                conf_b VARCHAR NOT NULL,
                id_b VARCHAR NOT NULL,
                link_kind VARCHAR,
                similarity REAL,
                metadata VARCHAR,
                PRIMARY KEY (conf_a, id_a, conf_b, id_b, link_kind)
            )
            """
        )

        con.commit()
        # DuckDB doesn't have a VACUUM; CHECKPOINT flushes the WAL.
        con.execute("CHECKPOINT")
    finally:
        con.close()

    return {db_path}
