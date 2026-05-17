"""Quantize MiniLM-L6 embeddings to int8 for the in-browser semantic search.

The browser-side worker (`site/src/lib/workers/semantic.worker.ts`) loads
`Xenova/all-MiniLM-L6-v2` via transformers.js to embed the query text in
the browser, then ranks the corpus by cosine similarity against this
pre-computed int8 vector buffer.

We compose the per-component bundles (introduction, methods, results,
conclusion) into a single per-abstract vector by mean-pooling and
L2-renormalizing — `title` is too narrow on its own; the four sections
together give a representative summary. Each vector is then int8-quantized
with a SINGLE global scale (max-abs → 127). Cosine-similarity ordering is
preserved by the int8 quantization regardless of scale.

Output: a raw little-endian Int8 buffer of shape `[N, 384]` row-major,
plus a sidecar JSON with the build_info + scale + abstract_ids order so
the browser can dequantize + positionally-join with `abstracts.json`.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any


COMPONENT_NAMES: tuple[str, ...] = ("introduction", "methods", "results", "conclusion")
DIMENSION = 384


def _load_component(component_root: Path) -> tuple["object", "object"]:
    """Return ``(ids, vectors)`` for a MiniLM component bundle.

    Lazy-imports numpy so `vectors.py` is import-safe without the [ui] extra.
    """

    import numpy as np  # noqa: I001

    ids = np.load(component_root / "ids.npy")
    vectors = np.load(component_root / "vectors.npy").astype(np.float32)
    if vectors.shape[1] != DIMENSION:
        raise RuntimeError(
            f"{component_root}: expected {DIMENSION}-dim vectors, got {vectors.shape[1]}"
        )
    return ids, vectors


def build_minilm_vectors(
    *,
    embeddings_root: Path,
    abstract_ids: Iterable[int],
    build_info: Mapping[str, str],
    components: tuple[str, ...] = COMPONENT_NAMES,
) -> tuple[bytes, dict[str, Any]]:
    """Return ``(int8_buffer, sidecar_dict)`` for the canonical per-abstract semantic vector.

    *abstract_ids* is the ordering required by ``abstracts.json`` — the output
    buffer is positionally joined to that ordering so the browser can index
    row *i* directly. Abstracts whose embedding is missing get a zero vector
    (which yields cosine 0 — they're never top-K matches).
    """

    import numpy as np  # noqa: I001

    ordered_ids = list(abstract_ids)

    # Find one component dir per name (most recent state-key suffix).
    component_dirs: list[Path] = []
    for name in components:
        candidates = sorted(Path(embeddings_root).glob(f"{name}__*"))
        if not candidates:
            raise FileNotFoundError(
                f"No MiniLM bundle for component {name!r} under {embeddings_root}"
            )
        component_dirs.append(candidates[-1])

    # Load each component → build a (abstract_id → vector) map, then mean.
    per_abstract: dict[int, list[np.ndarray]] = {}
    used_state_keys: list[str] = []
    for comp_dir in component_dirs:
        ids, vectors = _load_component(comp_dir)
        used_state_keys.append(comp_dir.name.split("__", 1)[1])
        for i, aid in enumerate(ids):
            per_abstract.setdefault(int(aid), []).append(vectors[i])

    # Compose per-abstract vector = mean of components (re-normalized).
    composed = np.zeros((len(ordered_ids), DIMENSION), dtype=np.float32)
    missing: list[int] = []
    for row, aid in enumerate(ordered_ids):
        parts = per_abstract.get(int(aid))
        if not parts:
            missing.append(int(aid))
            continue
        mean = np.mean(np.stack(parts, axis=0), axis=0)
        norm = np.linalg.norm(mean)
        if norm > 0:
            mean = mean / norm
        composed[row] = mean

    # Pick global scale: max abs across the matrix → 127.
    max_abs = float(np.max(np.abs(composed))) if composed.size else 1.0
    if max_abs == 0:
        max_abs = 1.0
    scale_to_int = 127.0 / max_abs
    quant = np.clip(np.round(composed * scale_to_int), -127, 127).astype(np.int8)

    # Cosine-recovery probe on a held-out subset (data-model.md §7).
    rng = np.random.default_rng(seed=0)
    n_check = min(100, composed.shape[0])
    sample_idx = rng.choice(composed.shape[0], size=n_check, replace=False) if n_check else np.array([], dtype=int)
    recovery_error = 0.0
    if n_check >= 2:
        f32 = composed[sample_idx]
        i8_as_f32 = quant[sample_idx].astype(np.float32) / scale_to_int
        # Normalize both
        for matrix in (f32, i8_as_f32):
            norms = np.linalg.norm(matrix, axis=1, keepdims=True)
            norms[norms == 0] = 1
            matrix /= norms
        cos_f32 = f32 @ f32.T
        cos_i8 = i8_as_f32 @ i8_as_f32.T
        recovery_error = float(np.mean(np.abs(cos_f32 - cos_i8)))

    sidecar = {
        "schema_version": "minilm_vectors.v1",
        "build_info": dict(build_info),
        "shape": [composed.shape[0], DIMENSION],
        "dtype": "int8",
        "scale": scale_to_int,
        "max_abs_original": max_abs,
        "components": list(components),
        "component_state_keys": used_state_keys,
        "missing_abstract_ids": missing,
        "cosine_recovery_mae": recovery_error,
        "byte_offset_url": "data/search/minilm_vectors.bin",
    }
    return quant.tobytes(), sidecar
