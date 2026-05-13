#!/usr/bin/env python3
"""Stage 1 (withdrawn) entry-point wrapper — fetch the SEPARATE
withdrawn-decision corpus into ``data/primary/abstracts_withdrawn.json``
without mixing with the accepted corpus.

Canonical invocation:

    PYTHONPATH=src .venv/bin/python scripts/run_fetch_withdrawn.py [options]

Equivalent through ``ohbmcli``:

    PYTHONPATH=src .venv/bin/python -m ohbm2026.cli fetch-withdrawn [options]

This wrapper forces ``--corpus-kind=withdrawn`` so accepted and
withdrawn artifacts never share a state-key namespace.
"""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SRC_DIR = _REPO_ROOT / "src"
if _SRC_DIR.exists() and str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

from ohbm2026.fetch_stage import main  # noqa: E402  (post sys.path setup)


if __name__ == "__main__":
    argv = list(sys.argv[1:])
    if "--corpus-kind" not in argv:
        argv = argv + ["--corpus-kind", "withdrawn"]
    raise SystemExit(main(argv))
