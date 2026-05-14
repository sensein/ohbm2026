"""Stage 3 composition surface.

Multi-component recipes are computed at consumption time by averaging
the relevant per-component vectors per abstract — `compose_recipe`
returns a legacy-stage-1-shaped dict so existing consumers
(cluster_benchmark, umap, projection_comparison, ui export) can swap
from `load_stage1_bundle(path)` to `compose_recipe([...], model_key=...)`
with a single-line change.

Lives here (not in `neuroscape.py`) so the Stage 3 surface stays
self-contained: every Stage 3 caller imports from `ohbm2026.embed_*`.
The NeuroScape Stage-2 application helper is also Stage-3 logic
(operates on Voyage matrices to produce NeuroScape-projected
matrices) and lives here for the same reason.

The `neuroscape.py` module re-exports both names as a thin
backward-compat shim so callers that still import from there keep
working.
"""

from __future__ import annotations

import hashlib as _hashlib
import json
from pathlib import Path
from typing import Any

from ohbm2026.exceptions import EmbeddingError

__all__ = [
    "compose_recipe",
    "apply_published_stage2_to_matrix",
]


def compose_recipe(
    components: list[str],
    *,
    model_key: str,
    bundles_root: Path | None = None,
    partial: bool = False,
    corpus_state_key: str | None = None,
) -> dict[str, Any]:
    """Compose a multi-component recipe by averaging per-component bundles.

    Returns a dict matching the legacy stage-1 bundle shape so that
    existing consumers can switch from `load_stage1_bundle(path)` to
    `compose_recipe([...], model_key=...)` with minimal code change:

        {
            "ids": numpy.ndarray[int64, shape=(n_union,)],
            "matrix": numpy.ndarray[float32, shape=(n_union, dim)],
            "metadata": {
                "model_key": str,
                "components": list[str],
                "dim": int,
                "n_union": int,
                "present_count_per_id": numpy.ndarray[int8, shape=(n_union,)],
                "missing_per_id": dict[int, list[str]],
                "source_bundles": list[str],   # bundle paths
            },
        }

    Path resolution order per component:
    1. State-key keyed: `<root>/<model>/<component>__<state_key>/`
       (when `corpus_state_key` is given; otherwise pick the
       lexically-latest match).
    2. Bare per-model layout: `<root>/<model>/<component>/`.
    3. Legacy flat layout: `<root>/<model_key>_<component>/`.

    Raises FileNotFoundError if any of the requested per-component
    bundles is missing on disk. Raises EmbeddingError if the bundles
    have inconsistent dimensions.
    """
    import numpy as np

    if bundles_root is None:
        bundles_root = Path("data/outputs/embeddings")
    suffix = "_partial" if partial else ""
    source_bundles: list[Path] = []

    def _resolve(component: str) -> Path:
        model_dir = Path(bundles_root) / model_key
        if corpus_state_key is not None:
            candidate = model_dir / f"{component}{suffix}__{corpus_state_key}"
            if candidate.exists():
                return candidate
        if model_dir.exists():
            keyed = sorted(model_dir.glob(f"{component}{suffix}__*"))
            if keyed:
                return keyed[-1]
        bare = model_dir / f"{component}{suffix}"
        if bare.exists():
            return bare
        legacy = Path(bundles_root) / f"{model_key}_{component}{suffix}"
        if legacy.exists():
            return legacy
        return bare  # caller raises FileNotFoundError below

    loaded: list[tuple[str, list[int], "np.ndarray"]] = []
    for component in components:
        bundle_dir = _resolve(component)
        if not bundle_dir.exists():
            raise FileNotFoundError(
                f"compose_recipe: component bundle missing for "
                f"{model_key}/{component} under {bundles_root} "
                f"(corpus_state_key={corpus_state_key!r})"
            )
        ids_path = bundle_dir / "ids.npy"
        vectors_path = bundle_dir / "vectors.npy"
        if ids_path.exists() and vectors_path.exists():
            ids = np.load(ids_path, allow_pickle=False).tolist()
            vectors = np.load(vectors_path, allow_pickle=False).astype(np.float32, copy=False)
        else:
            meta_path = bundle_dir / "metadata.json"
            if not meta_path.exists() or not vectors_path.exists():
                raise FileNotFoundError(
                    f"compose_recipe: bundle missing required files at {bundle_dir}"
                )
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            ids = list(meta.get("ids") or [])
            vectors = np.load(vectors_path, allow_pickle=False).astype(np.float32, copy=False)
        if vectors.ndim != 2 or vectors.shape[0] != len(ids):
            raise EmbeddingError(
                f"compose_recipe: bundle shape mismatch at {bundle_dir} — "
                f"ids={len(ids)} vectors={vectors.shape}"
            )
        loaded.append((component, ids, vectors))
        source_bundles.append(bundle_dir)

    union_ids: list[int] = sorted({aid for _, ids, _ in loaded for aid in ids})
    dims = {v.shape[1] for _, _, v in loaded}
    if len(dims) != 1:
        raise EmbeddingError(
            f"compose_recipe: component bundles have inconsistent dim: {sorted(dims)}"
        )
    dim = dims.pop()
    n = len(union_ids)
    id_to_row = {aid: row for row, aid in enumerate(union_ids)}

    accum = np.zeros((n, dim), dtype=np.float64)
    counts = np.zeros((n,), dtype=np.int32)
    missing_per_id: dict[int, list[str]] = {aid: [] for aid in union_ids}

    for component, ids, vectors in loaded:
        present_ids = set(ids)
        for aid, vec in zip(ids, vectors):
            row = id_to_row[aid]
            accum[row] += vec
            counts[row] += 1
        for aid in union_ids:
            if aid not in present_ids:
                missing_per_id[aid].append(component)

    if (counts == 0).any():
        zero_rows = np.where(counts == 0)[0]
        raise EmbeddingError(
            f"compose_recipe: {len(zero_rows)} abstract(s) had zero component "
            f"contributions — this should be impossible given union semantics"
        )

    matrix = (accum / counts[:, None]).astype(np.float32, copy=False)
    return {
        "ids": np.asarray(union_ids, dtype=np.int64),
        "matrix": matrix,
        "metadata": {
            "model_key": model_key,
            "components": list(components),
            "dim": int(dim),
            "n_union": int(n),
            "present_count_per_id": counts.astype(np.int8, copy=False),
            "missing_per_id": missing_per_id,
            "source_bundles": [str(b) for b in source_bundles],
        },
    }


def apply_published_stage2_to_matrix(
    voyage_matrix: Any,
    *,
    model_path: Path,
    device: str | None = None,
    batch_size: int = 256,
    dropout: float = 0.05,
) -> tuple[Any, str]:
    """Apply the published NeuroScape Stage 2 model to a raw Voyage
    matrix and return `(projected_matrix, model_version)`.

    Thin Stage-3 façade over `ns_stage2.load_pretrained_stage2_model`
    and `ns_stage2.apply_stage2_model`. Lives here so the Stage 3
    embed_stage orchestrator and any downstream NeuroScape lens
    consumer can import from a single Stage 3 entry point.

    Raises EmbeddingError when the input matrix dim doesn't match the
    NeuroScape Stage-2 input dimension, or when the model file is
    absent.
    """
    import numpy as np
    # Lazy import to avoid pulling in torch on import time of this module.
    from ohbm2026.embed import neuroscape as ns_stage2

    if voyage_matrix.shape[1] != 1024:
        raise EmbeddingError(
            f"published NeuroScape stage-2 expects 1024-dim input; "
            f"got {voyage_matrix.shape[1]}"
        )
    if not Path(model_path).exists():
        raise EmbeddingError(
            f"published NeuroScape stage-2 model not found at {model_path}"
        )
    model, torch_device = ns_stage2.load_pretrained_stage2_model(
        Path(model_path),
        input_dimension=int(voyage_matrix.shape[1]),
        hidden_dimensions=ns_stage2.PUBLISHED_STAGE2_HIDDEN_DIMENSIONS,
        output_dimension=ns_stage2.PUBLISHED_STAGE2_OUTPUT_DIMENSION,
        dropout=dropout,
        device=device,
    )
    projected = ns_stage2.apply_stage2_model(
        model,
        np.asarray(voyage_matrix, dtype=np.float32),
        batch_size=batch_size,
        device=torch_device,
    )
    h = _hashlib.sha256(Path(model_path).read_bytes()).hexdigest()[:12]
    return projected, f"neuroscape-stage2-published@{h}"
