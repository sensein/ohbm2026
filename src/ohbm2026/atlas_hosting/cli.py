"""CLI for Stage 20 — ``upload-atlas-package`` and ``compare-data-hosting``.

Spec: ``specs/020-cloudflare-r2-migration/`` —
``contracts/cli-upload-atlas-package.md`` +
``contracts/cli-compare-data-hosting.md``.

Each subcommand exposes a ``build_*_parser`` (the top-level ``ohbmcli``
copies its actions in) and a ``*_main`` argv entry point returning the
documented exit code. Typed Stage-20 failures map to distinct non-zero
codes; secrets are never echoed.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ohbm2026.exceptions import (
    ArtifactDiscoveryError,
    ContentHashMismatchError,
    R2CredentialsError,
    R2UploadError,
)

from . import r2_client, uploader

# Exit codes (contracts/cli-upload-atlas-package.md).
_UPLOAD_EXIT_CODES: dict[type[BaseException], int] = {
    R2CredentialsError: 2,
    ArtifactDiscoveryError: 3,
    ContentHashMismatchError: 4,
    R2UploadError: 5,
}


def build_upload_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ohbmcli upload-atlas-package",
        description=(
            "Upload a built atlas-package's parquets to Cloudflare R2 under "
            "content-addressed, immutable keys; emit a registry channel entry "
            "+ an upload manifest."
        ),
    )
    parser.add_argument(
        "--package-dir",
        type=Path,
        required=True,
        help=(
            "build-atlas-package --output-root: holds neuroscape.parquet, "
            "atlas.parquet, and neuroscape_vectors.parquet (all required)."
        ),
    )
    parser.add_argument(
        "--ohbm2026-parquet",
        type=Path,
        required=True,
        help=(
            "Path to ohbm2026.parquet (the Stage-10 build, separate from the "
            "atlas-package output; typically data/outputs/parquets/<key>/ohbm2026.parquet)."
        ),
    )
    parser.add_argument(
        "--env-file",
        type=Path,
        default=Path(".env"),
        help="File the R2 credentials are read from (default: .env).",
    )
    parser.add_argument(
        "--manifest-out",
        type=Path,
        default=Path(uploader.DEFAULT_MANIFEST_OUT),
        help="Directory for the upload manifest (default: data/provenance/).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Hash + existence-check + print the channel entry, but issue no PUT and write no manifest.",
    )
    return parser


def upload_main(argv: list[str] | None = None) -> int:
    parser = build_upload_parser()
    args = parser.parse_args(argv)

    command_line = " ".join(["ohbmcli", "upload-atlas-package", *(argv or sys.argv[1:])])

    try:
        settings = r2_client.load_settings(args.env_file)
        result = uploader.upload_atlas_package(
            args.package_dir,
            ohbm2026_parquet=args.ohbm2026_parquet,
            settings=settings,
            dry_run=args.dry_run,
            manifest_out=args.manifest_out,
            command_line=command_line,
        )
    except tuple(_UPLOAD_EXIT_CODES) as exc:  # type: ignore[misc]
        sys.stderr.write(f"upload-atlas-package: {type(exc).__name__}: {exc}\n")
        return _UPLOAD_EXIT_CODES[type(exc)]

    payload = {
        "channel_entry": result.channel_entry,
        "manifest_path": str(result.manifest_path) if result.manifest_path else None,
        "summary": result.summary,
        "dry_run": result.dry_run,
    }
    sys.stdout.write(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    return 0


# ``compare-data-hosting`` (US3) is wired in a later task.


if __name__ == "__main__":
    raise SystemExit(upload_main())
