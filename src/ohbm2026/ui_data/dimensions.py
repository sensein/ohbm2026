"""Stage 23 — research-classification dimensions (spec 023).

Four externally-computed categorical dimensions (Mario's NeuroScape dimension
analysis) are surfaced in the ``/ohbm2026/`` atlas as computed insights +
filterable facets. This module owns:

- the canonical dimension keys + display labels (single source of truth on the
  Python side; mirrored in ``site/src/lib/facets.ts``);
- ``distill_dimensions`` — reduce the bulky operator ``abstracts.detail.json``
  to a slim ``dimensions.slim.json`` (id + four label lists only);
- ``load_research_dimensions`` — read the slim file into a join map;
- ``compute_dimension_coverage`` — the provenance/coverage block.

Per the constitution: external layout is discovered at runtime and mismatches
raise the typed ``DimensionInputError`` (never a silent skip); the slim file is
a gitignored, regenerable artifact.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from ohbm2026.ui_data.state_key import Stage6BuildError

__all__ = [
    "DIMENSION_KEYS",
    "DIMENSION_LABELS",
    "DimensionInputError",
    "SLIM_SCHEMA_VERSION",
    "compute_dimension_coverage",
    "distill_dimensions",
    "load_research_dimensions",
]

# Canonical keys + human-readable labels for the four dimensions. Order is the
# display/iteration order. Mirrored in the site's facets.ts constants.
DIMENSION_KEYS: tuple[str, ...] = (
    "focus",
    "research_modality",
    "theory_scope",
    "epistemic_basis",
)

DIMENSION_LABELS: Mapping[str, str] = {
    "focus": "Focus",
    "research_modality": "Research modality",
    "theory_scope": "Theory scope",
    "epistemic_basis": "Epistemic basis",
}

SLIM_SCHEMA_VERSION = "dimensions.slim.v1"


class DimensionInputError(Stage6BuildError):
    """Raised when the dimension input (full or slim) is missing, unreadable,
    or doesn't match the expected layout discovered at runtime."""


def _load_json(path: Path, *, what: str) -> Any:
    p = Path(path)
    if not p.exists():
        raise DimensionInputError(f"{what} not found: {p}")
    try:
        with p.open() as fh:
            return json.load(fh)
    except (OSError, ValueError) as exc:
        raise DimensionInputError(f"{what} unreadable/not valid JSON: {p}: {exc}") from exc


def _clean_label_list(value: Any) -> list[str]:
    """De-duplicate + strip a dimension's label list; non-list ⇒ error upstream."""

    out: list[str] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, str):
            raise DimensionInputError(
                f"dimension label is not a string: {item!r}"
            )
        label = item.strip()
        if not label or label in seen:
            continue
        seen.add(label)
        out.append(label)
    return out


def _records_from_full(payload: Any) -> dict[str, dict[str, Any]]:
    """Discover the ``{submission_id: record}`` map in the full detail file.

    Accepts either ``{"abstracts": {id: record}}`` (canonical) or a bare
    ``{id: record}`` object. Raises on anything else.
    """

    if isinstance(payload, Mapping) and isinstance(payload.get("abstracts"), Mapping):
        records = payload["abstracts"]
    elif isinstance(payload, Mapping) and "abstracts" not in payload:
        records = payload
    else:
        raise DimensionInputError(
            "full dimension file must be an object keyed by submission id "
            "(optionally under an 'abstracts' map); got "
            f"{type(payload).__name__}"
        )
    if not all(isinstance(v, Mapping) for v in records.values()):
        raise DimensionInputError(
            "full dimension file records must be objects keyed by submission id"
        )
    return dict(records)


def distill_dimensions(full_path: Path, slim_path: Path) -> dict[str, Any]:
    """Reduce the full ``abstracts.detail.json`` to the slim build input.

    Keeps, per abstract, only the submission id + the four dimension label
    lists; drops every other field. Abstracts whose four dimensions are all
    empty are omitted. Output is deterministic (``sort_keys=True``). Raises
    ``DimensionInputError`` if the source isn't the expected layout or carries
    none of the four dimension fields on any record.

    Returns a small summary ``{abstracts_in, abstracts_out}``.
    """

    payload = _load_json(full_path, what="full dimension file")
    records = _records_from_full(payload)

    saw_any_dimension_field = False
    slim: dict[str, dict[str, list[str]]] = {}
    for sid, rec in records.items():
        present = [k for k in DIMENSION_KEYS if k in rec]
        if present:
            saw_any_dimension_field = True
        cleaned: dict[str, list[str]] = {}
        for key in DIMENSION_KEYS:
            raw = rec.get(key, [])
            if raw is None:
                raw = []
            if not isinstance(raw, list):
                raise DimensionInputError(
                    f"submission {sid}: dimension {key!r} must be a list, got "
                    f"{type(raw).__name__}"
                )
            cleaned[key] = _clean_label_list(raw)
        if any(cleaned[k] for k in DIMENSION_KEYS):
            slim[str(sid)] = cleaned

    if not saw_any_dimension_field:
        raise DimensionInputError(
            "no record in the full dimension file carries any of the expected "
            f"dimension fields {DIMENSION_KEYS}; this is not a dimension file"
        )

    out_payload = {"schema_version": SLIM_SCHEMA_VERSION, "dimensions": slim}
    out = Path(slim_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w") as fh:
        json.dump(out_payload, fh, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        fh.write("\n")
    return {"abstracts_in": len(records), "abstracts_out": len(slim)}


def load_research_dimensions(path: Path) -> dict[int, dict[str, list[str]]]:
    """Read the slim dimensions file into ``{submission_id: {dim_key: [labels]}}``.

    Restricts to ``DIMENSION_KEYS``, de-dups + strips labels, coerces id→int.
    Raises ``DimensionInputError`` on missing/unreadable/malformed input.
    """

    payload = _load_json(path, what="slim dimensions file")
    if not isinstance(payload, Mapping) or not isinstance(payload.get("dimensions"), Mapping):
        raise DimensionInputError(
            "slim dimensions file must be an object with a 'dimensions' map "
            f"({SLIM_SCHEMA_VERSION}); got {type(payload).__name__}"
        )
    out: dict[int, dict[str, list[str]]] = {}
    for sid, rec in payload["dimensions"].items():
        try:
            sid_int = int(sid)
        except (TypeError, ValueError) as exc:
            raise DimensionInputError(
                f"slim dimensions file key is not a submission id: {sid!r}"
            ) from exc
        if not isinstance(rec, Mapping):
            raise DimensionInputError(
                f"slim dimensions entry for {sid!r} must be an object, got "
                f"{type(rec).__name__}"
            )
        cleaned: dict[str, list[str]] = {}
        for key in DIMENSION_KEYS:
            raw = rec.get(key, [])
            if raw is None:
                raw = []
            if not isinstance(raw, list):
                raise DimensionInputError(
                    f"submission {sid}: dimension {key!r} must be a list, got "
                    f"{type(raw).__name__}"
                )
            cleaned[key] = _clean_label_list(raw)
        out[sid_int] = cleaned
    return out


def compute_dimension_coverage(
    dimensions: Mapping[int, Mapping[str, list[str]]],
    exported_submission_ids: Iterable[int],
    *,
    source_file: str,
    source_sha256: str,
) -> dict[str, Any]:
    """Build the machine-readable coverage/provenance block (data-model §3).

    ``matched`` = exported abstracts with ≥1 label for the dimension;
    ``no_value`` = exported abstracts with no label for it (``matched +
    no_value == len(exported)`` per dimension). ``unmatched_in_file`` = slim
    entries whose submission id is not in the export (FR-012).
    """

    exported = list(exported_submission_ids)
    exported_set = set(exported)
    per_dim: dict[str, dict[str, int]] = {}
    for key in DIMENSION_KEYS:
        matched = 0
        for sid in exported:
            labels = dimensions.get(sid, {}).get(key) or []
            if labels:
                matched += 1
        per_dim[key] = {"matched": matched, "no_value": len(exported) - matched}
    unmatched = sum(1 for sid in dimensions if sid not in exported_set)
    return {
        "source_file": source_file,
        "source_sha256": source_sha256,
        "dimensions": per_dim,
        "unmatched_in_file": unmatched,
    }
