"""LLM adapter that wires Stage 2.1's `enrich.flex_tier` into the Stage 4
topic-grouping pipeline.

`build_topics_artifact(..., llm_call=adapter)` consumes a
`(prompt: str, model_id: str) -> response_text: str` callable.
This module produces one when the run wants real LLM grouping
(i.e., `skip_llm_topics=False`).
"""

from __future__ import annotations

import os
from typing import Callable

from ohbm2026.exceptions import AnalysisError

LLMCaller = Callable[[str, str], str]

DEFAULT_TIMEOUT_SECONDS = 120.0


def build_topics_llm_adapter(
    *,
    flex_enabled: bool = True,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    component: str = "stage4.topics",
) -> LLMCaller:
    """Return a `(prompt, model_id) -> response_text` adapter that wraps
    `openai.responses.create(...)` with flex-tier retry semantics.

    Raises `AnalysisError` at call time if `OPENAI_API_KEY` is missing —
    catching it early would mask configuration mistakes. Callers that
    don't want LLM grouping should pass `--skip-llm-topics` so this
    adapter never gets built or invoked.
    """
    try:
        from openai import OpenAI
    except ImportError as exc:  # pragma: no cover — declared in deps
        raise AnalysisError(
            "openai SDK not installed; required for LLM topic grouping. "
            "Install via `uv pip install --python .venv/bin/python openai` "
            "or rerun with `--skip-llm-topics`."
        ) from exc

    from ohbm2026.enrich.flex_tier import call_with_flex_fallback

    def adapter(prompt: str, model_id: str) -> str:
        if not os.environ.get("OPENAI_API_KEY"):
            raise AnalysisError(
                "OPENAI_API_KEY not set; LLM topic grouping requires a key. "
                "Either export OPENAI_API_KEY or rerun with `--skip-llm-topics`."
            )
        client = OpenAI()

        def _call(*, service_tier, timeout):
            return client.responses.create(
                model=model_id,
                input=[
                    {
                        "role": "system",
                        "content": (
                            "You are a scientific topic-labeling assistant. "
                            "Reply with a single strictly-valid JSON object only, "
                            "no markdown fences, no commentary."
                        ),
                    },
                    {"role": "user", "content": prompt},
                ],
                service_tier=service_tier,
                timeout=timeout,
            )

        result = call_with_flex_fallback(
            _call,
            flex_enabled=flex_enabled,
            timeout_seconds=timeout_seconds,
            component=component,
        )
        response = result.response
        text = getattr(response, "output_text", None)
        if not text:
            try:
                text = response.output[0].content[0].text  # type: ignore[index]
            except (AttributeError, IndexError, KeyError) as exc:
                raise AnalysisError(
                    f"{component}: LLM response had no extractable text"
                ) from exc
        # Strip common markdown fences models add despite the system prompt.
        stripped = text.strip()
        if stripped.startswith("```"):
            stripped = stripped.split("\n", 1)[1] if "\n" in stripped else stripped[3:]
            if stripped.rstrip().endswith("```"):
                stripped = stripped.rstrip()[:-3]
        return stripped.strip()

    return adapter
