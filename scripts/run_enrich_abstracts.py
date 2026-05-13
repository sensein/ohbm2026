#!/usr/bin/env python3
"""Stage 2 entry-point wrapper — enrich the accepted abstracts corpus
with figures, claims, and references.

Canonical invocation from a fresh repo:

    PYTHONPATH=src .venv/bin/python scripts/run_enrich_abstracts.py [options]

This wrapper exists so the README's Stage 2 section has a single
copy-pasteable invocation that does not depend on the `ohbmcli` entry
point's installation state. It forwards ``sys.argv[1:]`` to
``ohbm2026.enrich_stage.main`` and returns its exit code.

All flags + exit codes are documented in
``specs/003-enrich-abstracts/contracts/cli.md`` and exercised by
``tests/test_enrich_stage.py``.
"""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SRC_DIR = _REPO_ROOT / "src"
if _SRC_DIR.exists() and str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

from ohbm2026.enrich_stage import main  # noqa: E402  (post sys.path setup)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
