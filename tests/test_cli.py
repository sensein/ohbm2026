import unittest
from unittest import mock

from ohbm2026 import cli


class CLITest(unittest.TestCase):
    def test_ingest_subcommand_delegates_to_ingest_main(self) -> None:
        with mock.patch.object(cli.assets, "main", return_value=7) as ingest_main:
            result = cli.main(["ingest", "--batch-size", "10"])

        self.assertEqual(result, 7)
        ingest_main.assert_called_once_with(["--batch-size", "10"])

    def test_refresh_assets_appends_refresh_flag(self) -> None:
        with mock.patch.object(cli.assets, "main", return_value=3) as ingest_main:
            result = cli.main(["refresh-assets", "--reuse-existing-assets-only"])

        self.assertEqual(result, 3)
        ingest_main.assert_called_once_with(
            ["--reuse-existing-assets-only", "--refresh-assets-from-existing-db"]
        )

    def test_phase2_subcommand_delegates_to_phase2_main(self) -> None:
        with mock.patch.object(cli.enrichment, "main", return_value=9) as phase2_main:
            result = cli.main(["phase2", "--skip-minilm"])

        self.assertEqual(result, 9)
        phase2_main.assert_called_once_with(["--skip-minilm"])


if __name__ == "__main__":
    unittest.main()
