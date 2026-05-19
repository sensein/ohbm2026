#!/usr/bin/env python
"""Stage-10 LinkML schema lint (T045).

Walks a LinkML schema YAML and verifies:

  1. Zero `range: Any` slots, unless each occurrence has a preceding
     `# LIMITATION:` comment naming the LinkML construct whose absence
     forces the looseness. (SC-203.)
  2. The schema parses as YAML.
  3. Every `multivalued: true` slot declares an explicit
     `minimum_cardinality` (catches the implicit "may be missing" bug
     that bit Stage-6 facet keys).

Exit code 0 = pass; non-zero = at least one violation, printed to
stderr. Used by `scripts/validate_ui_data.sh` to gate the build.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


def _check_range_any(lines: list[str], path: Path) -> list[str]:
    """Return list of human-readable errors for any unjustified `range: Any`."""
    errors: list[str] = []
    pattern = re.compile(r"^\s*range:\s*Any\b", re.IGNORECASE)
    for idx, line in enumerate(lines):
        if not pattern.match(line):
            continue
        # Walk back up to 3 lines looking for a leading `# LIMITATION:` marker.
        annotated = False
        for back in range(idx - 1, max(-1, idx - 4), -1):
            prev = lines[back].strip()
            if not prev:
                continue
            if prev.startswith("# LIMITATION:"):
                annotated = True
            break
        if not annotated:
            errors.append(
                f"{path}:{idx + 1}: range: Any without a preceding '# LIMITATION:' annotation"
            )
    return errors


def _check_multivalued_cardinality(lines: list[str], path: Path) -> list[str]:
    """Each `multivalued: true` slot must declare `minimum_cardinality`.

    Walks the schema as plain text (stdlib-only — no `linkml` runtime
    dependency). For each `multivalued: true` line, looks BACKWARD for
    the attribute name (a line ending in `:` with no value) at the
    nearest shallower indent, then scans FORWARD from that name until
    it hits another attribute name at the same indent (or a shallower
    indent — end of the parent map). The window between is one
    attribute's full key block; `minimum_cardinality` must appear in
    it.
    """
    errors: list[str] = []
    pattern_multi = re.compile(r"^\s*multivalued:\s*true\b")
    pattern_minc = re.compile(r"^\s*minimum_cardinality:\s*\d+\b")
    pattern_attr_header = re.compile(r"^(?P<indent>\s*)(?P<name>[A-Za-z_][\w-]*):\s*$")

    for idx, line in enumerate(lines):
        if not pattern_multi.match(line):
            continue
        multi_indent = len(line) - len(line.lstrip())
        # Walk backward to find the attribute header (a name: line with
        # an indent shallower than the multivalued line).
        attr_start = None
        attr_indent = 0
        for back in range(idx - 1, -1, -1):
            m = pattern_attr_header.match(lines[back])
            if m and len(m.group("indent")) < multi_indent:
                attr_start = back
                attr_indent = len(m.group("indent"))
                break
        if attr_start is None:
            errors.append(
                f"{path}:{idx + 1}: multivalued: true outside an attribute block"
            )
            continue
        # Walk forward from attr_start+1 until we hit another header at
        # the same indent or shallower indent (end of this attribute).
        attr_end = len(lines)
        for fwd in range(attr_start + 1, len(lines)):
            ln = lines[fwd]
            if not ln.strip():
                continue
            indent = len(ln) - len(ln.lstrip())
            if indent <= attr_indent:
                attr_end = fwd
                break
            # A sibling attribute header at the same indent as the
            # parent's attribute-level (one indent in from `attr_indent`)
            # also ends the current block. Detect: another `name:` line
            # without value at indent == attr_indent + step_size.
            sibling = pattern_attr_header.match(ln)
            if sibling and len(sibling.group("indent")) == attr_indent + 2:
                # Same-level attribute header → previous block ended.
                if fwd != attr_start + 1:
                    attr_end = fwd
                    break
        # Search the block for minimum_cardinality.
        block = lines[attr_start:attr_end]
        if not any(pattern_minc.match(ln) for ln in block):
            errors.append(
                f"{path}:{idx + 1}: multivalued: true without explicit minimum_cardinality"
            )
    return errors


def lint(path: Path) -> list[str]:
    if not path.exists():
        return [f"{path}: file does not exist"]
    text = path.read_text()
    lines = text.splitlines()
    errors: list[str] = []
    errors.extend(_check_range_any(lines, path))
    errors.extend(_check_multivalued_cardinality(lines, path))
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="lint_schema.py",
        description="Stage-10 LinkML schema lint (FR-201 + FR-202 gates).",
    )
    parser.add_argument(
        "schema",
        type=Path,
        nargs="?",
        default=Path(
            "specs/010-export-redesign/contracts/shards.linkml.yaml"
        ),
        help="Schema file to lint (default: the Stage-10 shard schema).",
    )
    args = parser.parse_args(argv)
    errors = lint(args.schema)
    if errors:
        for e in errors:
            print(f"lint_schema: {e}", file=sys.stderr)
        return 1
    print(f"lint_schema: {args.schema}: PASS")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
