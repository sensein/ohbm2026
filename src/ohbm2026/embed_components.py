"""Stage 3 component-text assembler.

Pure functions that read an enriched-abstract record and return the
canonical string for one named component (`title`, `introduction`,
`methods`, `results`, `conclusion`, `claims`, `inference_claims`).
No I/O; the orchestrator handles SQLite reads and feeds dicts in.

The component recipes are documented in
`specs/005-embeddings-matrix/data-model.md` §1.
"""

from __future__ import annotations

import re
from typing import Any, Iterable

from ohbm2026 import enrichment as enrichment_module

__all__ = [
    "DEFAULT_COMPONENTS",
    "PARTIAL_COMPONENTS",
    "ALL_COMPONENTS",
    "assemble_component",
    "assemble_all_components",
    "abstract_has_component",
]


DEFAULT_COMPONENTS: tuple[str, ...] = (
    "title",
    "introduction",
    "methods",
    "results",
    "conclusion",
    "claims",
)
PARTIAL_COMPONENTS: tuple[str, ...] = ("inference_claims",)
ALL_COMPONENTS: tuple[str, ...] = DEFAULT_COMPONENTS + PARTIAL_COMPONENTS

_PROSE_COMPONENTS = {"introduction", "methods", "results", "conclusion"}
_WHITESPACE_RE = re.compile(r"\s+")


def _normalize_whitespace(value: str) -> str:
    return _WHITESPACE_RE.sub(" ", (value or "")).strip()


def _section_text(record: dict, component: str) -> str:
    """Return the prose text for a section component.

    Pulls from `record["responses"]` matching `question_name` to the
    requested component (case-insensitive). Runs Stage 2's HTML →
    markdown conversion so that downstream embeddings see plain
    text, not raw HTML.
    """
    target = component.strip().lower()
    for response in record.get("responses") or []:
        name = (response.get("question_name") or "").strip().lower()
        if name == target:
            value = response.get("value") or ""
            if not value.strip():
                return ""
            # The enrichment helper already handles HTML→markdown for
            # Oxford Abstracts payloads; reuse it for consistency
            # across stages.
            markdown = enrichment_module.html_to_markdown(value)
            return _normalize_whitespace(markdown)
    return ""


def _claims_text(record: dict, *, filter_implicit: bool = False) -> str:
    claims: Iterable[dict] = record.get("claims") or []
    chunks: list[str] = []
    for claim in claims:
        if filter_implicit and claim.get("claim_type") != "IMPLICIT":
            continue
        text = (claim.get("claim") or "").strip()
        if text:
            chunks.append(text)
    return "\n\n".join(chunks)


def assemble_component(record: dict, component: str) -> str:
    """Assemble the canonical text for one component of one abstract.

    Returns an empty string when the abstract lacks content for the
    requested component (e.g., the introduction section is missing
    or the IMPLICIT-only claims list is empty). The orchestrator
    treats an empty result as "this abstract is absent from this
    component's bundle".

    Raises `ValueError` if the component name is not recognized.
    """
    if component == "title":
        return _normalize_whitespace(record.get("title") or "")
    if component in _PROSE_COMPONENTS:
        return _section_text(record, component)
    if component == "claims":
        return _claims_text(record)
    if component == "inference_claims":
        return _claims_text(record, filter_implicit=True)
    raise ValueError(f"unknown component {component!r}")


def assemble_all_components(
    record: dict, components: Iterable[str]
) -> dict[str, str]:
    """Convenience wrapper: assemble every requested component for one
    record in one pass. Useful when the orchestrator wants to
    materialize the text matrix up front."""
    return {comp: assemble_component(record, comp) for comp in components}


def abstract_has_component(record: dict, component: str) -> bool:
    """True iff `assemble_component(record, component)` would return a
    non-empty string. Cheap probe used by the coverage gate."""
    return bool(assemble_component(record, component))
