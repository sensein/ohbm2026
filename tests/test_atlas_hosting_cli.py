"""Tests for the Stage 20 CLI surface + top-level dispatch.

Spec: ``specs/020-cloudflare-r2-migration/`` —
``contracts/cli-upload-atlas-package.md`` (+ compare in US3).
"""

from __future__ import annotations

import unittest
from unittest import mock

from ohbm2026 import cli as top_cli
from ohbm2026.atlas_hosting import cli as hosting_cli


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


if __name__ == "__main__":
    unittest.main()
