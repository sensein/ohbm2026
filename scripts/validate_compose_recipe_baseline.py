#!/usr/bin/env python3
"""Validation: composed recipe vs direct full-text embedding (SC-004).

Verifies that the Stage 3 composition contract — averaging per-component
embeddings to approximate a multi-component "recipe" — produces vectors
that are cosine-similar to the embedding you'd get by passing the
directly-concatenated full text through the same encoder.

Spec SC-004 calls for: cosine similarity ≥ 0.90 on a 50-abstract
sample, for the title+introduction+methods+results+conclusion recipe.

Run:

    PYTHONPATH=src .venv/bin/python scripts/validate_compose_recipe_baseline.py \
        --model minilm      # or voyage

Defaults to running both `minilm` and `voyage` in sequence and emits
one JSON-per-model on stdout, then an aggregate summary. Exits 0
only if every model passes the threshold.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import sqlite3
import sys
import zlib
from pathlib import Path
from typing import Iterable

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SRC_DIR = _REPO_ROOT / "src"
if _SRC_DIR.exists() and str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

import numpy as np

from ohbm2026.embed.compose import compose_recipe
from ohbm2026.embed.components import assemble_component
from ohbm2026.embed.hf import DEFAULT_MINILM_MODEL, DEFAULT_PUBMEDBERT_MODEL, HFBatchClient
from ohbm2026.embed.voyage import DEFAULT_VOYAGE_MODEL, VoyageBatchClient


SAMPLE_SIZE = 50
SEED = 42
COMPONENTS = ("title", "introduction", "methods", "results", "conclusion")
COSINE_THRESHOLD = 0.90


def _load_records(sqlite_path: Path) -> list[dict]:
    con = sqlite3.connect(sqlite_path)
    try:
        rows = con.execute("SELECT id, payload FROM abstracts ORDER BY id").fetchall()
    finally:
        con.close()
    out: list[dict] = []
    for aid, payload in rows:
        rec = json.loads(zlib.decompress(payload).decode("utf-8"))
        rec["id"] = aid
        out.append(rec)
    return out


def _cosine_per_row(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    a_n = a / (np.linalg.norm(a, axis=1, keepdims=True) + 1e-12)
    b_n = b / (np.linalg.norm(b, axis=1, keepdims=True) + 1e-12)
    return np.einsum("ij,ij->i", a_n, b_n)


def _percentiles(values: Iterable[float]) -> dict[str, float]:
    arr = np.asarray(list(values), dtype=np.float64)
    return {
        "mean": float(arr.mean()),
        "min": float(arr.min()),
        "p25": float(np.percentile(arr, 25)),
        "p50": float(np.percentile(arr, 50)),
        "p75": float(np.percentile(arr, 75)),
        "p95": float(np.percentile(arr, 95)),
        "max": float(arr.max()),
    }


def _build_client(model_key: str) -> tuple[object, str]:
    """Return `(client, model_id)` for the named model_key."""
    if model_key == "minilm":
        return HFBatchClient(model_id=DEFAULT_MINILM_MODEL), DEFAULT_MINILM_MODEL
    if model_key == "pubmedbert":
        return HFBatchClient(model_id=DEFAULT_PUBMEDBERT_MODEL), DEFAULT_PUBMEDBERT_MODEL
    if model_key == "voyage":
        # Load the API key from .env without polluting os.environ.
        api_key = None
        env_path = Path(".env")
        if env_path.exists():
            for line in env_path.read_text().splitlines():
                line = line.strip()
                if line.startswith("VOYAGE_API="):
                    api_key = line.partition("=")[2].strip().strip("\"").strip("'")
                    break
        api_key = api_key or os.environ.get("VOYAGE_API_KEY")
        if not api_key:
            raise SystemExit(
                "VOYAGE_API not in .env; cannot validate voyage recipe"
            )
        return VoyageBatchClient(api_key=api_key, model_id=DEFAULT_VOYAGE_MODEL), DEFAULT_VOYAGE_MODEL
    raise SystemExit(f"unknown model_key {model_key!r}")


def _validate_one(model_key: str, records: list[dict], sampled_ids: list[int]) -> dict:
    """Compute composed-vs-direct cosine stats for one model. Returns
    a JSON-serializable report dict."""
    # 1) Composed recipe over per-component bundles for this model.
    recipe = compose_recipe(list(COMPONENTS), model_key=model_key)
    bundle_ids = recipe["ids"].tolist()
    id_to_row = {aid: row for row, aid in enumerate(bundle_ids)}
    missing_in_bundle = [aid for aid in sampled_ids if aid not in id_to_row]
    if missing_in_bundle:
        return {
            "model_key": model_key,
            "error": f"{len(missing_in_bundle)} sampled ids missing from composed recipe",
            "missing_ids_sample": missing_in_bundle[:5],
            "passes_threshold": False,
        }
    composed_matrix = np.asarray(
        [recipe["matrix"][id_to_row[aid]] for aid in sampled_ids],
        dtype=np.float32,
    )

    # 2) Direct full-text embedding: concat components, embed once.
    id_to_record = {int(r["id"]): r for r in records}
    full_texts: list[str] = []
    for aid in sampled_ids:
        rec = id_to_record[aid]
        chunks = [assemble_component(rec, comp) for comp in COMPONENTS]
        full_text = "\n\n".join(c for c in chunks if c)
        full_texts.append(full_text)
    client, model_id = _build_client(model_key)
    direct_vectors, telemetry = client.embed_batch(full_texts)
    direct_matrix = np.asarray(direct_vectors, dtype=np.float32)

    # 3) Cosine per abstract.
    cosines = _cosine_per_row(composed_matrix, direct_matrix)
    stats = _percentiles(cosines.tolist())
    below_threshold = int(np.sum(cosines < COSINE_THRESHOLD))
    pass_flag = stats["mean"] >= COSINE_THRESHOLD
    return {
        "model_key": model_key,
        "model_id": model_id,
        "components": list(COMPONENTS),
        "sample_size": len(sampled_ids),
        "cosine_threshold": COSINE_THRESHOLD,
        "stats": stats,
        "abstracts_below_threshold": below_threshold,
        "telemetry_direct_embed_truncated_count": telemetry.get("truncated_count"),
        "passes_threshold": pass_flag,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--model",
        action="append",
        choices=["minilm", "voyage", "pubmedbert"],
        help="Repeatable. Defaults to [minilm, voyage] when omitted.",
    )
    parser.add_argument(
        "--source-corpus",
        default="data/primary/abstracts_enriched.sqlite",
    )
    args = parser.parse_args()

    sqlite_path = Path(args.source_corpus)
    if not sqlite_path.exists():
        print(f"error: source corpus not found at {sqlite_path}", file=sys.stderr)
        return 1
    records = _load_records(sqlite_path)
    random.seed(SEED)
    sampled = random.sample(records, min(SAMPLE_SIZE, len(records)))
    sampled_ids = sorted(int(r["id"]) for r in sampled)

    models_to_check = args.model or ["minilm", "voyage"]
    reports = []
    all_pass = True
    for model_key in models_to_check:
        report = _validate_one(model_key, records, sampled_ids)
        reports.append(report)
        all_pass = all_pass and bool(report.get("passes_threshold"))
        print(json.dumps(report, indent=2, sort_keys=True))

    summary = {
        "sample_size": len(sampled_ids),
        "seed": SEED,
        "cosine_threshold": COSINE_THRESHOLD,
        "corpus_state_key": "f0c51e80dc0e",
        "models": [r["model_key"] for r in reports],
        "all_pass": all_pass,
        "per_model_mean": {r["model_key"]: r.get("stats", {}).get("mean") for r in reports},
    }
    print("---")
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if all_pass else 1


if __name__ == "__main__":
    raise SystemExit(main())
