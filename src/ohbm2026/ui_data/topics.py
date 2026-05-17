"""Build ``data/topics/<model>_<input>_<kind>.json`` for Stage 6 (T017).

Reads the Stage 4 rollup's ``cluster_topics`` table and emits one envelope per
``(model_key, input_source, clustering_method)`` triple.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from ohbm2026.ui_data.state_key import Stage6BuildError

SCHEMA_VERSION = "topics.v1"


def _split_keywords(blob: str | None) -> list[str]:
    if not blob:
        return []
    raw = str(blob).strip()
    if not raw:
        return []
    # cluster_topics stores keywords as JSON, comma-, or pipe-separated strings
    # depending on the upstream writer. Be permissive on the read side.
    if raw.startswith("[") and raw.endswith("]"):
        try:
            decoded = json.loads(raw)
        except json.JSONDecodeError:
            decoded = None
        if isinstance(decoded, list):
            return [str(item).strip() for item in decoded if str(item).strip()]
    for sep in ("|", ","):
        if sep in raw:
            return [piece.strip() for piece in raw.split(sep) if piece.strip()]
    return [raw]


def build_topics_shards(
    *,
    rollup_db: Path,
) -> dict[tuple[str, str, str], list[dict[str, Any]]]:
    """Return ``{(model, input, kind): [topic_record, ...]}`` for every triple."""

    rollup_path = Path(rollup_db)
    if not rollup_path.exists():
        raise Stage6BuildError(f"Stage 4 rollup not found: {rollup_path}")
    out: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    with sqlite3.connect(str(rollup_path)) as conn:
        conn.row_factory = sqlite3.Row
        for row in conn.execute(
            """
            SELECT clustering_method, model_key, input_source, cluster_id,
                   topic_keywords, topic_title, topic_description, topic_focus
              FROM cluster_topics
             ORDER BY clustering_method, model_key, input_source, cluster_id
            """
        ):
            triple = (row["model_key"], row["input_source"], row["clustering_method"])
            out.setdefault(triple, []).append(
                {
                    "cluster_id": int(row["cluster_id"]),
                    "keywords": _split_keywords(row["topic_keywords"]),
                    "title": row["topic_title"] or "",
                    "description": row["topic_description"] or "",
                    "focus": row["topic_focus"] or "",
                }
            )
    return out


def build_topics(
    *,
    rollup_db: Path,
    build_info: Mapping[str, str],
) -> dict[tuple[str, str, str], dict[str, Any]]:
    """Return ``{(model, input, kind): envelope}`` per data-model.md §5."""

    shards = build_topics_shards(rollup_db=rollup_db)
    return {
        triple: {
            "schema_version": SCHEMA_VERSION,
            "build_info": dict(build_info),
            "cell_key": f"{triple[0]}_{triple[1]}",
            "kind": triple[2],
            "topics": rows,
        }
        for triple, rows in shards.items()
    }
