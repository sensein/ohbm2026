"""Stage 3 Voyage embedding runner.

Uses the Voyage REST API directly (no SDK) because the `voyageai`
SDK pulls in a Pydantic V1 multimodal-input class that is broken on
Python 3.14 (its `min_items` constraint on a Union field is no
longer enforceable by pydantic.v1). The REST endpoint is documented,
stable, and the parameters we need are minimal: `model`, `input`,
`input_type`.

Public surface unchanged: `VoyageBatchClient(api_key,
model_id).embed_batch(texts) -> (vectors, telemetry)`.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
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
_VOYAGE_ENDPOINT = "https://api.voyageai.com/v1/embeddings"


class VoyageBatchClient:
    """One-call-per-batch wrapper around the Voyage REST embeddings endpoint.

    Accepts an `api_key` directly so the orchestrator can pass it in
    memory without going through environment variables (Principle V).
    Test fakes can substitute the `_send` method to inject deterministic
    responses; see tests/test_embed_stage.py for the pattern (the
    orchestrator's tests use a fake `_FakeBatchClient` with the same
    public surface).
    """

    def __init__(
        self,
        api_key: str | None = None,
        model_id: str = DEFAULT_VOYAGE_MODEL,
        *,
        input_type: str = "document",
        max_retries: int = 3,
        timeout_seconds: float = 60.0,
    ) -> None:
        if not api_key:
            raise EmbeddingProviderError(
                "VoyageBatchClient requires an api_key (pass it in-memory "
                "rather than via os.environ; Principle V)."
            )
        self._api_key = api_key
        self.model_id = model_id
        self.input_type = input_type
        self.max_retries = max_retries
        self.timeout_seconds = timeout_seconds
        # Populated after first successful call (Principle VII).
        self.reported_model: str | None = None
        self.dim: int | None = None

    def _send(self, texts: list[str]) -> dict:
        """Send one HTTP POST to Voyage's embeddings endpoint.

        Returns the parsed JSON body. Raises urllib.error.HTTPError on
        non-2xx responses; the caller maps to typed Stage 3 errors.
        """
        body = json.dumps({
            "input": texts,
            "model": self.model_id,
            "input_type": self.input_type,
        }).encode("utf-8")
        req = urllib.request.Request(
            _VOYAGE_ENDPOINT,
            data=body,
            method="POST",
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
                "User-Agent": "ohbm2026-stage3-embed",
            },
        )
        with urllib.request.urlopen(req, timeout=self.timeout_seconds) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def embed_batch(self, texts: list[str]) -> tuple[list[list[float]], dict]:
        """Send one batch. Returns `(vectors, telemetry)`.

        Maps HTTP / parse failures to typed Stage 3 exceptions:
        - 4xx that mentions budget / quota → EmbeddingBudgetError
        - other 4xx/5xx past retries → EmbeddingProviderError
        - cardinality mismatch / dim drift → EmbeddingContractError
        """
        start = time.perf_counter()
        last_exc: BaseException | None = None
        for attempt in range(1, self.max_retries + 1):
            try:
                data = self._send(texts)
            except urllib.error.HTTPError as exc:
                try:
                    err_body = exc.read().decode("utf-8")
                except Exception:  # noqa: BLE001
                    err_body = ""
                msg = err_body.lower()
                if exc.code == 402 or "insufficient" in msg or "quota" in msg or "budget" in msg:
                    raise EmbeddingBudgetError(
                        f"Voyage budget exhausted: HTTP {exc.code} {err_body[:200]}"
                    ) from exc
                last_exc = exc
                if attempt < self.max_retries and exc.code >= 500 or exc.code == 429:
                    time.sleep(2 ** (attempt - 1))
                    continue
                raise EmbeddingProviderError(
                    f"Voyage HTTP {exc.code} after {attempt} attempts: {err_body[:200]}"
                ) from exc
            except urllib.error.URLError as exc:
                last_exc = exc
                if attempt < self.max_retries:
                    time.sleep(2 ** (attempt - 1))
                    continue
                raise EmbeddingProviderError(
                    f"Voyage network error after {attempt} attempts: {exc}"
                ) from exc

            # Parse response.
            entries = data.get("data") or data.get("embeddings") or []
            if not entries:
                raise EmbeddingContractError(
                    f"Voyage response missing data/embeddings array: {data!r}"
                )
            # Voyage returns either a flat list (older) or a list of
            # {object, embedding, index} (newer, OpenAI-style).
            vectors: list[list[float]] = []
            for entry in entries:
                if isinstance(entry, list):
                    vectors.append(list(entry))
                elif isinstance(entry, dict) and "embedding" in entry:
                    vectors.append(list(entry["embedding"]))
                else:
                    raise EmbeddingContractError(
                        f"Voyage response has unexpected entry shape: {entry!r}"
                    )
            if len(vectors) != len(texts):
                raise EmbeddingContractError(
                    f"Voyage returned {len(vectors)} vectors for a batch of {len(texts)} inputs"
                )
            usage = data.get("usage") or {}
            tokens = int(usage.get("total_tokens", 0) or 0)
            reported = data.get("model") or self.model_id

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
        raise EmbeddingProviderError(f"Voyage call failed: {last_exc!r}")
