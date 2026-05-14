"""Flex-tier retry/fallback helper for Stage 2.1 LLM calls.

Wraps a single OpenAI Responses API call with:

- An explicit per-request timeout (component-specific default).
- A standard-tier retry on flex timeout / service-unavailable.
- A bounded retry budget; on exhaustion, raise `EnrichmentError`
  so the orchestrator's component-failure-threshold logic kicks
  in.

The helper is synchronous (one logical request at a time). The
orchestrator-level fan-out across abstracts lives in
`enrich_stage._run_component_concurrent`; this module worries
only about one call's tier policy.
"""

from __future__ import annotations

import dataclasses
import time
from typing import Any, Callable, Literal

import openai

from ohbm2026.exceptions import ContextLengthExceededError, EnrichmentError

__all__ = [
    "FlexTierResult",
    "call_with_flex_fallback",
    "DEFAULT_FIGURES_TIMEOUT_SECONDS",
    "DEFAULT_CLAIMS_TIMEOUT_SECONDS",
    "DEFAULT_MAX_RETRIES",
]

DEFAULT_FIGURES_TIMEOUT_SECONDS: int = 120
DEFAULT_CLAIMS_TIMEOUT_SECONDS: int = 180
DEFAULT_MAX_RETRIES: int = 2  # one flex attempt + one standard-tier retry


@dataclasses.dataclass
class FlexTierResult:
    """The outcome of one logical request, regardless of which tier
    actually served it."""

    response: Any
    tier_used: Literal["flex", "standard"]
    flex_timed_out: bool
    latency_ms: float
    attempts: int


# OpenAI exception types that indicate flex tier should retry on
# standard. APITimeoutError covers explicit timeouts; APIConnection
# Error covers network blips; InternalServerError + service_un-
# available status covers OpenAI-side capacity issues.
_FLEX_RETRYABLE: tuple[type[BaseException], ...] = (
    openai.APITimeoutError,
    openai.APIConnectionError,
    openai.InternalServerError,
)


def _extract_error_code(exc: openai.BadRequestError) -> str | None:
    """Pull the `error.code` field out of an SDK BadRequestError body
    (it's not always exposed as an attribute on older SDK builds)."""
    body = getattr(exc, "body", None) or {}
    if isinstance(body, dict):
        err = body.get("error") or {}
        if isinstance(err, dict):
            code = err.get("code")
            if isinstance(code, str):
                return code
    return None


def call_with_flex_fallback(
    client_call: Callable[..., Any],
    *,
    flex_enabled: bool,
    timeout_seconds: float,
    max_retries: int = DEFAULT_MAX_RETRIES,
    component: str = "unknown",
) -> FlexTierResult:
    """Invoke `client_call(service_tier=..., timeout=...)` with
    flex-then-standard semantics.

    `client_call` is a zero-arg lambda that closes over the
    OpenAI client + the request kwargs and returns the SDK
    response object. The helper invokes it up to `max_retries`
    times, varying only the `service_tier` and `timeout` kwargs.

    On exhaustion, raises `EnrichmentError` naming the component
    and the final exception. The orchestrator catches this and
    increments the typed failure-threshold counter.

    Note: `client_call` MUST accept `service_tier` and `timeout`
    keyword arguments. Production callers pass a `functools.partial`
    or a small closure that forwards them to
    `client.responses.parse(...)` / `client.responses.create(...)`.
    """
    attempts = 0
    flex_timed_out = False
    tiers_to_try: list[Literal["flex", "standard"]] = (
        ["flex", "standard"] if flex_enabled else ["standard"]
    )

    last_exc: BaseException | None = None
    for tier in tiers_to_try:
        if attempts >= max_retries:
            break
        attempts += 1
        start = time.perf_counter()
        try:
            response = client_call(service_tier=tier, timeout=timeout_seconds)
        except openai.BadRequestError as exc:
            # Deterministic input-side rejection. Retrying with the
            # same input — even on a different tier — fails identically,
            # so surface as a typed failure for the orchestrator
            # (Principle VI). `context_length_exceeded` gets its own
            # subclass so callers can attempt a larger-model fallback.
            code = (getattr(exc, "code", None)
                    or _extract_error_code(exc)
                    or getattr(exc, "status_code", "?"))
            if code == "context_length_exceeded":
                raise ContextLengthExceededError(
                    f"{component}: context_length_exceeded: {exc}"
                ) from exc
            raise EnrichmentError(
                f"{component}: non-retryable BadRequestError ({code}): {exc}"
            ) from exc
        except _FLEX_RETRYABLE as exc:
            last_exc = exc
            if tier == "flex":
                flex_timed_out = True
            continue
        else:
            elapsed_ms = (time.perf_counter() - start) * 1000.0
            return FlexTierResult(
                response=response,
                tier_used=tier,
                flex_timed_out=flex_timed_out,
                latency_ms=elapsed_ms,
                attempts=attempts,
            )

    # Both attempts exhausted (or single attempt failed) — escalate.
    raise EnrichmentError(
        f"{component}: retry budget exhausted after {attempts} attempts "
        f"(last error: {type(last_exc).__name__}: {last_exc})"
    ) from last_exc
