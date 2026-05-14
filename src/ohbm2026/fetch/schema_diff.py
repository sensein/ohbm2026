"""Schema-drift classification for Stage 1 (fetch-abstracts).

Pure functions only — no I/O. Implements the tiered HARD / SOFT /
INFORMATIONAL classification model defined in FR-003:

  - HARD CONTRACT: fields the live GraphQL fetch query body asks for.
    Drift here BLOCKS Stage 1.
  - SOFT CONTRACT: fields any `src/ohbm2026/` module reads from
    `data/primary/abstracts.json`. Drift here is recorded with a
    `DOWNSTREAM IMPACT` tag; Stage 1 still completes.
  - INFORMATIONAL: everything else; recorded for visibility only.

The HARD set is derived at runtime from the query body via a minimal
recursive AST walker. The SOFT set is derived at runtime by importing
consuming modules and unioning their `CONSUMED_ABSTRACT_FIELDS`
frozensets of `(GraphQLTypeName, FieldName)` pairs.

This module is the canonical reference instance of Principle VII
("discover external state, don't hardcode it") applied to a GraphQL
fetch boundary. See specs/002-rewire-pipeline/research.md §4-§5.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import re
from typing import Iterable, Mapping

__all__ = [
    "FieldIndexEntry",
    "SchemaDiffEntry",
    "flatten_introspection",
    "hash_field_index",
    "parse_hard_set_from_queries",
    "collect_soft_contract_fields",
    "compare",
]


@dataclasses.dataclass(frozen=True)
class FieldIndexEntry:
    """Flattened, normalized representation of one field on one type.

    Two introspection results that describe the same schema MUST
    produce equal FieldIndexEntry sets so `hash_field_index` is stable
    across JSON-serialization variations.
    """

    type_name: str
    field_name: str
    wrapping_kinds: tuple[str, ...]
    named_type: str
    args_signature: str

    def to_dict(self) -> dict[str, object]:
        return {
            "type_name": self.type_name,
            "field_name": self.field_name,
            "wrapping_kinds": list(self.wrapping_kinds),
            "named_type": self.named_type,
            "args_signature": self.args_signature,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> "FieldIndexEntry":
        return cls(
            type_name=str(payload["type_name"]),
            field_name=str(payload["field_name"]),
            wrapping_kinds=tuple(payload.get("wrapping_kinds") or ()),
            named_type=str(payload["named_type"]),
            args_signature=str(payload.get("args_signature", "")),
        )


@dataclasses.dataclass(frozen=True)
class SchemaDiffEntry:
    """One delta between two schema versions. Tier classification per
    FR-003. The `previous`/`current` payloads carry the
    FieldIndexEntry-as-dict so error messages can quote both shapes."""

    tier: str  # "HARD" | "SOFT" | "INFORMATIONAL"
    change_kind: str  # "added" | "removed" | "type_changed" | "args_changed"
    type_name: str
    field_name: str
    previous: dict | None
    current: dict | None
    downstream_consumers: list[str]


# ── flatten_introspection ─────────────────────────────────────────────


def _unwrap(type_ref: Mapping[str, object] | None) -> tuple[tuple[str, ...], str]:
    """Walk a GraphQL type reference, peeling off NON_NULL / LIST
    wrappers, and return (wrapping_kinds, named_type)."""
    wrapping: list[str] = []
    cur: Mapping[str, object] | None = type_ref or {}
    while cur and cur.get("kind") in {"NON_NULL", "LIST"} and not cur.get("name"):
        wrapping.append(str(cur["kind"]))
        cur = cur.get("ofType")  # type: ignore[assignment]
    named = str(((cur or {}).get("name")) or "")
    return tuple(wrapping), named


def _args_signature(args: Iterable[Mapping[str, object]] | None) -> str:
    if not args:
        return ""
    parts: list[str] = []
    for arg in sorted(args, key=lambda a: str(a.get("name", ""))):
        name = str(arg.get("name") or "")
        wrapping, named = _unwrap(arg.get("type"))
        wrap_repr = "".join("!" if w == "NON_NULL" else "[]" for w in wrapping)
        parts.append(f"{name}:{wrap_repr}{named}")
    return "(" + ",".join(parts) + ")"


def flatten_introspection(introspection_raw: Mapping[str, object]) -> list[FieldIndexEntry]:
    """Flatten a GraphQL introspection `__schema` block into a sorted
    list of `FieldIndexEntry`. Skips meta types whose names start with
    `__`."""
    entries: list[FieldIndexEntry] = []
    for t in introspection_raw.get("types", []) or []:
        type_name = str(t.get("name") or "")
        if not type_name or type_name.startswith("__"):
            continue
        for field in (t.get("fields") or []):
            field_name = str(field.get("name") or "")
            if not field_name:
                continue
            wrapping, named = _unwrap(field.get("type"))
            entries.append(
                FieldIndexEntry(
                    type_name=type_name,
                    field_name=field_name,
                    wrapping_kinds=wrapping,
                    named_type=named,
                    args_signature=_args_signature(field.get("args")),
                )
            )
    entries.sort(key=lambda e: (e.type_name, e.field_name))
    return entries


# ── hash_field_index ─────────────────────────────────────────────────


def hash_field_index(entries: Iterable[FieldIndexEntry]) -> str:
    """SHA-256 over the sorted, normalized field-index view. Two equal
    schemas always produce the same hash; any field change changes the
    hash."""
    normalized = sorted(
        (e.to_dict() for e in entries),
        key=lambda e: (e["type_name"], e["field_name"]),
    )
    payload = json.dumps(normalized, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# ── parse_hard_set_from_queries ──────────────────────────────────────


_COMMENT_RE = re.compile(r"#[^\n]*")
_IDENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def parse_hard_set_from_queries(*query_texts: str) -> set[tuple[str, str]]:
    """Minimal recursive AST walker over GraphQL query bodies.

    Records `(parent, child)` field pairs from selection sets. The
    top-level operation's selection set is parented to `"Query"`.
    Nested selections record the immediate parent field as the bucket
    (we don't have type info from the query alone — the introspection
    + compare loop is what reconciles these against typed entries).
    Argument blocks (`(...)`) are skipped entirely.

    Intentionally limited to the form our fetch queries use: named
    fields with optional argument lists and nested selection sets, no
    inline fragments, no directives, no aliases.
    """
    result: set[tuple[str, str]] = set()
    for query in query_texts:
        _walk_query(query, result)
    return result


def _walk_query(query: str, result: set[tuple[str, str]]) -> None:
    query = _COMMENT_RE.sub("", query)
    parent_stack: list[str] = ["Query"]
    started = False
    paren_depth = 0
    i = 0
    n = len(query)

    while i < n:
        ch = query[i]

        if ch == "(":
            paren_depth += 1
            i += 1
            continue
        if ch == ")":
            paren_depth -= 1
            i += 1
            continue
        if paren_depth > 0:
            i += 1
            continue

        if ch == "{":
            started = True
            i += 1
            continue
        if ch == "}":
            if len(parent_stack) > 1:
                parent_stack.pop()
            i += 1
            continue

        if ch.isalpha() or ch == "_":
            match = _IDENT_RE.match(query, i)
            ident = match.group(0) if match else ""
            i = match.end() if match else i + 1

            if not started:
                continue

            parent = parent_stack[-1]
            result.add((parent, ident))

            # Look ahead past whitespace; consume an optional argument
            # block; then decide if a sub-selection set follows.
            k = i
            while k < n and query[k] in " \t\n\r":
                k += 1
            if k < n and query[k] == "(":
                depth = 1
                k += 1
                while k < n and depth > 0:
                    if query[k] == "(":
                        depth += 1
                    elif query[k] == ")":
                        depth -= 1
                    k += 1
                while k < n and query[k] in " \t\n\r":
                    k += 1

            if k < n and query[k] == "{":
                parent_stack.append(ident)
                i = k + 1
            else:
                i = k
            continue

        i += 1


# ── collect_soft_contract_fields ─────────────────────────────────────


def collect_soft_contract_fields(modules: Iterable[object]) -> dict[tuple[str, str], list[str]]:
    """Union `CONSUMED_ABSTRACT_FIELDS` across the given modules.

    Returns `{(type_name, field_name): [module_name, ...]}`. Modules
    that do not declare `CONSUMED_ABSTRACT_FIELDS` are skipped silently.
    Module names within each list are sorted to keep the output stable
    across import-order variations.
    """
    out: dict[tuple[str, str], list[str]] = {}
    for mod in modules:
        consumed = getattr(mod, "CONSUMED_ABSTRACT_FIELDS", None)
        if consumed is None:
            continue
        mod_name = getattr(mod, "__name__", str(mod))
        for entry in consumed:
            key = tuple(entry)  # type: ignore[assignment]
            if len(key) != 2:
                raise ValueError(
                    f"{mod_name}.CONSUMED_ABSTRACT_FIELDS entries must be "
                    f"(type_name, field_name) tuples; got {entry!r}"
                )
            out.setdefault(key, []).append(mod_name)
    for key in out:
        out[key].sort()
    return out


# ── compare ──────────────────────────────────────────────────────────


def compare(
    previous: Iterable[FieldIndexEntry],
    current: Iterable[FieldIndexEntry],
    *,
    hard_set: set[tuple[str, str]],
    soft_set: Mapping[tuple[str, str], list[str]],
) -> list[SchemaDiffEntry]:
    """Compare two field-index views and classify each delta.

    Tier precedence: HARD > SOFT > INFORMATIONAL. A field in BOTH the
    HARD and SOFT sets is classified HARD; its `downstream_consumers`
    list is still populated so operators see both signals (spec edge
    case).
    """
    prev_by_key = {(e.type_name, e.field_name): e for e in previous}
    curr_by_key = {(e.type_name, e.field_name): e for e in current}
    diffs: list[SchemaDiffEntry] = []

    for key in sorted(set(prev_by_key) | set(curr_by_key)):
        prev = prev_by_key.get(key)
        curr = curr_by_key.get(key)
        change_kind = _change_kind(prev, curr)
        if change_kind is None:
            continue

        if key in hard_set:
            tier = "HARD"
        elif key in soft_set:
            tier = "SOFT"
        else:
            tier = "INFORMATIONAL"

        downstream = list(soft_set.get(key, []))

        diffs.append(
            SchemaDiffEntry(
                tier=tier,
                change_kind=change_kind,
                type_name=key[0],
                field_name=key[1],
                previous=prev.to_dict() if prev else None,
                current=curr.to_dict() if curr else None,
                downstream_consumers=downstream,
            )
        )

    return diffs


def _change_kind(prev: FieldIndexEntry | None, curr: FieldIndexEntry | None) -> str | None:
    if prev is None and curr is None:
        return None
    if prev is None:
        return "added"
    if curr is None:
        return "removed"
    if prev.named_type != curr.named_type or prev.wrapping_kinds != curr.wrapping_kinds:
        return "type_changed"
    if prev.args_signature != curr.args_signature:
        return "args_changed"
    return None
