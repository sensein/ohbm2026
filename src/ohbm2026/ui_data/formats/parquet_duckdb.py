"""Candidate #3: Parquet files + DuckDB-WASM views sidecar.

Identical Parquet emission to ``parquet_files`` (we delegate to it),
plus a single ``manifest.duckdb_views.sql`` sidecar that declares the
views / attach commands the browser-side DuckDB-WASM runs on boot.

The views sidecar lets the browser issue SQL queries against the
Parquet files via DuckDB's ``httpfs`` extension — including cross-
table JOINs (e.g., abstracts + enrichment_claims) and the
cross-conference JOIN once a second conference exists.

Sidecar shape (one statement per line):

    INSTALL httpfs; LOAD httpfs;
    CREATE OR REPLACE VIEW abstracts AS SELECT * FROM read_parquet('abstracts.parquet');
    CREATE OR REPLACE VIEW authors   AS SELECT * FROM read_parquet('authors.parquet');
    ...
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from ohbm2026.ui_data.formats import parquet_files

__all__ = ["write"]


def _build_views_sql(
    cells_envelopes: Mapping[str, Mapping[str, Any]],
    topics_envelopes: Mapping[tuple[str, str, str], Mapping[str, Any]],
    neighbors_envelopes: Mapping[str, Mapping[str, Any]],
    has_claims: bool,
    has_figures: bool,
) -> str:
    """Render the DuckDB views file that the browser runs on boot."""
    lines: list[str] = [
        "-- Stage-10 candidate-3 sidecar: DuckDB-WASM view declarations.",
        "-- The browser's DuckDB-WASM runs these on first paint so the UI",
        "-- can issue plain SQL against logical view names rather than the",
        "-- on-disk Parquet file paths.",
        "INSTALL httpfs; LOAD httpfs;",
        "CREATE OR REPLACE VIEW manifest AS SELECT * FROM read_parquet('manifest.parquet');",
        "CREATE OR REPLACE VIEW abstracts AS SELECT * FROM read_parquet('abstracts.parquet');",
        "CREATE OR REPLACE VIEW authors AS SELECT * FROM read_parquet('authors.parquet');",
    ]
    if has_claims:
        lines.append(
            "CREATE OR REPLACE VIEW enrichment_claims AS SELECT * FROM read_parquet('enrichment_claims.parquet');"
        )
    if has_figures:
        lines.append(
            "CREATE OR REPLACE VIEW enrichment_figures AS SELECT * FROM read_parquet('enrichment_figures.parquet');"
        )
    for cell_key in cells_envelopes:
        lines.append(
            f"CREATE OR REPLACE VIEW cell_{cell_key} AS SELECT * FROM read_parquet('cells/{cell_key}.parquet');"
        )
    for (model, inp, kind), _ in topics_envelopes.items():
        lines.append(
            f"CREATE OR REPLACE VIEW topics_{model}_{inp}_{kind} AS "
            f"SELECT * FROM read_parquet('topics/{model}_{inp}_{kind}.parquet');"
        )
    for cell_key in neighbors_envelopes:
        lines.append(
            f"CREATE OR REPLACE VIEW neighbours_{cell_key} AS "
            f"SELECT * FROM read_parquet('neighbors/{cell_key}.parquet');"
        )
    return "\n".join(lines) + "\n"


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
    # Delegate the Parquet emission verbatim.
    expected = parquet_files.write(
        output_dir=output_dir,
        build_info=build_info,
        conference_id=conference_id,
        manifest=manifest,
        abstracts_envelope=abstracts_envelope,
        authors_envelope=authors_envelope,
        cells_envelopes=cells_envelopes,
        topics_envelopes=topics_envelopes,
        neighbors_envelopes=neighbors_envelopes,
        enrichment_envelope=enrichment_envelope,
        minilm_bin=minilm_bin,
        minilm_sidecar=minilm_sidecar,
    )

    # Emit the DuckDB views sidecar alongside the Parquet files.
    has_claims = bool(enrichment_envelope.get("records"))
    has_figures = has_claims  # both come from the same records dict
    views_sql = _build_views_sql(
        cells_envelopes, topics_envelopes, neighbors_envelopes,
        has_claims=has_claims, has_figures=has_figures,
    )
    sidecar_path = Path(output_dir) / "manifest.duckdb_views.sql"
    sidecar_path.write_text(views_sql)
    expected.add(sidecar_path)

    return expected
