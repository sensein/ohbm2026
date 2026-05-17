#!/usr/bin/env python
"""Stage 4 venv-only wrapper.

Mirror of `scripts/run_embed_matrix.py`. Operators run this directly
when they want the canonical Stage 4 matrix without going through
`ohbmcli`; downstream code paths are identical.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC = REPO_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from ohbm2026.analyze.stage import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
