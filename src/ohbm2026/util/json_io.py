"""Canonical JSON load/write helpers shared across the pipeline.

Consolidates ~10 identical `load_json` / `write_json` definitions that
were scattered across `titles.py`, `category_evaluation.py`,
`category_rollup.py`, `ui/payload.py`, `enrich/openalex.py`,
`analyze/storage.py`, and others.

Stable contract: `write_json` is NOT atomic — it does a plain
`path.write_text(...)`. Callers that need atomic temp-then-rename
semantics keep their own helper.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
