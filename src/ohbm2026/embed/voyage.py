"""Stage 3 Voyage embedding runner.

Thin wrapper over the `voyageai` SDK that exposes one entrypoint —
`VoyageBatchClient.embed_batch(texts)` — returning a list of float
vectors and the SDK-reported model id. The orchestrator handles
batching, caching, and dynamic concurrency; this module only owns
the per-batch call shape + provider error mapping.
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
    "DEFAULT_VOYAGE_MODEL",
    "VoyageBatchClient",
]


DEFAULT_VOYAGE_MODEL = "voyage-large-2-instruct"


class VoyageBatchClient:
    """One-call-per-batch wrapper around the Voyage SDK.

    The constructor accepts an already-built `voyageai.Client` (or a
    test fake exposing `.embed(texts, model=...)`); the orchestrator
    builds the real one. Keeping the SDK reference out of import-time
    state lets tests inject fakes without monkey-patching the module.
    """

    def __init__(
        self,
        client: Any,
        model_id: str = DEFAULT_VOYAGE_MODEL,
        *,
        input_type: str = "document",
        max_retries: int = 3,
    ) -> None:
        self._client = client
        self.model_id = model_id
        self.input_type = input_type
        self.max_retries = max_retries
        # Populated after first successful call (Principle VII: discover, don't hardcode).
        self.reported_model: str | None = None
        self.dim: int | None = None

    def embed_batch(self, texts: list[str]) -> tuple[list[list[float]], dict]:
        """Send one batch. Returns `(vectors, telemetry)`.

        Telemetry: {tokens_used, reported_model, attempts, latency_ms}.

        Maps SDK errors to typed Stage 3 exceptions:
        - rate-limit-after-retries → EmbeddingProviderError
        - budget / quota → EmbeddingBudgetError
        - cardinality mismatch / off-model-id → EmbeddingContractError
        """
        start = time.perf_counter()
        last_exc: BaseException | None = None
        for attempt in range(1, self.max_retries + 1):
            try:
                resp = self._client.embed(
                    texts=texts,
                    model=self.model_id,
                    input_type=self.input_type,
                )
            except Exception as exc:  # noqa: BLE001 — Voyage SDK error types vary
                msg = str(exc).lower()
                if "insufficient" in msg or "budget" in msg or "quota" in msg or "402" in msg:
                    raise EmbeddingBudgetError(
                        f"Voyage budget exhausted: {exc}"
                    ) from exc
                last_exc = exc
                # Backoff: 1s, 2s, 4s
                if attempt < self.max_retries:
                    time.sleep(2 ** (attempt - 1))
                    continue
                raise EmbeddingProviderError(
                    f"Voyage call failed after {attempt} attempts: {exc}"
                ) from exc
            # Success path
            vectors = list(getattr(resp, "embeddings", None) or resp["embeddings"])
            usage = getattr(resp, "usage", None) or (resp.get("usage") if isinstance(resp, dict) else None) or {}
            tokens = int(usage.get("total_tokens", 0) or 0) if isinstance(usage, dict) else 0
            reported = getattr(resp, "model", None) or (resp.get("model") if isinstance(resp, dict) else None) or self.model_id
            if len(vectors) != len(texts):
                raise EmbeddingContractError(
                    f"Voyage returned {len(vectors)} vectors for a batch of {len(texts)} inputs"
                )
            if self.reported_model is None:
                self.reported_model = reported
                self.dim = len(vectors[0]) if vectors else None
            if self.dim is not None and vectors and len(vectors[0]) != self.dim:
                raise EmbeddingContractError(
                    f"Voyage dim drifted: expected {self.dim}, got {len(vectors[0])}"
                )
            telemetry = {
                "tokens_used": tokens,
                "reported_model": reported,
                "attempts": attempt,
                "latency_ms": (time.perf_counter() - start) * 1000.0,
            }
            return vectors, telemetry
        # unreachable
        raise EmbeddingProviderError(
            f"Voyage call failed: {last_exc!r}"
        )
