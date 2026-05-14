"""Stage 3 OpenAI embedding runner.

Thin wrapper over the OpenAI Python SDK's embeddings endpoint. Same
shape as `VoyageBatchClient` so the orchestrator can dispatch
polymorphically.
"""

from __future__ import annotations

import time
from typing import Any

from ohbm2026.exceptions import (
    EmbeddingBudgetError,
    EmbeddingContractError,
    EmbeddingProviderError,
)

__all__ = [
    "DEFAULT_OPENAI_MODEL",
    "OpenAIBatchClient",
]


DEFAULT_OPENAI_MODEL = "text-embedding-3-small"


class OpenAIBatchClient:
    """One-call-per-batch wrapper around `openai.embeddings.create`."""

    def __init__(
        self,
        client: Any,
        model_id: str = DEFAULT_OPENAI_MODEL,
        *,
        max_retries: int = 3,
    ) -> None:
        self._client = client
        self.model_id = model_id
        self.max_retries = max_retries
        self.reported_model: str | None = None
        self.dim: int | None = None

    def embed_batch(self, texts: list[str]) -> tuple[list[list[float]], dict]:
        start = time.perf_counter()
        last_exc: BaseException | None = None
        for attempt in range(1, self.max_retries + 1):
            try:
                resp = self._client.embeddings.create(
                    input=texts,
                    model=self.model_id,
                )
            except Exception as exc:  # noqa: BLE001 — openai exception types vary
                msg = str(exc).lower()
                if "insufficient_quota" in msg or "billing" in msg or "402" in msg:
                    raise EmbeddingBudgetError(
                        f"OpenAI budget exhausted: {exc}"
                    ) from exc
                last_exc = exc
                if attempt < self.max_retries:
                    time.sleep(2 ** (attempt - 1))
                    continue
                raise EmbeddingProviderError(
                    f"OpenAI call failed after {attempt} attempts: {exc}"
                ) from exc
            data = list(getattr(resp, "data", None) or resp.get("data") or [])
            if len(data) != len(texts):
                raise EmbeddingContractError(
                    f"OpenAI returned {len(data)} vectors for a batch of {len(texts)} inputs"
                )
            vectors = [list(getattr(item, "embedding", None) or item["embedding"]) for item in data]
            usage = getattr(resp, "usage", None) or (resp.get("usage") if isinstance(resp, dict) else None)
            tokens = int(getattr(usage, "total_tokens", 0) or (usage.get("total_tokens", 0) if isinstance(usage, dict) else 0) or 0) if usage else 0
            reported = getattr(resp, "model", None) or (resp.get("model") if isinstance(resp, dict) else None) or self.model_id
            if self.reported_model is None:
                self.reported_model = reported
                self.dim = len(vectors[0]) if vectors else None
            if self.dim is not None and vectors and len(vectors[0]) != self.dim:
                raise EmbeddingContractError(
                    f"OpenAI dim drifted: expected {self.dim}, got {len(vectors[0])}"
                )
            telemetry = {
                "tokens_used": tokens,
                "reported_model": reported,
                "attempts": attempt,
                "latency_ms": (time.perf_counter() - start) * 1000.0,
            }
            return vectors, telemetry
        raise EmbeddingProviderError(f"OpenAI call failed: {last_exc!r}")
