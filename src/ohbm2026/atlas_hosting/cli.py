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

from ohbm2026.artifacts import utc_now_isoformat
from ohbm2026.exceptions import (
    ArtifactDiscoveryError,
    ContentHashMismatchError,
    HostingComparisonError,
    R2CredentialsError,
    R2UploadError,
)

from . import compare, r2_client, uploader

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


def build_compare_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ohbmcli compare-data-hosting",
        description=(
            "Probe the Dropbox- and R2-served copies of each artifact for "
            "byte-parity, HTTP Range support, and CORS; write a pass/fail report."
        ),
    )
    parser.add_argument(
        "--registry",
        type=Path,
        required=True,
        help="JSON registry (value of OHBM2026_UI_DATA_PACKAGE_URLS); local only, never committed.",
    )
    parser.add_argument("--dropbox-channel", required=True, help="Channel key on the Dropbox side.")
    parser.add_argument("--r2-channel", required=True, help="Channel key on the R2 side.")
    parser.add_argument(
        "--origin",
        required=True,
        help="Origin used in the CORS probe (the production site origin).",
    )
    parser.add_argument(
        "--report-out",
        type=Path,
        default=Path("data/outputs"),
        help="Directory for the comparison report (default: data/outputs/).",
    )
    parser.add_argument(
        "--trust-recorded-sha256",
        action="store_true",
        help="Skip downloads; compare each channel's recorded sha256 instead of re-hashing bytes.",
    )
    parser.add_argument("--range-bytes", type=int, default=100, help="Range probe window size.")
    return parser


def _load_channel(registry: dict, key: str) -> dict:
    channel = registry.get(key)
    if not isinstance(channel, dict):
        raise HostingComparisonError(
            f"channel {key!r} not found in registry",
            probe="channel",
            reason="unknown_channel",
        )
    return channel


def compare_main(argv: list[str] | None = None) -> int:
    parser = build_compare_parser()
    args = parser.parse_args(argv)

    try:
        registry = json.loads(Path(args.registry).read_text())
        report = compare.compare_channels(
            dropbox_channel=_load_channel(registry, args.dropbox_channel),
            r2_channel=_load_channel(registry, args.r2_channel),
            origin=args.origin,
            generated_utc=utc_now_isoformat(),
            dropbox_channel_key=args.dropbox_channel,
            r2_channel_key=args.r2_channel,
            range_bytes=args.range_bytes,
            trust_recorded_sha256=args.trust_recorded_sha256,
        )
    except HostingComparisonError as exc:
        sys.stderr.write(f"compare-data-hosting: {type(exc).__name__}: {exc}\n")
        return 2

    out_dir = Path(args.report_out)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = utc_now_isoformat().replace(":", "").replace("-", "").split(".")[0] + "Z"
    out_path = out_dir / f"data-hosting-comparison__{stamp}.json"
    out_path.write_text(json.dumps(report.to_dict(), indent=2, sort_keys=True))

    for art in report.artifacts:
        mark = lambda ok: "✓" if ok else "✗"  # noqa: E731
        sys.stdout.write(
            f"{art.logical_name:18s} parity {mark(art.byte_parity)}  "
            f"range {mark(art.r2.range_supported)}  cors {mark(art.r2.cors_allowed)}  "
            f"=> {'PASS' if art.passed else 'FAIL'}\n"
        )
    sys.stdout.write(f"report: {out_path}\noverall: {'PASS' if report.overall_pass else 'FAIL'}\n")
    return 0 if report.overall_pass else 1


if __name__ == "__main__":
    raise SystemExit(upload_main())
