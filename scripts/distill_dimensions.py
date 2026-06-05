#!/usr/bin/env python
"""Stage 23 — distill the bulky NeuroScape dimension analysis to the slim build input.

Reads the operator-supplied ``abstracts.detail.json`` (keyed by Oxford
submission id, carrying many analysis fields) and writes a slim
``dimensions.slim.json`` containing only the submission id + the four
research-classification dimension label lists per abstract. The slim file is
the input consumed by ``scripts/build_ui_data.py --dimensions ...``.

Both files are gitignored under ``data/inputs/neuroscape-dimensions/``; the
distiller is the reproducible source-of-record (re-run to regenerate the slim
file). See specs/023-atlas-research-dimensions/contracts/dimension-input.md.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="distill_dimensions.py",
        description="Reduce abstracts.detail.json to a slim {id + 4 dimensions} file.",
    )
    parser.add_argument("--in", dest="in_path", required=True, type=Path,
                        help="Full operator file (abstracts.detail.json).")
    parser.add_argument("--out", dest="out_path", required=True, type=Path,
                        help="Slim output (dimensions.slim.json).")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    from ohbm2026.ui_data.dimensions import DimensionInputError, distill_dimensions

    try:
        summary = distill_dimensions(args.in_path, args.out_path)
    except DimensionInputError as exc:
        print(f"distill_dimensions.py: {exc}", file=sys.stderr)
        return 3
    print(
        f"distill_dimensions: {summary['abstracts_out']}/{summary['abstracts_in']} "
        f"abstracts carry ≥1 dimension → {args.out_path}"
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
