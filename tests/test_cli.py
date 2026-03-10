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

    def test_authors_subcommand_delegates_to_authors_main(self) -> None:
        with mock.patch.object(cli.enrichment, "authors_main", return_value=9) as authors_main:
            result = cli.main(["authors", "--authors-output", "custom.json"])

        self.assertEqual(result, 9)
        authors_main.assert_called_once_with(["--authors-output", "custom.json"])

    def test_enrich_subcommand_delegates_to_enrich_main(self) -> None:
        with mock.patch.object(cli.enrichment, "enrich_main", return_value=11) as enrich_main:
            result = cli.main(["enrich", "--enriched-output", "custom.json"])

        self.assertEqual(result, 11)
        enrich_main.assert_called_once_with(["--enriched-output", "custom.json"])

    def test_analyze_figures_subcommand_delegates_to_figure_main(self) -> None:
        with mock.patch.object(cli.enrichment, "analyze_figures_main", return_value=13) as figure_main:
            result = cli.main(["analyze-figures", "--vision-max-images", "2"])

        self.assertEqual(result, 13)
        figure_main.assert_called_once_with(["--vision-max-images", "2"])

    def test_embed_minilm_subcommand_delegates_to_minilm_main(self) -> None:
        with mock.patch.object(cli.neuroscape, "minilm_main", return_value=17) as minilm_main:
            result = cli.main(["embed-minilm", "--embeddings-dir", "custom"])

        self.assertEqual(result, 17)
        minilm_main.assert_called_once_with(["--embeddings-dir", "custom"])

    def test_embed_voyage_subcommand_delegates_to_voyage_main(self) -> None:
        with mock.patch.object(cli.neuroscape, "voyage_main", return_value=19) as voyage_main:
            result = cli.main(["embed-voyage", "--voyage-model", "test-model"])

        self.assertEqual(result, 19)
        voyage_main.assert_called_once_with(["--voyage-model", "test-model"])

    def test_embed_stage2_subcommand_delegates_to_stage2_main(self) -> None:
        with mock.patch.object(cli.neuroscape, "stage2_main", return_value=21) as stage2_main:
            result = cli.main(["embed-stage2", "--epochs", "5"])

        self.assertEqual(result, 21)
        stage2_main.assert_called_once_with(["--epochs", "5"])

    def test_write_manifest_subcommand_delegates_to_manifest_main(self) -> None:
        with mock.patch.object(cli.neuroscape, "manifest_main", return_value=23) as manifest_main:
            result = cli.main(["write-manifest", "--output", "manifest.json"])

        self.assertEqual(result, 23)
        manifest_main.assert_called_once_with(["--output", "manifest.json"])


if __name__ == "__main__":
    unittest.main()
