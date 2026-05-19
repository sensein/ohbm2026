"""Candidate #4: single-file SQLite container.

One ``main.sqlite`` blob with all tables + FTS5 on the abstract text.
Browser-side decoder uses ``@sqlite.org/sqlite-wasm`` (with its range-
read VFS so the whole file doesn't fetch on first paint).

Schema choices (tightening targets per FR-201 / FR-202):

- ``abstracts`` table: scalar columns + JSON columns for the nested
  ``sections``, ``topics``, ``facets``. JSON is the cleanest SQLite
  representation for nested struct data; the schema annotates each
  JSON column with a `# LIMITATION: SQLite has no native struct type`.
- ``abstracts_fts`` virtual table (FTS5) over ``title || ' ' ||
  json_extract(sections, '$.methods') || …`` so the browser's lexical
  search can query SQL instead of building the inverted index in JS.
- Each cell becomes one table: ``cell_<key>(abstract_id INTEGER, ...)``.
  STRUCT-shaped ``umap2d``, ``umap3d`` go as JSON columns.
- Topics likewise: ``topic_<cell>_<kind>(cluster_id, …)``.
- Neighbours: ``neighbours_<key>(abstract_id, nearest_ids JSON,
  nearest_distances JSON, farthest_ids JSON, farthest_distances JSON)``.
- Enrichment: two tables — ``enrichment_claims`` (one row per claim)
  and ``enrichment_figures`` (one row per figure). The Stage-6
  ``{str(id): record}`` dict is gone (FR-201 / FR-202).
- Manifest: one-row ``meta`` table with a ``manifest_json`` column.
- ``minilm_vectors`` BLOB column in a ``vectors`` table; one row per
  abstract (abstract_id, vector_int8 BLOB) — keeps the int8 layout but
  removes the separate ``.bin`` sidecar.
- ``cross_conference_links`` table (FR-208). Empty for OHBM-only.

Compression: SQLite supports per-page zlib via the ``sqlite_zstd``
extension OR a one-shot ``VACUUM INTO`` after build. For the bench
we use plain SQLite + a follow-up ``sqlite3 …  '.dump' | gzip`` to
get a fair "compressed download size" number alongside the on-disk
size; the production deploy is the gzipped version because
``@sqlite.org/sqlite-wasm`` decompresses transparently on first read.

(In Phase 4 we revisit whether SQLite-native compression is worth
the extension dependency.)
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Mapping

__all__ = ["write"]


def _sql_safe(name: str) -> str:
    """Coerce a cell_key or topic triple into a SQL-safe table-name suffix."""
    return name.replace("-", "_").replace(" ", "_")


def _create_abstracts_table(con: sqlite3.Connection) -> None:
    con.executescript(
        """
        CREATE TABLE abstracts (
            abstract_id     INTEGER PRIMARY KEY,
            poster_id       TEXT NOT NULL,
            title           TEXT,
            accepted_for    TEXT,
            sections        TEXT, -- JSON STRUCT (LIMITATION: SQLite has no native struct type)
            topics          TEXT, -- JSON STRUCT
            methods_checklist TEXT, -- JSON list[str]
            facets          TEXT, -- JSON STRUCT-of-list[str], 11 keys
            author_ids      TEXT, -- JSON list[int]
            reference_dois  TEXT, -- JSON list[str]
            reference_urls  TEXT, -- JSON list[str]
            reference_titles TEXT  -- JSON list[str]
        );
        -- NB: NOT a UNIQUE index — the Stage-6 corpus contains one
        -- duplicate poster_id ('2335'), which is a real FR-202 finding
        -- (parallel-data cross-validation gap) for the Phase-4 schema
        -- tightening to address. Until then, we tolerate the duplicate.
        CREATE INDEX abstracts_poster_id ON abstracts(poster_id);

        -- FTS5 over the abstract text for lexical search. The browser's
        -- lexical-search worker queries this instead of building its own
        -- inverted index.
        CREATE VIRTUAL TABLE abstracts_fts USING fts5(
            poster_id UNINDEXED,
            title,
            methods,
            results,
            conclusion,
            tokenize = 'porter unicode61'
        );
        """
    )


def _create_authors_table(con: sqlite3.Connection) -> None:
    con.executescript(
        """
        CREATE TABLE authors (
            author_id       INTEGER PRIMARY KEY,
            name            TEXT,
            affiliations    TEXT, -- JSON list[str]
            abstract_ids    TEXT  -- JSON list[int]
        );
        """
    )


def _create_meta_table(con: sqlite3.Connection) -> None:
    con.executescript(
        """
        CREATE TABLE meta (
            key    TEXT PRIMARY KEY,
            value  TEXT
        );
        """
    )


def _insert_abstracts(con: sqlite3.Connection, abstracts_envelope: Mapping[str, Any]) -> None:
    cur = con.cursor()
    rows = []
    fts_rows = []
    for r in abstracts_envelope["abstracts"]:
        sections = dict(r.get("sections", {}))
        rows.append(
            (
                int(r["abstract_id"]),
                str(r["poster_id"]),
                str(r.get("title", "")),
                str(r.get("accepted_for", "Unknown")),
                json.dumps(sections, sort_keys=True),
                json.dumps(r.get("topics", {}), sort_keys=True),
                json.dumps(r.get("methods_checklist", [])),
                json.dumps(r.get("facets", {}), sort_keys=True),
                json.dumps(r.get("author_ids", [])),
                json.dumps(r.get("reference_dois", [])),
                json.dumps(r.get("reference_urls", [])),
                json.dumps(r.get("reference_titles", [])),
            )
        )
        fts_rows.append(
            (
                str(r["poster_id"]),
                str(r.get("title", "")),
                str(sections.get("methods", "")),
                str(sections.get("results", "")),
                str(sections.get("conclusion", "")),
            )
        )
    cur.executemany(
        "INSERT INTO abstracts VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        rows,
    )
    cur.executemany(
        "INSERT INTO abstracts_fts (poster_id, title, methods, results, conclusion) "
        "VALUES (?, ?, ?, ?, ?)",
        fts_rows,
    )


def _insert_authors(con: sqlite3.Connection, authors_envelope: Mapping[str, Any]) -> None:
    rows = [
        (
            int(a["author_id"]),
            str(a.get("name", "")),
            json.dumps(a.get("affiliations", [])),
            json.dumps(a.get("abstract_ids", [])),
        )
        for a in authors_envelope["authors"]
    ]
    con.executemany("INSERT INTO authors VALUES (?, ?, ?, ?)", rows)


def _insert_cell(
    con: sqlite3.Connection, cell_key: str, envelope: Mapping[str, Any]
) -> None:
    table = f"cell_{_sql_safe(cell_key)}"
    con.execute(
        f"""
        CREATE TABLE {table} (
            abstract_id INTEGER PRIMARY KEY,
            umap2d TEXT, -- JSON [float, float]
            umap3d TEXT, -- JSON [float, float, float]
            community_id INTEGER,
            topic_cluster_id INTEGER,
            neuroscape_cluster_id INTEGER,
            umap_missing INTEGER
        )
        """
    )
    rows = [
        (
            int(r["abstract_id"]),
            json.dumps(r.get("umap2d")) if r.get("umap2d") is not None else None,
            json.dumps(r.get("umap3d")) if r.get("umap3d") is not None else None,
            r.get("community_id"),
            r.get("topic_cluster_id"),
            r.get("neuroscape_cluster_id"),
            int(bool(r.get("umap_missing", False))),
        )
        for r in envelope["rows"]
    ]
    con.executemany(
        f"INSERT INTO {table} VALUES (?, ?, ?, ?, ?, ?, ?)",
        rows,
    )


def _insert_topics(
    con: sqlite3.Connection,
    triple: tuple[str, str, str],
    envelope: Mapping[str, Any],
) -> None:
    model, inp, kind = triple
    table = f"topic_{_sql_safe(model)}_{_sql_safe(inp)}_{_sql_safe(kind)}"
    con.execute(
        f"""
        CREATE TABLE {table} (
            cluster_id INTEGER PRIMARY KEY,
            title TEXT,
            description TEXT,
            focus TEXT,
            keywords TEXT -- JSON list[str]
        )
        """
    )
    rows = [
        (
            int(r["cluster_id"]),
            r.get("title", ""),
            r.get("description", ""),
            r.get("focus", ""),
            json.dumps(r.get("keywords", [])),
        )
        for r in envelope["topics"]
    ]
    con.executemany(
        f"INSERT INTO {table} VALUES (?, ?, ?, ?, ?)",
        rows,
    )


def _insert_neighbours(
    con: sqlite3.Connection, cell_key: str, envelope: Mapping[str, Any]
) -> None:
    table = f"neighbours_{_sql_safe(cell_key)}"
    con.execute(
        f"""
        CREATE TABLE {table} (
            abstract_id INTEGER PRIMARY KEY,
            nearest_ids TEXT,         -- JSON list[int]
            nearest_distances TEXT,   -- JSON list[float]
            farthest_ids TEXT,        -- JSON list[int]
            farthest_distances TEXT   -- JSON list[float]
        )
        """
    )
    rows = []
    for idx, aid in enumerate(envelope["abstract_ids"]):
        rows.append(
            (
                int(aid),
                json.dumps(envelope["nearest_ids"][idx]),
                json.dumps(envelope["nearest_distances"][idx]),
                json.dumps(envelope["farthest_ids"][idx]),
                json.dumps(envelope["farthest_distances"][idx]),
            )
        )
    con.executemany(
        f"INSERT INTO {table} VALUES (?, ?, ?, ?, ?)",
        rows,
    )


def _insert_enrichment(con: sqlite3.Connection, envelope: Mapping[str, Any]) -> None:
    con.executescript(
        """
        CREATE TABLE enrichment_claims (
            abstract_id INTEGER,
            claim_index INTEGER,
            text TEXT,
            source TEXT,
            evidence TEXT,
            evidence_eco_codes TEXT,
            confidence REAL,
            PRIMARY KEY (abstract_id, claim_index)
        );
        CREATE INDEX enrichment_claims_aid ON enrichment_claims(abstract_id);
        CREATE TABLE enrichment_figures (
            abstract_id INTEGER,
            figure_index INTEGER,
            figure_id TEXT,
            caption_guess TEXT,
            interpretation TEXT,
            ocr_text TEXT,
            keywords TEXT,
            PRIMARY KEY (abstract_id, figure_index)
        );
        CREATE INDEX enrichment_figures_aid ON enrichment_figures(abstract_id);
        """
    )
    claim_rows: list[tuple[Any, ...]] = []
    figure_rows: list[tuple[Any, ...]] = []
    for aid_str, rec in envelope.get("records", {}).items():
        aid = int(aid_str)
        for i, c in enumerate(rec.get("claims", []) or []):
            claim_rows.append(
                (
                    aid,
                    i,
                    c.get("text"),
                    c.get("source"),
                    c.get("evidence"),
                    json.dumps(c.get("evidence_eco_codes", [])),
                    c.get("confidence"),
                )
            )
        for i, f in enumerate(rec.get("figures", []) or []):
            figure_rows.append(
                (
                    aid,
                    i,
                    f.get("figure_id"),
                    f.get("caption_guess"),
                    f.get("interpretation"),
                    f.get("ocr_text"),
                    json.dumps(f.get("keywords", [])),
                )
            )
    if claim_rows:
        con.executemany(
            "INSERT INTO enrichment_claims VALUES (?, ?, ?, ?, ?, ?, ?)",
            claim_rows,
        )
    if figure_rows:
        con.executemany(
            "INSERT INTO enrichment_figures VALUES (?, ?, ?, ?, ?, ?, ?)",
            figure_rows,
        )


def _insert_minilm(
    con: sqlite3.Connection, minilm_bin: bytes | None, sidecar: Mapping[str, Any]
) -> None:
    """Store the int8 vectors as one BLOB column per abstract.

    Splits the flat int8 buffer into per-abstract rows so the browser
    can fetch a single vector via a range-scan ``SELECT vector FROM
    vectors WHERE abstract_id = ?`` without loading the full N×384
    matrix into memory at boot.
    """
    con.executescript(
        """
        CREATE TABLE vectors_meta (
            key TEXT PRIMARY KEY,
            value TEXT
        );
        CREATE TABLE vectors (
            abstract_id INTEGER PRIMARY KEY,
            vector_int8 BLOB
        );
        """
    )
    con.executemany(
        "INSERT INTO vectors_meta VALUES (?, ?)",
        [
            ("shape", json.dumps(sidecar.get("shape", []))),
            ("dtype", sidecar.get("dtype", "int8")),
            ("metadata_json", json.dumps(sidecar, sort_keys=True)),
        ],
    )
    if minilm_bin is None:
        return
    shape = sidecar.get("shape") or [0, 384]
    n_rows, dim = int(shape[0]), int(shape[1])
    row_bytes = dim  # int8 = 1 byte per element
    if len(minilm_bin) != n_rows * row_bytes:
        return
    abstract_ids = sidecar.get("abstract_ids") or list(range(n_rows))
    rows = []
    for i, aid in enumerate(abstract_ids[:n_rows]):
        start = i * row_bytes
        rows.append((int(aid), minilm_bin[start : start + row_bytes]))
    con.executemany("INSERT INTO vectors VALUES (?, ?)", rows)


def _create_cross_conference_table(con: sqlite3.Connection) -> None:
    """Empty table for OHBM-only; populated by a follow-up multi-conf build."""
    con.executescript(
        """
        CREATE TABLE cross_conference_links (
            conf_a TEXT NOT NULL,
            id_a TEXT NOT NULL,
            conf_b TEXT NOT NULL,
            id_b TEXT NOT NULL,
            link_kind TEXT,
            similarity REAL,
            metadata TEXT, -- JSON
            PRIMARY KEY (conf_a, id_a, conf_b, id_b, link_kind)
        );
        CREATE INDEX xconf_a_idx ON cross_conference_links(conf_a, id_a);
        CREATE INDEX xconf_b_idx ON cross_conference_links(conf_b, id_b);
        """
    )


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
    db_path = out / "main.sqlite"
    # Always rebuild from scratch — there's no incremental insert path.
    if db_path.exists():
        db_path.unlink()

    con = sqlite3.connect(str(db_path))
    try:
        con.execute("PRAGMA journal_mode = OFF")
        con.execute("PRAGMA synchronous = OFF")
        con.execute("PRAGMA temp_store = MEMORY")
        con.execute("PRAGMA page_size = 4096")

        _create_meta_table(con)
        con.executemany(
            "INSERT INTO meta VALUES (?, ?)",
            [
                ("schema_version", str(manifest.get("schema_version", ""))),
                ("format", "sqlite-single"),
                ("conference_id", conference_id),
                ("build_info_json", json.dumps(dict(build_info), sort_keys=True)),
                ("manifest_json", json.dumps(manifest, sort_keys=True)),
            ],
        )

        _create_abstracts_table(con)
        _insert_abstracts(con, abstracts_envelope)

        _create_authors_table(con)
        _insert_authors(con, authors_envelope)

        for cell_key, env in cells_envelopes.items():
            _insert_cell(con, cell_key, env)
        for triple, env in topics_envelopes.items():
            _insert_topics(con, triple, env)
        for cell_key, env in neighbors_envelopes.items():
            _insert_neighbours(con, cell_key, env)

        _insert_enrichment(con, enrichment_envelope)
        _insert_minilm(con, minilm_bin, minilm_sidecar)
        _create_cross_conference_table(con)

        con.commit()
        # Compact the file. VACUUM also rewrites the file in a stable
        # page order, which helps the gzipped size + the browser-side
        # range-fetch heuristic.
        con.execute("VACUUM")
        con.commit()
    finally:
        con.close()

    return {db_path}
