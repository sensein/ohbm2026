#!/usr/bin/env python3
"""Stage 1 entry-point wrapper — fetch OHBM 2026 abstracts + persist
the upstream GraphQL schema introspection.

Canonical invocation from a fresh repo:

    PYTHONPATH=src .venv/bin/python scripts/run_fetch_abstracts.py [options]

This wrapper exists so the README's Stage 1 section has a single
copy-pasteable invocation that does not depend on the `ohbmcli` entry
point's installation state. It forwards ``sys.argv[1:]`` to
``ohbm2026.fetch.stage.main`` and returns its exit code.

All flags + exit codes are documented in
``specs/002-rewire-pipeline/contracts/cli.md`` and exercised by
``tests/test_fetch_stage.py``.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Make `src/ohbm2026` importable when this script is invoked without
# `PYTHONPATH=src` set. We prepend the repo's `src/` directory so the
# wrapper works in both invocation styles documented in the README.
_REPO_ROOT = Path(__file__).resolve().parent.parent
_SRC_DIR = _REPO_ROOT / "src"
if _SRC_DIR.exists() and str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

from ohbm2026.fetch.stage import main  # noqa: E402  (post sys.path setup)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
