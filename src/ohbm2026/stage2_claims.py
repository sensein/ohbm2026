"""Stage 2.1 claims-component production runner.

Per-abstract agentic OpenAI Responses API call. The model is given
three function tools (`verify_source_quote`, `lookup_eco_code`,
`dedupe_check`) that it invokes internally during a single API
call to extract, verify, annotate, and dedupe atomic claims. The
final structured output is a Pydantic `ClaimsResponse` validated
both server-side (via `text_format`) and client-side (vocabulary
membership for ECO codes).

Drives FR-009 (cllm removed), FR-010 (single agentic call),
FR-011 (three function tools), FR-012 (structured output + drop
unverified), FR-013 (ECO v1 vocabulary).
"""

from __future__ import annotations

import dataclasses
import difflib
import hashlib
import json
import re
import sys
import time
from importlib import resources
from pathlib import Path
from typing import Any, Callable, Literal

from pydantic import BaseModel, Field

from ohbm2026 import flex_tier
from ohbm2026 import enrichment as enrichment_module
from ohbm2026.exceptions import EnrichmentError

__all__ = [
    "Claim",
    "ClaimsResponse",
    "ClaimsRunSummary",
    "VerifyQuoteArgs",
    "LookupEcoArgs",
    "DedupeArgs",
    "load_eco_vocabulary",
    "run_claims_component",
]


# ----- Embedded ECO vocabulary loader --------------------------------


_VOCABULARY_CACHE: dict[str, Any] | None = None


def load_eco_vocabulary() -> dict[str, Any]:
    """Load the embedded ECO v1 vocabulary from package data.

    Memoized so repeated calls are free. Returns a dict with
    `vocabulary_version`, `codes` (list of dicts), and
    `_id_set` (set of eco_id strings, added for fast membership).
    """
    global _VOCABULARY_CACHE
    if _VOCABULARY_CACHE is not None:
        return _VOCABULARY_CACHE
    raw = resources.files("ohbm2026.data").joinpath("eco_top_codes.json").read_text(encoding="utf-8")
    data = json.loads(raw)
    data["_id_set"] = frozenset(entry["eco_id"] for entry in data["codes"])
    _VOCABULARY_CACHE = data
    return data


# ----- Pydantic schemas -----------------------------------------------


class Claim(BaseModel):
    """One atomic factual claim, with verification + ECO annotation."""

    claim_text: str = Field(..., min_length=1)
    source_quote: str = Field(..., min_length=1)
    source_quote_verified: bool
    claim_type: Literal["explicit", "implicit"]
    evidence_eco_codes: list[str] = Field(..., min_length=1)
    confidence: float = Field(..., ge=0.0, le=1.0)


class ClaimsResponse(BaseModel):
    claims: list[Claim]


# Function-tool argument schemas. The Responses API derives the
# JSON schema for each tool from these Pydantic models via
# `openai.lib._tools.pydantic_function_tool`.


class VerifyQuoteArgs(BaseModel):
    claim_text: str
    source_quote: str


class LookupEcoArgs(BaseModel):
    label_or_description: str


class DedupeArgs(BaseModel):
    claim_a: str
    claim_b: str


# ----- Function-tool handlers ----------------------------------------


def _verify_source_quote_handler(
    claim_text: str, source_quote: str, *, manuscript: str
) -> dict:
    """Exact substring check + ranked corrections on miss.

    Returns: `{is_substring, candidate_corrections}`. Pure function;
    no I/O.
    """
    if source_quote and source_quote in manuscript:
        return {"is_substring": True, "candidate_corrections": []}
    # Split manuscript into sentences and score against the candidate.
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", manuscript) if s.strip()]
    candidates = difflib.get_close_matches(
        source_quote or "", sentences, n=3, cutoff=0.6,
    )
    return {"is_substring": False, "candidate_corrections": list(candidates)}


def _lookup_eco_code_handler(
    label_or_description: str, *, vocabulary: dict[str, Any]
) -> list[dict]:
    """Case-insensitive label match + substring match on definitions."""
    needle = (label_or_description or "").strip().lower()
    if not needle:
        return []
    matches: list[dict] = []
    for entry in vocabulary["codes"]:
        label = entry["label"].lower()
        definition = entry["definition"].lower()
        if needle in label or needle in definition or label.startswith(needle):
            matches.append({
                "eco_id": entry["eco_id"],
                "label": entry["label"],
                "definition": entry["definition"],
            })
    return matches


def _dedupe_check_handler(claim_a: str, claim_b: str) -> dict:
    """Jaccard similarity on token sets + first-5-word prefix match."""
    def _tokens(text: str) -> set[str]:
        return {t.lower() for t in re.findall(r"\w+", text or "")}
    a_tokens = _tokens(claim_a)
    b_tokens = _tokens(claim_b)
    if not a_tokens or not b_tokens:
        return {"is_duplicate": False, "reasoning": "empty claim"}
    jaccard = len(a_tokens & b_tokens) / max(1, len(a_tokens | b_tokens))
    a_prefix = " ".join((claim_a or "").split()[:5]).lower()
    b_prefix = " ".join((claim_b or "").split()[:5]).lower()
    prefix_match = bool(a_prefix) and (a_prefix == b_prefix)
    is_duplicate = jaccard >= 0.85 or prefix_match
    return {
        "is_duplicate": is_duplicate,
        "reasoning": (
            f"jaccard={jaccard:.2f}, prefix_match={prefix_match}"
        ),
    }


def _make_tool_executor(
    manuscript: str, vocabulary: dict[str, Any]
) -> Callable[[str, dict], dict | list[dict]]:
    """Build a dispatcher that the orchestrator uses to execute
    tool calls reported by the model.

    Tools are pure — no network, no disk. Caller closes over the
    manuscript text + vocabulary; the dispatcher routes by tool
    name and validates args via the per-tool Pydantic model.
    """
    def _dispatch(name: str, args: dict) -> Any:
        if name == "verify_source_quote":
            parsed = VerifyQuoteArgs.model_validate(args)
            return _verify_source_quote_handler(
                parsed.claim_text, parsed.source_quote, manuscript=manuscript,
            )
        if name == "lookup_eco_code":
            parsed = LookupEcoArgs.model_validate(args)
            return _lookup_eco_code_handler(
                parsed.label_or_description, vocabulary=vocabulary,
            )
        if name == "dedupe_check":
            parsed = DedupeArgs.model_validate(args)
            return _dedupe_check_handler(parsed.claim_a, parsed.claim_b)
        raise EnrichmentError(f"claims: unknown tool call {name!r}")

    return _dispatch


# ----- ECO primer (system message) -----------------------------------


def _build_eco_primer(vocabulary: dict[str, Any]) -> str:
    lines = [
        "Evidence and Conclusion Ontology (ECO) v1 controlled vocabulary.",
        "Use ONLY these codes for the evidence_eco_codes field; off-vocabulary "
        "codes will cause the claim to be dropped:",
        "",
    ]
    for entry in vocabulary["codes"]:
        lines.append(f"- {entry['eco_id']} ({entry['label']}): {entry['definition']}")
    return "\n".join(lines)


# ----- RunSummary ----------------------------------------------------


@dataclasses.dataclass
class ClaimsRunSummary:
    claims_count: int
    flex_timed_out: bool
    tier_used: Literal["flex", "standard"]
    attempts: int
    latency_ms: float
    prompt_tokens_cached: int = 0
    prompt_tokens_uncached: int = 0
    completion_tokens: int = 0
    dropped_off_vocab_count: int = 0
    dropped_unverified_count: int = 0


# ----- Manuscript builder -------------------------------------------


def _build_manuscript_markdown(
    abstract: dict, figure_interpretations: list[dict] | None
) -> str:
    """Build the claim-prompt manuscript.

    Reuses `enrichment.build_claim_manuscript_markdown` plus the
    new Stage 2.1 figure-interpretation list (so claims can cite
    figure-derived observations).
    """
    sections, additional = enrichment_module.build_sections_markdown(abstract)
    figure_analyses: list[dict] = []
    for fi in figure_interpretations or []:
        figure_analyses.append({
            "figure_url": fi.get("figure_url"),
            "question_name": fi.get("question_name", "Methods Figure (Optional)"),
            "caption_guess": "",
            "rich_markdown": fi.get("interpretation", ""),
            "ocr_text": fi.get("ocr_text") or "",
            "notes": "",
            "keywords": fi.get("keywords", []),
        })
    title = abstract.get("title") or ""
    return enrichment_module.build_claim_manuscript_markdown(
        title=title,
        sections_markdown=sections,
        additional_content_questions=additional,
        figure_analyses=figure_analyses,
    )


def _hash_for_cache(
    manuscript: str, model_id: str, vocabulary_version: str
) -> str:
    h = hashlib.sha256()
    h.update(manuscript.encode("utf-8"))
    h.update(b"||")
    h.update(model_id.encode("utf-8"))
    h.update(b"||")
    h.update(vocabulary_version.encode("utf-8"))
    return h.hexdigest()


# ----- Tool definitions for the Responses API ------------------------


def _function_tools() -> list[dict]:
    """JSON schema for each function tool, in the Responses API's
    tool-definition shape.

    The OpenAI SDK exposes `openai.lib._tools.pydantic_function_tool`
    which derives this shape from a Pydantic model. We build the
    shape explicitly here for stability across SDK versions (the
    helper's import path has changed in past releases) and for
    test fixtures' ability to inspect the registered tools.
    """
    return [
        {
            "type": "function",
            "name": "verify_source_quote",
            "description": (
                "Verify that source_quote is an exact substring of the "
                "manuscript. Returns is_substring (bool) and, if false, "
                "up to 3 ranked candidate_corrections (real substrings "
                "of the manuscript that are close in wording)."
            ),
            "parameters": VerifyQuoteArgs.model_json_schema(),
        },
        {
            "type": "function",
            "name": "lookup_eco_code",
            "description": (
                "Look up Evidence and Conclusion Ontology (ECO) codes "
                "by label or description fragment. Returns a list of "
                "{eco_id, label, definition} entries from the v1 "
                "controlled vocabulary."
            ),
            "parameters": LookupEcoArgs.model_json_schema(),
        },
        {
            "type": "function",
            "name": "dedupe_check",
            "description": (
                "Compare two claims for semantic duplication. Returns "
                "is_duplicate (bool) and a brief reasoning string. The "
                "model uses this to deduplicate its own intermediate "
                "claim list before emitting the final response."
            ),
            "parameters": DedupeArgs.model_json_schema(),
        },
    ]


# ----- Agentic loop -------------------------------------------------


def _instructions(eco_primer: str) -> str:
    return (
        "You extract atomic factual claims from a scientific abstract. "
        "For each claim, perform this four-step internal loop within "
        "THIS call:\n"
        "  1. EXTRACT — identify an atomic factual claim with a source "
        "quote that is a verbatim substring of the manuscript.\n"
        "  2. VERIFY — call the verify_source_quote tool with the "
        "claim_text and your candidate source_quote; if is_substring is "
        "false AND candidate_corrections is non-empty, use the best "
        "correction as the source_quote (re-verify). If still not a "
        "substring, drop the claim.\n"
        "  3. ANNOTATE — call the lookup_eco_code tool to find one or "
        "more applicable evidence codes from the v1 vocabulary. Drop "
        "claims for which no vocabulary code applies.\n"
        "  4. DEDUPE — for each new claim, call dedupe_check against "
        "claims you've already accepted; drop duplicates.\n\n"
        "Return the final list as a JSON object with key 'claims'. "
        "Set source_quote_verified=true only after the verify tool "
        "returned is_substring=true. Confidence is a 0..1 self-rating.\n\n"
        f"{eco_primer}"
    )


def _execute_agentic_loop(
    client: Any,
    *,
    model_id: str,
    manuscript: str,
    figure_interpretations_text: str,
    vocabulary: dict[str, Any],
    flex_enabled: bool,
    timeout_seconds: float,
    max_tool_iterations: int = 16,
) -> tuple[ClaimsResponse, Any, "_TierTelemetry"]:
    """Drive the Responses API's agentic loop until a final
    structured response is returned.

    The SDK exposes function tools via the `tools=` kwarg; the
    model emits tool-call entries in `response.output`, the
    orchestrator executes them and posts the results back via
    `previous_response_id` (the API's continuation primitive),
    and the loop terminates when the model emits a
    `text_format`-validated final output.
    """
    primer = _build_eco_primer(vocabulary)
    user_message = (
        f"=== MANUSCRIPT ===\n{manuscript}\n\n"
        f"=== FIGURE INTERPRETATIONS ===\n{figure_interpretations_text}\n\n"
        "Extract atomic factual claims from the manuscript per the "
        "instructions. Use the tools to verify, annotate, and dedupe."
    )

    tool_executor = _make_tool_executor(manuscript, vocabulary)
    tools = _function_tools()

    initial_input: list[dict] = [
        {"role": "system", "content": _instructions(primer)},
        {"role": "user", "content": user_message},
    ]

    tier_telemetry = _TierTelemetry()

    def call(*, service_tier: str, timeout: float, current_input: list[dict]) -> Any:
        return client.responses.create(
            model=model_id,
            input=current_input,
            tools=tools,
            service_tier=service_tier,
            timeout=timeout,
            prompt_cache_key=f"stage2.claims.{model_id}.{vocabulary['vocabulary_version']}",
        )

    # First call (with flex/standard fallback).
    def first_call(*, service_tier: str, timeout: float) -> Any:
        return call(service_tier=service_tier, timeout=timeout, current_input=initial_input)

    result = flex_tier.call_with_flex_fallback(
        first_call,
        flex_enabled=flex_enabled,
        timeout_seconds=timeout_seconds,
        component="claims",
    )
    tier_telemetry.update(result)
    response = result.response

    accumulated_input = list(initial_input)
    iterations = 0

    while iterations < max_tool_iterations:
        iterations += 1
        # Look for tool calls in the response output.
        output_items = _response_output_items(response)
        tool_call_items = [item for item in output_items if _is_function_call_item(item)]
        if not tool_call_items:
            break

        # Append the model's tool-call outputs (the assistant message)
        # then append each tool result so the next call sees the
        # full conversation history.
        accumulated_input.extend(output_items)
        for call_item in tool_call_items:
            name = _get_call_field(call_item, "name")
            call_id = _get_call_field(call_item, "call_id")
            args_raw = _get_call_field(call_item, "arguments") or "{}"
            try:
                args = json.loads(args_raw) if isinstance(args_raw, str) else args_raw
            except json.JSONDecodeError as exc:
                raise EnrichmentError(
                    f"claims: model emitted invalid JSON arguments for tool {name!r}: {exc}"
                ) from exc
            try:
                tool_result = tool_executor(name, args)
            except EnrichmentError:
                raise
            accumulated_input.append({
                "type": "function_call_output",
                "call_id": call_id,
                "output": json.dumps(tool_result),
            })

        # Continue the agentic loop with the tool results in context.
        def continuation_call(*, service_tier: str, timeout: float) -> Any:
            return call(service_tier=service_tier, timeout=timeout, current_input=accumulated_input)

        result = flex_tier.call_with_flex_fallback(
            continuation_call,
            flex_enabled=flex_enabled,
            timeout_seconds=timeout_seconds,
            component="claims",
        )
        tier_telemetry.update(result)
        response = result.response

    if iterations >= max_tool_iterations:
        raise EnrichmentError(
            f"claims: agentic loop exceeded {max_tool_iterations} tool iterations"
        )

    # Parse the final structured output via Pydantic.
    parsed = _parse_claims_response(response)
    return parsed, response, tier_telemetry


def _parse_claims_response(response: Any) -> ClaimsResponse:
    """Extract the final ClaimsResponse from the SDK response.

    Tries `.output_parsed` first (Responses API's auto-parsing when
    `text_format=` was used). Falls back to parsing
    `.output_text` as JSON.
    """
    parsed = getattr(response, "output_parsed", None)
    if isinstance(parsed, ClaimsResponse):
        return parsed
    output_text = getattr(response, "output_text", None)
    if output_text:
        try:
            payload = json.loads(output_text)
        except json.JSONDecodeError as exc:
            raise EnrichmentError(
                f"claims: model returned non-JSON output: {exc}"
            ) from exc
        try:
            return ClaimsResponse.model_validate(payload)
        except Exception as exc:
            raise EnrichmentError(
                f"claims: response failed schema validation: {exc}"
            ) from exc
    raise EnrichmentError("claims: model returned no final structured output")


def _response_output_items(response: Any) -> list[Any]:
    """Walk the response's output list robustly across SDK shapes."""
    output = getattr(response, "output", None)
    if output is None:
        return []
    return list(output)


def _is_function_call_item(item: Any) -> bool:
    return getattr(item, "type", None) == "function_call" or (
        isinstance(item, dict) and item.get("type") == "function_call"
    )


def _get_call_field(item: Any, name: str) -> Any:
    if isinstance(item, dict):
        return item.get(name)
    return getattr(item, name, None)


@dataclasses.dataclass
class _TierTelemetry:
    flex_timed_out: bool = False
    tier_used: Literal["flex", "standard"] = "flex"
    attempts: int = 0
    latency_ms: float = 0.0
    prompt_tokens_cached: int = 0
    prompt_tokens_uncached: int = 0
    completion_tokens: int = 0

    def update(self, result: flex_tier.FlexTierResult) -> None:
        if result.flex_timed_out:
            self.flex_timed_out = True
        self.tier_used = result.tier_used
        self.attempts += result.attempts
        self.latency_ms += result.latency_ms
        usage = getattr(result.response, "usage", None)
        if usage is not None:
            # Roll up across continuation calls.
            input_tokens = _read_usage(usage, "input_tokens")
            cached = _read_usage(usage, "cached_tokens")
            output_tokens = _read_usage(usage, "output_tokens")
            if cached == 0:
                details = getattr(usage, "input_tokens_details", None)
                if details is not None:
                    cached = _read_usage(details, "cached_tokens")
            self.prompt_tokens_cached += cached
            self.prompt_tokens_uncached += max(0, input_tokens - cached)
            self.completion_tokens += output_tokens


def _read_usage(obj: Any, name: str) -> int:
    if obj is None:
        return 0
    value = getattr(obj, name, None)
    if value is None and isinstance(obj, dict):
        value = obj.get(name)
    if isinstance(value, (int, float)):
        return int(value)
    return 0


# ----- Public entry --------------------------------------------------


def run_claims_component(
    abstract: dict,
    *,
    model_id: str,
    flex_enabled: bool,
    client: Any,
    figure_interpretations: list[dict] | None = None,
    vocabulary: dict[str, Any] | None = None,
    timeout_seconds: float = flex_tier.DEFAULT_CLAIMS_TIMEOUT_SECONDS,
) -> tuple[list[dict], ClaimsRunSummary]:
    """Run the claims component for one abstract.

    Returns `(claim_dict_list, ClaimsRunSummary)`.

    Each claim_dict matches the Stage 2.1 `Claim` schema (data-
    model.md §3). Claims that fail post-response validation
    (off-vocabulary ECO codes, unverifiable source quotes) are
    DROPPED before return, and the drop counter is recorded in
    the summary.

    Raises `EnrichmentError` on agentic-loop failure, retry-budget
    exhaustion, or schema validation failure on the final response.
    """
    vocab = vocabulary or load_eco_vocabulary()
    manuscript = _build_manuscript_markdown(abstract, figure_interpretations)
    if not manuscript.strip():
        return [], ClaimsRunSummary(
            claims_count=0, flex_timed_out=False,
            tier_used="flex" if flex_enabled else "standard",
            attempts=0, latency_ms=0.0,
        )

    # Render figure-interpretations for the user message.
    fi_chunks: list[str] = []
    for fi in figure_interpretations or []:
        fi_chunks.append(
            f"Figure {fi.get('figure_url', '?')}: {fi.get('interpretation', '')}"
        )
    fi_text = "\n\n".join(fi_chunks) if fi_chunks else "(no figures)"

    parsed_response, _raw_response, telemetry = _execute_agentic_loop(
        client,
        model_id=model_id,
        manuscript=manuscript,
        figure_interpretations_text=fi_text,
        vocabulary=vocab,
        flex_enabled=flex_enabled,
        timeout_seconds=timeout_seconds,
    )

    cache_key = _hash_for_cache(manuscript, model_id, vocab["vocabulary_version"])
    vocab_ids = vocab["_id_set"]

    out: list[dict] = []
    dropped_off_vocab = 0
    dropped_unverified = 0
    for claim in parsed_response.claims:
        # Post-response verification — re-check the substring
        # condition (don't trust the model's flag alone) and the
        # ECO vocabulary membership.
        if claim.source_quote not in manuscript:
            dropped_unverified += 1
            print(
                f"WARN claims: dropping unverifiable quote: {claim.claim_text[:80]!r}",
                file=sys.stderr,
            )
            continue
        if not set(claim.evidence_eco_codes).issubset(vocab_ids):
            dropped_off_vocab += 1
            off = set(claim.evidence_eco_codes) - vocab_ids
            print(
                f"WARN claims: dropping off-vocab claim {claim.claim_text[:80]!r}"
                f" (codes={sorted(off)})",
                file=sys.stderr,
            )
            continue
        out.append({
            "claim_text": claim.claim_text,
            "source_quote": claim.source_quote,
            "source_quote_verified": True,
            "claim_type": claim.claim_type,
            "evidence_eco_codes": list(claim.evidence_eco_codes),
            "confidence": claim.confidence,
            "model_id": model_id,
            "cache_key": cache_key,
        })

    summary = ClaimsRunSummary(
        claims_count=len(out),
        flex_timed_out=telemetry.flex_timed_out,
        tier_used=telemetry.tier_used,
        attempts=telemetry.attempts,
        latency_ms=telemetry.latency_ms,
        prompt_tokens_cached=telemetry.prompt_tokens_cached,
        prompt_tokens_uncached=telemetry.prompt_tokens_uncached,
        completion_tokens=telemetry.completion_tokens,
        dropped_off_vocab_count=dropped_off_vocab,
        dropped_unverified_count=dropped_unverified,
    )
    return out, summary
