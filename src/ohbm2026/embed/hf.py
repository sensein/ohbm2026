"""Stage 3 HuggingFace / Sentence-Transformers embedding runner.

One class with two convenient defaults: `MiniLMClient` and
`PubMedBERTClient`. Both share the same `embed_batch(texts)`
interface as the paid-provider clients so the orchestrator can
dispatch polymorphically.

Long-input strategy defaults to `chunk_mean_pool` (window 512,
overlap 64) for local transformer encoders per FR-010 and the
Phase 0 research decision.
"""

from __future__ import annotations

import time
from typing import Any, Iterable

from ohbm2026.exceptions import (
    EmbeddingContractError,
    EmbeddingProviderError,
)

__all__ = [
    "DEFAULT_MINILM_MODEL",
    "DEFAULT_PUBMEDBERT_MODEL",
    "DEFAULT_CHUNK_WINDOW",
    "DEFAULT_CHUNK_OVERLAP",
    "HFBatchClient",
]


DEFAULT_MINILM_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
DEFAULT_PUBMEDBERT_MODEL = "neuml/pubmedbert-base-embeddings"
DEFAULT_CHUNK_WINDOW = 512
DEFAULT_CHUNK_OVERLAP = 64


class HFBatchClient:
    """Sentence-Transformers wrapper with chunk_mean_pool long-input handling.

    Lazy-loads the model on first call so test fixtures can pass a
    fake encoder. The encoder's `encode(texts, ...)` MUST return a
    numpy array of shape `[N, dim]` or a list of length N.
    """

    def __init__(
        self,
        model: Any | None = None,
        *,
        model_id: str = DEFAULT_MINILM_MODEL,
        chunk_window: int = DEFAULT_CHUNK_WINDOW,
        chunk_overlap: int = DEFAULT_CHUNK_OVERLAP,
        long_input_strategy: str = "chunk_mean_pool",
        batch_size: int = 64,
    ) -> None:
        self._model = model
        self.model_id = model_id
        self.chunk_window = chunk_window
        self.chunk_overlap = chunk_overlap
        self.long_input_strategy = long_input_strategy
        self.batch_size = batch_size
        # Filled in on first call.
        self.reported_model: str | None = None
        self.dim: int | None = None

    def _ensure_model(self) -> Any:
        if self._model is None:
            from sentence_transformers import SentenceTransformer
            self._model = SentenceTransformer(self.model_id)
        return self._model

    def _encode(self, texts: list[str]) -> list[list[float]]:
        model = self._ensure_model()
        out = model.encode(
            texts,
            batch_size=min(self.batch_size, max(1, len(texts))),
            show_progress_bar=False,
            convert_to_numpy=True,
            normalize_embeddings=False,
        )
        # Normalize to list-of-lists of floats.
        if hasattr(out, "tolist"):
            out = out.tolist()
        return [list(v) for v in out]

    def _split_into_chunks(self, text: str) -> list[str]:
        """Split `text` into overlapping windows by token-approximate
        character count. This is the same fixed-width recipe used by
        the legacy `neuroscape.hf_embed` chunking path — a fully
        token-correct version requires the tokenizer, which is left
        to the underlying SentenceTransformer.

        We use character windows of `chunk_window * 4` chars as a
        proxy for `chunk_window` tokens (~4 chars/token on English
        scientific text); good enough to keep batches small without
        being aggressive about the actual token limit.
        """
        if not text:
            return []
        win_chars = self.chunk_window * 4
        overlap_chars = self.chunk_overlap * 4
        if len(text) <= win_chars:
            return [text]
        chunks: list[str] = []
        step = max(1, win_chars - overlap_chars)
        for start in range(0, len(text), step):
            chunk = text[start : start + win_chars]
            if not chunk:
                break
            chunks.append(chunk)
            if start + win_chars >= len(text):
                break
        return chunks

    def embed_batch(self, texts: list[str]) -> tuple[list[list[float]], dict]:
        """Embed a batch of texts.

        For each input over the chunk window, splits into chunks,
        embeds each chunk, and mean-pools the result. The returned
        `truncated_flags` telemetry records which inputs were chunked.
        """
        if self.long_input_strategy != "chunk_mean_pool":
            raise EmbeddingProviderError(
                f"HF client only supports chunk_mean_pool for now, got "
                f"{self.long_input_strategy!r}"
            )
        start = time.perf_counter()
        # Per-input chunk lists; remember the flat index ranges so we
        # can mean-pool after one big encode call.
        chunk_lists: list[list[str]] = [self._split_into_chunks(t) for t in texts]
        flat_chunks: list[str] = []
        ranges: list[tuple[int, int]] = []
        for chunks in chunk_lists:
            i0 = len(flat_chunks)
            flat_chunks.extend(chunks if chunks else [""])  # placeholder for empty
            ranges.append((i0, len(flat_chunks)))
        if not flat_chunks:
            return [], {
                "attempts": 1,
                "latency_ms": 0.0,
                "reported_model": self.model_id,
                "tokens_used": 0,
                "truncated_count": 0,
                "truncated_flags": [],
            }
        try:
            flat_vectors = self._encode(flat_chunks)
        except Exception as exc:  # noqa: BLE001
            raise EmbeddingProviderError(
                f"HF encode failed: {exc}"
            ) from exc

        import numpy as np

        out_vectors: list[list[float]] = []
        truncated_flags: list[bool] = []
        for chunks, (i0, i1) in zip(chunk_lists, ranges):
            slab = np.asarray(flat_vectors[i0:i1], dtype=np.float32)
            if slab.shape[0] == 0:
                pooled = np.zeros((self.dim or slab.shape[1] if slab.size else 1,), dtype=np.float32)
            elif slab.shape[0] == 1:
                pooled = slab[0]
            else:
                pooled = slab.mean(axis=0)
            out_vectors.append(pooled.tolist())
            truncated_flags.append(len(chunks) > 1)
        if self.dim is None and out_vectors:
            self.dim = len(out_vectors[0])
        if self.reported_model is None:
            self.reported_model = self.model_id
        telemetry = {
            "attempts": 1,
            "latency_ms": (time.perf_counter() - start) * 1000.0,
            "reported_model": self.reported_model,
            "tokens_used": 0,  # local model — no token billing
            "truncated_count": sum(1 for f in truncated_flags if f),
            "truncated_flags": truncated_flags,
        }
        if any(len(v) != len(out_vectors[0]) for v in out_vectors[1:]) if len(out_vectors) > 1 else False:
            raise EmbeddingContractError(
                "HF encoder returned vectors of inconsistent dimension"
            )
        return out_vectors, telemetry


def make_minilm_client() -> HFBatchClient:
    """Default MiniLM client (matches the UI search model)."""
    return HFBatchClient(model_id=DEFAULT_MINILM_MODEL)


def make_pubmedbert_client() -> HFBatchClient:
    """Default PubMedBERT client (Sentence-Transformers compatible mirror)."""
    return HFBatchClient(model_id=DEFAULT_PUBMEDBERT_MODEL)
