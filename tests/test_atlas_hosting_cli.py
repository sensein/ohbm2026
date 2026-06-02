"""Tests for the Stage 20 CLI surface + top-level dispatch.

Spec: ``specs/020-cloudflare-r2-migration/`` —
``contracts/cli-upload-atlas-package.md`` (+ compare in US3).
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from ohbm2026 import cli as top_cli
from ohbm2026.atlas_hosting import cli as hosting_cli
from ohbm2026.atlas_hosting.compare import (
    ArtifactComparison,
    CacheProbe,
    ComparisonReport,
    EndpointProbe,
)


def _report(cache_effective):
    ep = EndpointProbe(
        url="https://r2/o.parquet",
        reachable=True,
        sha256="a",
        status=200,
        range_supported=True,
        cors_allowed=True,
        revalidation_cors=True,
        latency_ms=1.0,
        error=None,
    )
    cp = CacheProbe(
        url="https://r2/o.parquet",
        kind="full",
        cf_cache_status="DYNAMIC" if cache_effective is False else "HIT",
        age=None,
        cache_control="public, max-age=31536000, immutable",
        cached=cache_effective is True,
        warmed=False,
        cold_ms=1.0,
        warm_ms=1.0,
        range_byte_parity=None,
        flag=None if cache_effective else "not edge-cached",
    )
    art = ArtifactComparison("ohbm2026", ep, ep, True, True, [cp])
    return ComparisonReport(
        generated_utc="2026-06-02T00:00:00+00:00",
        origin="https://abstractatlas.brainkb.org",
        dropbox_channel="d",
        r2_channel="r",
        artifacts=[art],
        overall_pass=True,
        cache_effective=cache_effective,
    )


class UploadParserTests(unittest.TestCase):
    def test_package_dir_required(self) -> None:
        parser = hosting_cli.build_upload_parser()
        with self.assertRaises(SystemExit):
            parser.parse_args([])

    def test_ohbm2026_parquet_required(self) -> None:
        parser = hosting_cli.build_upload_parser()
        with self.assertRaises(SystemExit):
            parser.parse_args(["--package-dir", "data/outputs/atlas-package__x"])

    def test_parses_dry_run_and_defaults(self) -> None:
        parser = hosting_cli.build_upload_parser()
        args = parser.parse_args(
            [
                "--package-dir",
                "data/outputs/atlas-package__x",
                "--ohbm2026-parquet",
                "data/outputs/parquets/abc/ohbm2026.parquet",
                "--dry-run",
            ]
        )
        self.assertTrue(args.dry_run)
        self.assertEqual(str(args.env_file), ".env")
        self.assertEqual(str(args.manifest_out), "data/provenance")


class TopLevelDispatchTests(unittest.TestCase):
    def test_upload_help_resolves(self) -> None:
        with self.assertRaises(SystemExit) as ctx:
            top_cli.main(["upload-atlas-package", "--help"])
        self.assertEqual(ctx.exception.code, 0)

    def test_routes_to_upload_main(self) -> None:
        argv_tail = [
            "--package-dir",
            "data/outputs/atlas-package__x",
            "--ohbm2026-parquet",
            "data/outputs/parquets/abc/ohbm2026.parquet",
        ]
        with mock.patch.object(
            top_cli.atlas_hosting_cli, "upload_main", return_value=0
        ) as upload_main:
            rc = top_cli.main(["upload-atlas-package", *argv_tail])
        self.assertEqual(rc, 0)
        upload_main.assert_called_once()
        # The subcommand argv (without the command token) is forwarded.
        self.assertEqual(upload_main.call_args.args[0], argv_tail)


class CompareParserAndExitCodeTests(unittest.TestCase):
    def test_compare_help_resolves(self) -> None:
        with self.assertRaises(SystemExit) as ctx:
            top_cli.main(["compare-data-hosting", "--help"])
        self.assertEqual(ctx.exception.code, 0)

    def test_compare_required_args(self) -> None:
        parser = hosting_cli.build_compare_parser()
        with self.assertRaises(SystemExit):
            parser.parse_args(["--registry", "r.json"])  # missing channels + origin

    def test_routes_to_compare_main(self) -> None:
        with mock.patch.object(
            top_cli.atlas_hosting_cli, "compare_main", return_value=0
        ) as compare_main:
            rc = top_cli.main(
                [
                    "compare-data-hosting",
                    "--registry",
                    "r.json",
                    "--dropbox-channel",
                    "prod",
                    "--r2-channel",
                    "r2",
                    "--origin",
                    "https://abstractatlas.brainkb.org",
                ]
            )
        self.assertEqual(rc, 0)
        compare_main.assert_called_once()


class RequireCacheGateTests(unittest.TestCase):
    """Spec 022 — `--require-cache` exits non-zero via DataHostingCacheError
    when the host is not edge-cache-effective (CA-006 loud failure)."""

    def _run(self, cache_effective, extra_args):
        with TemporaryDirectory() as td:
            reg = Path(td) / "registry.json"
            reg.write_text(json.dumps({"d": {"ohbm2026": {"url": "u"}}, "r": {"ohbm2026": {"url": "u"}}}))
            argv = [
                "--registry", str(reg),
                "--dropbox-channel", "d",
                "--r2-channel", "r",
                "--origin", "https://abstractatlas.brainkb.org",
                "--report-out", td,
                *extra_args,
            ]
            with mock.patch.object(
                hosting_cli.compare, "compare_channels", return_value=_report(cache_effective)
            ):
                return hosting_cli.compare_main(argv)

    def test_require_cache_fails_when_not_effective(self) -> None:
        self.assertEqual(self._run(False, ["--verify-cache", "--require-cache"]), 3)

    def test_require_cache_passes_when_effective(self) -> None:
        self.assertEqual(self._run(True, ["--verify-cache", "--require-cache"]), 0)

    def test_require_cache_without_probe_fails(self) -> None:
        # --require-cache but no --verify-cache → cache_effective is None → gate fails.
        self.assertEqual(self._run(None, ["--require-cache"]), 3)


if __name__ == "__main__":
    unittest.main()
