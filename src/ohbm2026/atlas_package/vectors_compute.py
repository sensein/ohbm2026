"""Stage 19 — corpus-side MiniLM embedding compute + per-cluster cache.

Spec: ``specs/019-neuroscape-semantic-search/research.md#R-002`` +
``#R-009`` (build-step caching).

Loads the corpus-side MiniLM model (``sentence-transformers/all-MiniLM-L6-v2``)
via the shared ``embed/hf.py`` chunk-mean-pool client (token window 512,
overlap 64 — the same long-input handling the ``/ohbm2026/`` corpus vectors
use), runs inference over ``title + abstract`` batch-by-batch,
quantises with the single-global-scale scheme that matches
``src/ohbm2026/ui_data/vectors.py`` (so the browser dequantisation path
in ``site/src/lib/workers/semantic.worker.ts`` works unchanged), and
persists per-cluster intermediates under
``<cache_root>/<state_key>/cluster_<id>.npy`` so a rebuild with
unchanged inputs short-circuits.

Matched-pair note (R-010): the browser worker
(``site/src/lib/workers/semantic.worker.ts``) embeds queries with
``Xenova/all-MiniLM-L6-v2`` — Xenova's ONNX export of this same
``sentence-transformers/all-MiniLM-L6-v2`` checkpoint. The Xenova repo
ships ONLY ONNX weights, so it is not loadable by sentence-transformers;
we load its PyTorch origin here instead. This is exactly the matched
pair the existing ``/ohbm2026/`` semantic search already relies on
(corpus vectors from PyTorch ``all-MiniLM-L6-v2`` via ``embed-matrix``,
in-browser query from the Xenova ONNX export). This module records the
corpus-side model id + file sha256 in the vectors-parquet manifest for
provenance.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping, Sequence

import numpy as np

from ohbm2026.exceptions import EmbeddingComputeError

__all__ = [
    "compute_state_key",
    "compute_cluster_vectors",
    "load_model_sha256",
    "VECTORS_CACHE_STATE_KEY_LEN",
    "DEFAULT_MODEL_ID",
    "VECTOR_DIM",
    "ClusterVectors",
    "VectorsComputeResult",
]

# Corpus-side encoder. Xenova/all-MiniLM-L6-v2 (the browser's
# Transformers.js model) is an ONNX-only export with no PyTorch /
# safetensors weights, so sentence-transformers cannot load it; we load
# its PyTorch origin, which produces the same embedding space.
DEFAULT_MODEL_ID = "sentence-transformers/all-MiniLM-L6-v2"
VECTOR_DIM = 384
VECTORS_CACHE_STATE_KEY_LEN = 12


@dataclass(frozen=True)
class ClusterVectors:
    """One cluster's worth of quantised vectors + their pubmed_ids."""

    cluster_id: int
    pubmed_ids: np.ndarray  # (n,) int64
    vectors_int8: np.ndarray  # (n, 384) int8


@dataclass(frozen=True)
class VectorsComputeResult:
    """Full corpus output of :func:`compute_cluster_vectors`."""

    clusters: list[ClusterVectors]
    scale: float  # 127.0 / max_abs_original
    max_abs_original: float
    model_sha256: str
    cache_hits: int
    cache_misses: int


def compute_state_key(
    article_set_hash: str,
    model_id: str,
    quantization_scheme: str = "int8-global-scale",
    text_recipe: str = "title",
) -> str:
    """Return
    ``sha256(article_set_hash || model_id || quantization || text_recipe)[:12]``.

    The article_set_hash is the upstream NeuroScape ingest's
    article-set state-key (already present on neuroscape.parquet's
    manifest as ``state_key``).

    ``text_recipe`` names the field composition fed to the encoder
    (e.g. ``"title"`` vs ``"title+abstract"``). It is folded into the
    hash so switching the composition invalidates any cache built under
    the previous recipe — otherwise a title-only cache would be silently
    reused for a title+abstract build.
    """
    h = hashlib.sha256()
    h.update(article_set_hash.encode("utf-8"))
    h.update(b"|")
    h.update(model_id.encode("utf-8"))
    h.update(b"|")
    h.update(quantization_scheme.encode("utf-8"))
    h.update(b"|")
    h.update(text_recipe.encode("utf-8"))
    return h.hexdigest()[:VECTORS_CACHE_STATE_KEY_LEN]


def load_model_sha256(model_id: str = DEFAULT_MODEL_ID) -> str:
    """Hash the local sentence-transformers model file(s) so the manifest
    can pin them. The browser worker's init handshake cross-checks the
    same hash against its locally-loaded model bytes (R-010).

    The sha256 is computed over the model's ``pytorch_model.bin`` (or
    ``model.safetensors`` if no .bin) so the same model on disk produces
    the same hash regardless of the sentence-transformers wrapper
    version. If neither file exists yet (first-run download in progress),
    raises ``EmbeddingComputeError(reason='model_file_missing')``.
    """
    try:
        from huggingface_hub import snapshot_download  # type: ignore
    except ImportError as exc:
        raise EmbeddingComputeError(
            f"huggingface_hub is required for model_sha256 computation: {exc}",
            reason="huggingface_hub_missing",
        ) from exc

    try:
        local_dir = Path(snapshot_download(repo_id=model_id))
    except Exception as exc:
        raise EmbeddingComputeError(
            f"could not snapshot_download model {model_id!r}: {exc}",
            reason="model_download_failed",
        ) from exc

    # Prefer safetensors over pytorch_model.bin when both exist.
    candidates = [
        local_dir / "model.safetensors",
        local_dir / "pytorch_model.bin",
        local_dir / "onnx" / "model.onnx",
    ]
    for path in candidates:
        if path.exists():
            h = hashlib.sha256()
            with path.open("rb") as f:
                for chunk in iter(lambda: f.read(1 << 20), b""):
                    h.update(chunk)
            return h.hexdigest()
    raise EmbeddingComputeError(
        f"no recognisable model weight file in {local_dir!s}; expected one of "
        f"{', '.join(p.name for p in candidates)}",
        reason="model_file_missing",
    )


def _quantise_int8(vectors: np.ndarray) -> tuple[np.ndarray, float, float]:
    """Single-global-scale INT8 quantisation, identical scheme to
    ``src/ohbm2026/ui_data/vectors.py:107-110``.

    Returns (int8_vectors, scale, max_abs_original) where
    ``scale = 127.0 / max_abs_original`` is the dequantisation
    multiplier the browser worker applies inline.
    """
    if vectors.size == 0:
        return np.empty((0, vectors.shape[1] if vectors.ndim == 2 else VECTOR_DIM), dtype=np.int8), 1.0, 0.0
    max_abs = float(np.max(np.abs(vectors)))
    if max_abs == 0.0:
        # All-zero corpus (defensive). Scale=1 prevents div-by-zero in the
        # browser dequantisation path.
        return np.zeros_like(vectors, dtype=np.int8), 1.0, 0.0
    scale_to_int = 127.0 / max_abs
    quant = np.clip(np.round(vectors * scale_to_int), -127, 127).astype(np.int8)
    return quant, scale_to_int, max_abs


def _l2_renormalise(vectors: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    norms = np.where(norms == 0.0, 1.0, norms)
    return (vectors / norms).astype(np.float32)


def compute_cluster_vectors(
    *,
    article_texts: Sequence[str],
    pubmed_ids: Sequence[int],
    cluster_ids: Sequence[int],
    state_key: str,
    cache_root: Path,
    model_id: str = DEFAULT_MODEL_ID,
    batch_size: int = 64,
    encoder=None,
) -> VectorsComputeResult:
    """Compute INT8 cluster-grouped MiniLM vectors with per-cluster cache.

    ``article_texts`` is the per-article string fed to the encoder. The
    orchestrator composes it as ``title + "\\n\\n" + abstract`` so the
    corpus vectors carry the same field set the ``/ohbm2026/`` vectors
    use; the long-input handling (token window 512, overlap 64,
    mean-pool across chunks) reuses ``embed/hf.py`` so a multi-hundred-
    token abstract is never silently truncated.

    Cache layout: ``<cache_root>/<state_key>/cluster_<id>.npz`` carries
    ``{pubmed_ids: int64[N], vectors_int8: int8[N, 384]}`` per cluster
    plus ``<cache_root>/<state_key>/scale.json`` for the global scale +
    max_abs_original (so a partial-rebuild after a corpus delta produces
    a coherent global scale).

    When ``encoder`` is None the production chunk-mean-pool pathway runs
    (``HFBatchClient`` over the PyTorch ``all-MiniLM-L6-v2`` origin of the
    browser's Xenova ONNX model). Tests inject a callable
    ``encoder(texts: list[str]) -> np.ndarray[N, 384]`` to skip the heavy
    download.
    """
    if len(article_texts) != len(pubmed_ids) or len(article_texts) != len(cluster_ids):
        raise EmbeddingComputeError(
            f"input length mismatch: texts={len(article_texts)} "
            f"pubmed_ids={len(pubmed_ids)} cluster_ids={len(cluster_ids)}",
            reason="input_length_mismatch",
            n_titles=len(article_texts),
        )
    state_dir = Path(cache_root) / state_key
    state_dir.mkdir(parents=True, exist_ok=True)
    scale_path = state_dir / "scale.json"

    # Resolve cache state.
    cluster_to_indices: dict[int, list[int]] = {}
    for i, cid in enumerate(cluster_ids):
        cluster_to_indices.setdefault(int(cid), []).append(i)

    cache_hits = 0
    cache_misses = 0
    needs_recompute: list[int] = []
    cached: dict[int, ClusterVectors] = {}
    for cid in cluster_to_indices:
        cache_path = state_dir / f"cluster_{cid}.npz"
        if cache_path.exists():
            try:
                with np.load(cache_path, allow_pickle=False) as data:
                    cv = ClusterVectors(
                        cluster_id=cid,
                        pubmed_ids=data["pubmed_ids"].astype(np.int64, copy=False),
                        vectors_int8=data["vectors_int8"].astype(np.int8, copy=False),
                    )
                cached[cid] = cv
                cache_hits += 1
                continue
            except Exception:
                # Corrupt cache entry — treat as miss; do not silently use.
                pass
        needs_recompute.append(cid)
        cache_misses += 1

    if not needs_recompute and scale_path.exists():
        # Full cache hit — short-circuit; rebuild the result from cached entries.
        scale_meta = json.loads(scale_path.read_text())
        return VectorsComputeResult(
            clusters=sorted(cached.values(), key=lambda c: c.cluster_id),
            scale=float(scale_meta["scale"]),
            max_abs_original=float(scale_meta["max_abs_original"]),
            model_sha256=str(scale_meta["model_sha256"]),
            cache_hits=cache_hits,
            cache_misses=0,
        )

    # Run the encoder on the missing clusters (or the whole corpus if any
    # cluster needs recompute and we don't have a stable scale.json yet).
    if encoder is None:
        try:
            from ohbm2026.embed.hf import HFBatchClient
        except ImportError as exc:
            raise EmbeddingComputeError(
                f"sentence-transformers / embed.hf not importable: {exc}",
                reason="sentence_transformers_missing",
                n_titles=len(article_texts),
            ) from exc
        try:
            client = HFBatchClient(model_id=model_id, batch_size=batch_size)
        except Exception as exc:
            raise EmbeddingComputeError(
                f"could not construct HFBatchClient for {model_id!r}: {exc}",
                reason="model_load_failed",
                n_titles=len(article_texts),
            ) from exc

        def _default_encoder(texts: list[str]) -> np.ndarray:
            # Mini-batch the chunk-mean-pool client so the flat list of
            # token chunks for a 461K-row corpus never materialises at
            # once (each text may expand to several chunks). Each mini-
            # batch produces (m, 384); we stack them at the end.
            step = max(batch_size * 8, 256)
            out_chunks: list[np.ndarray] = []
            for start in range(0, len(texts), step):
                vecs, _telemetry = client.embed_batch(texts[start : start + step])
                out_chunks.append(np.asarray(vecs, dtype=np.float32))
            if not out_chunks:
                return np.empty((0, VECTOR_DIM), dtype=np.float32)
            return np.concatenate(out_chunks, axis=0)

        encoder = _default_encoder

    # For determinism of the GLOBAL scale across cache hits + misses, we
    # always run the encoder over the FULL article set when ANY cluster is
    # missing — otherwise an incremental rebuild could shift max_abs and
    # invalidate the cache contract. The per-cluster cache becomes
    # meaningful in the "no inputs changed" case (full hit) but on any
    # delta we recompute everything for byte-identity.
    try:
        all_vectors = encoder(list(article_texts))
    except Exception as exc:
        raise EmbeddingComputeError(
            f"encoder failed: {exc}",
            reason="encoder_failed",
            n_titles=len(article_texts),
        ) from exc
    all_vectors = np.asarray(all_vectors, dtype=np.float32)
    if all_vectors.shape != (len(article_texts), VECTOR_DIM):
        raise EmbeddingComputeError(
            f"encoder output shape {all_vectors.shape!r} != "
            f"({len(article_texts)}, {VECTOR_DIM})",
            reason="encoder_output_shape",
            n_titles=len(article_texts),
        )
    if not np.isfinite(all_vectors).all():
        raise EmbeddingComputeError(
            "encoder output contains non-finite values",
            reason="encoder_output_nonfinite",
            n_titles=len(article_texts),
        )

    normed = _l2_renormalise(all_vectors)
    quant, scale, max_abs = _quantise_int8(normed)

    try:
        model_sha256 = load_model_sha256(model_id)
    except EmbeddingComputeError:
        # Tests / synthetic-encoder paths may not have a real on-disk
        # model; the manifest then records the synthetic-encoder sentinel.
        model_sha256 = "synthetic-encoder-sha256-stub"

    # Re-partition by cluster + persist.
    pubmed_arr = np.asarray(pubmed_ids, dtype=np.int64)
    clusters_out: list[ClusterVectors] = []
    for cid, idxs in sorted(cluster_to_indices.items()):
        idx_arr = np.asarray(idxs, dtype=np.int64)
        cv = ClusterVectors(
            cluster_id=cid,
            pubmed_ids=pubmed_arr[idx_arr],
            vectors_int8=quant[idx_arr],
        )
        np.savez_compressed(
            state_dir / f"cluster_{cid}.npz",
            pubmed_ids=cv.pubmed_ids,
            vectors_int8=cv.vectors_int8,
        )
        clusters_out.append(cv)

    scale_path.write_text(
        json.dumps(
            {
                "scale": scale,
                "max_abs_original": max_abs,
                "model_id": model_id,
                "model_sha256": model_sha256,
            },
            sort_keys=True,
        )
    )
    return VectorsComputeResult(
        clusters=clusters_out,
        scale=scale,
        max_abs_original=max_abs,
        model_sha256=model_sha256,
        cache_hits=cache_hits,
        cache_misses=cache_misses,
    )
