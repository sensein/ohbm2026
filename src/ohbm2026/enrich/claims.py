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

from ohbm2026.enrich import flex_tier as flex_tier
from ohbm2026 import enrichment as enrichment_module
from ohbm2026.exceptions import ContextLengthExceededError, EnrichmentError

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


# ----- JSON-schema helper --------------------------------------------


def _make_strict_schema(schema: dict) -> dict:
    """Coerce a Pydantic-derived JSON schema into the shape OpenAI's
    strict structured-output mode accepts.

    OpenAI strict mode requires:
    - `additionalProperties: false` on every object.
    - `required` listing EVERY property of every object (no
      optional fields — express absence via type unions with null).
    - No Pydantic-specific metadata keys (e.g., `title`).
    """
    import copy
    schema = copy.deepcopy(schema)

    def fix(node: Any) -> None:
        if isinstance(node, dict):
            # Strip metadata OpenAI doesn't accept.
            node.pop("title", None)
            if node.get("type") == "object" or "properties" in node:
                node.setdefault("additionalProperties", False)
                props = node.get("properties") or {}
                node["required"] = sorted(props.keys())
            for v in list(node.values()):
                fix(v)
            for key in ("$defs", "definitions"):
                if key in node:
                    for v in node[key].values():
                        fix(v)
        elif isinstance(node, list):
            for item in node:
                fix(item)

    fix(schema)
    return schema


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
    """One atomic factual claim.

    The first six fields are verbatim cllm `extract.txt` output
    shape (per project directive "don't deviate from cllm's
    approach"). The last two fields are Stage 2.1 augmentations:

    - `evidence_eco_codes`: optional ECO v1 annotation, additive
      to (not a mapping from) `evidence_type`. Empty list is
      allowed when no v1 code applies; off-vocab codes are
      filtered post-response but the claim is kept (FR-013).
    - `source_quote_verified`: bool the model sets to true ONLY
      after `verify_source_quote` tool returned is_substring=true.
      The orchestrator independently re-verifies before persisting.
    """

    # cllm fields (verbatim)
    claim: str = Field(..., min_length=1, description="Extracted atomic claim text.")
    claim_type: Literal["EXPLICIT", "IMPLICIT"] = Field(
        ..., description="EXPLICIT if directly stated; IMPLICIT if logically inferred."
    )
    source: str = Field(..., min_length=1, description="Exact source quote or figure reference from the manuscript.")
    source_type: list[Literal["TEXT", "IMAGE"]] = Field(
        ..., min_length=1, description="TEXT for direct quotes; IMAGE for figure/table references."
    )
    evidence: str = Field(..., min_length=1, description="Brief reasoning for the evidence_type assignment.")
    evidence_type: list[Literal["DATA", "CITATION", "KNOWLEDGE", "INFERENCE", "SPECULATION"]] = Field(
        ..., min_length=1, description="One or more cllm evidence categories supporting the claim."
    )

    # Stage 2.1 augmentations (additive — separate annotation, not a mapping from evidence_type)
    evidence_eco_codes: list[str] = Field(
        ...,
        description=(
            "Optional ECO v1 annotation, separate from cllm `evidence_type`. "
            "Each code MUST come from the embedded controlled vocabulary; "
            "if no ECO code in the v1 vocabulary applies, return an empty list."
        ),
    )
    source_quote_verified: bool = Field(
        ..., description="True iff the verify_source_quote tool returned is_substring=true for this `source`.",
    )


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
        "These codes are an OPTIONAL secondary annotation, independent of "
        "the cllm `evidence_type` list. For each claim, judge whether any "
        "of these top-9 ECO codes describe the evidence backing the claim. "
        "If one or more apply, list them in `evidence_eco_codes` (drawn "
        "ONLY from this list). If none apply, return an empty list — "
        "do NOT invent off-vocabulary codes, and do NOT drop the claim.",
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
    # Number of off-vocabulary ECO codes filtered out across all kept claims.
    # ECO codes are an additive annotation, not a gate — off-vocab codes are
    # stripped from the claim's `evidence_eco_codes` list but the claim is
    # otherwise kept.
    dropped_off_vocab_count: int = 0
    dropped_unverified_count: int = 0
    # Set to the fallback model id when the primary model raised
    # context_length_exceeded and the fallback succeeded.
    fallback_model_used: str | None = None


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
    """Build the claim-extraction system prompt.

    Base (verbatim) is OpenEvalProject/cllm's `extract.txt` — the
    project's canonical claim-vs-not-claim definition, evidence
    vocabulary, source-quote rules, and CORRECT/INCORRECT examples.
    Augmentations layered on top:

    1. Agentic four-step internal loop using the three function tools
       (verify_source_quote, lookup_eco_code, dedupe_check) for
       in-call self-correction.
    2. ECO controlled-vocabulary alignment — every claim must carry
       ≥1 ECO code in addition to its cllm `evidence_type`.
    3. Structured-output return shape (extended cllm schema with
       evidence_eco_codes + source_quote_verified fields).
    """
    cllm_base = (
        "You are a scientist who is an expert at identifying and "
        "extracting scientific claims. Your task is to accurately "
        "extract ALL atomic factual claims from a given scientific "
        "manuscript.\n\n"
        "NOTE: The manuscript may include figure interpretations and "
        "images that provide additional context and visual evidence. "
        "Consider both the text and any included figures when "
        "extracting claims.\n\n"
        "# Claim Extraction Guidelines\n"
        "An atomic factual claim is a single, discrete, factual "
        "statement that contains an assertion, the supporting "
        "evidence, and a source from the manuscript.\n\n"
        "## Definition: Atomic Factual Claim\n"
        "- Represents ONE specific assertion or assumption about "
        "the world\n"
        "- Can be assessed as supported or unsupported\n"
        "- Is indivisible—cannot be broken down into smaller "
        "factual units\n\n"
        "## Claim Types\n"
        "A claim may be explicit or implicit:\n"
        "- **EXPLICIT**: Clearly and directly stated in the manuscript\n"
        "- **IMPLICIT**: Inferred logically from the content, though "
        "not directly stated\n\n"
        "## Evidence\n"
        "Evidence is the data, citation, knowledge, inference, or "
        "speculation that justifies the claim.\n\n"
        "### Evidence Types (multiple may apply)\n"
        "- **DATA**: Supported by experimental data, measurements, "
        "or observations in the manuscript\n"
        "- **CITATION**: Supported by references to other scholarly work\n"
        "- **KNOWLEDGE**: Draws from established scientific "
        "consensus or knowledge\n"
        "- **INFERENCE**: Based on logical inference from presented "
        "information\n"
        "- **SPECULATION**: Involves hypothetical or speculative "
        "reasoning\n\n"
        "## Source\n"
        "The source is the origin of the claim within the manuscript. "
        "IMPORTANT: The extracted source text must match EXACTLY with "
        "the text in the manuscript, including all inline citations.\n\n"
        "Example of CORRECT extraction:\n"
        '"Specific responses to different types of green leaf volatiles '
        "have been reported both at physiological (Hansson et al., 1999; "
        "Røstelien et al., 2005) and behavioral levels (Reinecke et al., "
        '2005)"\n\n'
        "Example of INCORRECT extraction (missing citations):\n"
        '"Specific responses to different types of green leaf volatiles '
        "have been reported both at physiological and behavioral "
        'levels"\n\n'
        "The source field must preserve:\n"
        "- All author names and years in parentheses\n"
        "- All citation markers\n"
        "- The exact formatting and punctuation around citations\n\n"
        "Do NOT remove, paraphrase, or omit any citations from the "
        "extracted text.\n\n"
        "### Source Types (multiple may apply)\n"
        "- **TEXT**: Direct quote from the manuscript text\n"
        '- **IMAGE**: Reference to a figure, table, or image (e.g., '
        '"Figure 2A shows...")\n\n'
        "## Extraction Rules\n"
        "1. Extract ALL factual claims, including primary findings "
        "and secondary/supporting statements\n"
        "2. Each extracted claim must be fully self-contained and "
        "independently understandable\n"
        "3. Include the exact source (direct quote from manuscript "
        "or reference to figure/table/image)\n"
        "4. Specify source type(s): TEXT for text quotes, IMAGE for "
        "figure/table references\n"
        "5. Provide a brief explanation for each assigned evidence type\n"
        "6. DO NOT evaluate the truthfulness of claims, only assess "
        "whether the claim has supporting evidence of `evidence_type`.\n"
    )
    augmentations = (
        "\n# Stage 2.1 Augmentations (additive — do NOT relax the "
        "cllm rules above)\n\n"
        "## Agentic Internal Loop (use the function tools)\n"
        "For each candidate claim, before adding it to your final "
        "output:\n"
        "1. **VERIFY source** — call `verify_source_quote` with the "
        "candidate `claim` and `source`. If `is_substring=false` AND "
        "`candidate_corrections` is non-empty, use the best correction "
        "as `source` and re-verify. If still false after one correction, "
        "DROP the claim.\n"
        "2. **DEDUPE** — before emitting a claim, call `dedupe_check` "
        "against claims you've already accepted. Drop duplicates.\n"
        "3. **ECO annotation (optional, additive)** — independently of "
        "the cllm `evidence_type` you assigned, consider whether any "
        "of the ECO v1 codes below describe the evidence backing the "
        "claim. You MAY call `lookup_eco_code` to search the vocabulary "
        "by keyword. List every applicable in-vocabulary code in "
        "`evidence_eco_codes`. If none apply, return an empty list — "
        "do NOT drop the claim, and do NOT invent off-vocabulary "
        "codes. ECO codes are a separate annotation; they do NOT "
        "replace or override `evidence_type`.\n\n"
        "## Output Fields\n"
        "Each emitted claim must include the cllm fields "
        "(claim, claim_type, source, source_type, evidence, "
        "evidence_type) PLUS the Stage 2.1 augmentations "
        "(evidence_eco_codes, source_quote_verified).\n\n"
        "Set `source_quote_verified=true` ONLY after the verify tool "
        "returned `is_substring=true` for the final `source`.\n\n"
        f"{eco_primer}"
    )
    return cllm_base + augmentations


def _execute_agentic_loop(
    client: Any,
    *,
    model_id: str,
    manuscript: str,
    figure_interpretations_text: str,
    vocabulary: dict[str, Any],
    flex_enabled: bool,
    timeout_seconds: float,
    max_tool_iterations: int = 32,
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

    # Structured output: ClaimsResponse JSON schema enforced
    # server-side. Strict mode means missing required fields,
    # off-enum claim_type, or out-of-range confidence are
    # rejected by OpenAI before reaching our parser — matches
    # spec FR-012.
    claims_schema = ClaimsResponse.model_json_schema()
    text_format = {
        "format": {
            "type": "json_schema",
            "name": "claims_response",
            "strict": True,
            "schema": _make_strict_schema(claims_schema),
        }
    }

    def call(*, service_tier: str, timeout: float, current_input: list[dict]) -> Any:
        return client.responses.create(
            model=model_id,
            input=current_input,
            tools=tools,
            text=text_format,
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
    fallback_model_id: str | None = None,
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

    If `fallback_model_id` is supplied and the primary model raises
    `ContextLengthExceededError`, the agentic loop is re-run once
    with the fallback model. A successful fallback writes to a new
    cache slot keyed by the fallback model id.
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

    try:
        parsed_response, _raw_response, telemetry = _execute_agentic_loop(
            client,
            model_id=model_id,
            manuscript=manuscript,
            figure_interpretations_text=fi_text,
            vocabulary=vocab,
            flex_enabled=flex_enabled,
            timeout_seconds=timeout_seconds,
        )
        active_model_id = model_id
        fallback_used: str | None = None
    except ContextLengthExceededError:
        if not fallback_model_id or fallback_model_id == model_id:
            raise
        print(
            f"INFO claims: context_length_exceeded on {model_id} for abstract "
            f"{abstract.get('id')}; retrying with fallback model {fallback_model_id!r}",
            file=sys.stderr,
        )
        parsed_response, _raw_response, telemetry = _execute_agentic_loop(
            client,
            model_id=fallback_model_id,
            manuscript=manuscript,
            figure_interpretations_text=fi_text,
            vocabulary=vocab,
            flex_enabled=flex_enabled,
            timeout_seconds=timeout_seconds,
        )
        active_model_id = fallback_model_id
        fallback_used = fallback_model_id

    cache_key = _hash_for_cache(manuscript, active_model_id, vocab["vocabulary_version"])
    vocab_ids = vocab["_id_set"]

    out: list[dict] = []
    filtered_off_vocab_codes = 0
    dropped_unverified = 0
    for claim in parsed_response.claims:
        # Post-response verification: re-check the substring condition
        # (Principle VI — don't trust the model's flag alone). The
        # source quote MUST be present in the manuscript, else drop.
        if claim.source not in manuscript:
            dropped_unverified += 1
            print(
                f"WARN claims: dropping unverifiable quote: {claim.claim[:80]!r}",
                file=sys.stderr,
            )
            continue
        # ECO codes are an additive annotation, not a gate: filter
        # off-vocabulary codes from the list but KEEP the claim. An
        # empty result is allowed when no v1 code applies.
        kept_codes: list[str] = []
        off_codes: list[str] = []
        for code in claim.evidence_eco_codes:
            (kept_codes if code in vocab_ids else off_codes).append(code)
        if off_codes:
            filtered_off_vocab_codes += len(off_codes)
            print(
                f"WARN claims: filtering off-vocab ECO codes "
                f"{sorted(set(off_codes))} from claim {claim.claim[:80]!r}",
                file=sys.stderr,
            )
        out.append({
            "claim": claim.claim,
            "claim_type": claim.claim_type,
            "source": claim.source,
            "source_type": list(claim.source_type),
            "evidence": claim.evidence,
            "evidence_type": list(claim.evidence_type),
            "evidence_eco_codes": kept_codes,
            "source_quote_verified": True,
            "model_id": active_model_id,
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
        dropped_off_vocab_count=filtered_off_vocab_codes,
        dropped_unverified_count=dropped_unverified,
        fallback_model_used=fallback_used,
    )
    return out, summary
