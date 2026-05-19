"""Build ``data/enrichment.json`` — Stage 2.1 claims + figure interpretations.

These are the AI-authored surfaces that the detail panel shows behind
expandable headers (per FR-023). The shard is keyed by ``abstract_id`` so the
UI can look up each focused abstract's enrichment in O(1). Fields are trimmed
to the user-visible subset to keep the wire size modest:

* claims → ``{claim, claim_type, evidence, evidence_eco_codes, source,
              source_quote_verified}``
* figures → ``{interpretation, keywords, ocr_text, question_name,
               model_quality_estimate}``

The ``model_id`` is identical across every record so it's lifted to the shard
envelope instead of being repeated thousands of times.
"""

from __future__ import annotations

import json
import sqlite3
import zlib
from collections.abc import Iterable, Iterator, Mapping
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "enrichment.v1"


_CLAIM_FIELDS = (
    "claim",
    "claim_type",
    "evidence",
    "evidence_eco_codes",
    "source",
    "source_quote_verified",
)

_FIGURE_FIELDS = (
    "interpretation",
    "keywords",
    "ocr_text",
    "question_name",
    "model_quality_estimate",
)


def _trim_claim(claim: Mapping[str, Any]) -> dict[str, Any]:
    return {k: claim.get(k) for k in _CLAIM_FIELDS if k in claim}


def _trim_figure(fig: Mapping[str, Any]) -> dict[str, Any]:
    return {k: fig.get(k) for k in _FIGURE_FIELDS if k in fig}


def _iter_enriched_rows(sqlite_path: Path) -> Iterable[tuple[int, dict[str, Any]]]:
    con = sqlite3.connect(sqlite_path)
    try:
        for row_id, payload in con.execute("SELECT id, payload FROM abstracts"):
            yield int(row_id), json.loads(zlib.decompress(payload))
    finally:
        con.close()


def iter_enrichment(
    *,
    enriched_path: Path | None,
    abstract_ids: Iterable[int],
    abstract_to_poster: Mapping[int, int],
) -> Iterator[tuple[dict[str, Any], dict[str, set[str]]]]:
    """Yield per-abstract enrichment rows AND the accumulating model_ids set.

    Each yielded tuple is
    ``({poster_id, claims, figures}, {"claims": {…model_ids}, "figures": {…}})``.

    The model_ids set is shared mutable state across yields — it builds up
    as records are consumed. After the iterator exhausts, the caller has
    the full ``ai_provenance`` set.

    Records with no claims AND no figures are skipped (Stage-6 semantics:
    the UI treats a missing key as 'no enrichment available').

    Stage 10: rows carry the user-facing ``poster_id`` (int) — the
    enriched SQLite is indexed by Oxford submission id internally, and
    we translate via *abstract_to_poster* at emit time.
    """
    keep_ids = set(abstract_ids)
    model_ids: dict[str, set[str]] = {"claims": set(), "figures": set()}
    if enriched_path is None or not Path(enriched_path).exists():
        return
    for abstract_id, payload in _iter_enriched_rows(Path(enriched_path)):
        if abstract_id not in keep_ids:
            continue
        poster_id = abstract_to_poster.get(int(abstract_id))
        if poster_id is None:
            # Dedup drop or missing poster_id — record is not in the
            # exported corpus.
            continue
        claims_raw = payload.get("claims") or []
        figures_raw = payload.get("figure_interpretation") or []
        if not claims_raw and not figures_raw:
            continue
        claims = [_trim_claim(c) for c in claims_raw if isinstance(c, dict)]
        figures = [_trim_figure(f) for f in figures_raw if isinstance(f, dict)]
        for c in claims_raw:
            if isinstance(c, dict) and c.get("model_id"):
                model_ids["claims"].add(c["model_id"])
        for f in figures_raw:
            if isinstance(f, dict) and f.get("model_id"):
                model_ids["figures"].add(f["model_id"])
        yield (
            {"poster_id": int(poster_id), "claims": claims, "figures": figures},
            model_ids,
        )


def build_enrichment(
    *,
    enriched_path: Path | None,
    abstract_ids: Iterable[int],
    abstract_to_poster: Mapping[int, int],
    build_info: Mapping[str, str],
) -> dict[str, Any]:
    """Return the enrichment shard envelope keyed by ``str(poster_id)``.

    Records with no claims AND no figures are omitted from the records dict
    entirely (the UI treats a missing key as "no enrichment available").
    """
    records: dict[str, dict[str, Any]] = {}
    model_ids_final: dict[str, set[str]] = {"claims": set(), "figures": set()}
    for row, accumulated in iter_enrichment(
        enriched_path=enriched_path,
        abstract_ids=abstract_ids,
        abstract_to_poster=abstract_to_poster,
    ):
        records[str(row["poster_id"])] = {
            "claims": row["claims"],
            "figures": row["figures"],
        }
        model_ids_final = accumulated  # last value carries the full set
    return {
        "schema_version": SCHEMA_VERSION,
        "build_info": dict(build_info),
        # When the corpus has multiple model ids (e.g. mid-cycle rebuild), join
        # them with "+" so the AI-attribution pill can still cite a string. The
        # set is usually a singleton.
        "ai_provenance": {
            "claims_model_id": "+".join(sorted(model_ids_final["claims"])) or None,
            "figures_model_id": "+".join(sorted(model_ids_final["figures"])) or None,
        },
        "records": records,
    }
