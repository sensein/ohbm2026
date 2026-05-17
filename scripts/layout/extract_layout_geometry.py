from __future__ import annotations

import argparse
import json
from pathlib import Path

from ohbm2026.layout.poster_layout import _default_layout_geometry_payload


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Write the checked-in poster board geometry artifact")
    parser.add_argument(
        "--output",
        default="data/poster_layout/layout_assets/layout_geometry.json",
        help="Path to the output geometry JSON",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = _default_layout_geometry_payload()
    output_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
