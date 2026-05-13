import unittest
from unittest import mock

from ohbm2026 import cli


class CLITest(unittest.TestCase):
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

    def test_extract_claims_subcommand_delegates_to_extract_claims_main(self) -> None:
        with mock.patch.object(cli.enrichment, "extract_claims_main", return_value=12) as extract_claims_main:
            result = cli.main(["extract-claims", "--max-abstracts", "5"])

        self.assertEqual(result, 12)
        extract_claims_main.assert_called_once_with(["--max-abstracts", "5"])

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

    def test_embed_hf_subcommand_delegates_to_hf_main(self) -> None:
        with mock.patch.object(cli.neuroscape, "hf_main", return_value=18) as hf_main:
            result = cli.main(["embed-hf", "--model", "neuml/pubmedbert-base-embeddings"])

        self.assertEqual(result, 18)
        hf_main.assert_called_once_with(["--model", "neuml/pubmedbert-base-embeddings"])

    def test_embed_voyage_subcommand_delegates_to_voyage_main(self) -> None:
        with mock.patch.object(cli.neuroscape, "voyage_main", return_value=19) as voyage_main:
            result = cli.main(["embed-voyage", "--voyage-model", "test-model", "--batch-size", "16"])

        self.assertEqual(result, 19)
        voyage_main.assert_called_once_with(["--voyage-model", "test-model", "--batch-size", "16"])

    def test_embed_openai_subcommand_delegates_to_openai_main(self) -> None:
        with mock.patch.object(cli.neuroscape, "openai_main", return_value=20) as openai_main:
            result = cli.main(["embed-openai", "--openai-model", "text-embedding-3-small"])

        self.assertEqual(result, 20)
        openai_main.assert_called_once_with(["--openai-model", "text-embedding-3-small"])

    def test_embed_stage2_subcommand_delegates_to_stage2_main(self) -> None:
        with mock.patch.object(cli.neuroscape, "stage2_main", return_value=21) as stage2_main:
            result = cli.main(["embed-stage2", "--epochs", "5"])

        self.assertEqual(result, 21)
        stage2_main.assert_called_once_with(["--epochs", "5"])

    def test_apply_published_stage2_subcommand_delegates_to_pretrained_main(self) -> None:
        with mock.patch.object(cli.neuroscape, "apply_pretrained_stage2_main", return_value=28) as pretrained_main:
            result = cli.main(["apply-published-stage2", "--stage1-dir", "custom"])

        self.assertEqual(result, 28)
        pretrained_main.assert_called_once_with(["--stage1-dir", "custom"])

    def test_cluster_benchmark_subcommand_delegates_to_cluster_benchmark_main(self) -> None:
        with mock.patch.object(cli.neuroscape, "cluster_benchmark_main", return_value=31) as cluster_benchmark_main:
            result = cli.main(["cluster-benchmark", "--k-max", "12"])

        self.assertEqual(result, 31)
        cluster_benchmark_main.assert_called_once_with(["--k-max", "12"])

    def test_semantic_analysis_subcommand_delegates_to_semantic_analysis_main(self) -> None:
        with mock.patch.object(cli.neuroscape, "semantic_analysis_main", return_value=22) as semantic_analysis_main:
            result = cli.main(["semantic-analysis", "--num-neighbors", "25"])

        self.assertEqual(result, 22)
        semantic_analysis_main.assert_called_once_with(["--num-neighbors", "25"])

    def test_umap_plot_subcommand_delegates_to_umap_main(self) -> None:
        with mock.patch.object(cli.neuroscape, "umap_main", return_value=23) as umap_main:
            result = cli.main(["umap-plot", "--n-neighbors", "25"])

        self.assertEqual(result, 23)
        umap_main.assert_called_once_with(["--n-neighbors", "25"])

    def test_compare_projections_subcommand_delegates_to_projection_compare_main(self) -> None:
        with mock.patch.object(cli.neuroscape, "projection_compare_main", return_value=26) as compare_main:
            result = cli.main(["compare-projections", "--umap-n-neighbors", "25"])

        self.assertEqual(result, 26)
        compare_main.assert_called_once_with(["--umap-n-neighbors", "25"])

    def test_optimize_projections_subcommand_delegates_to_projection_optimize_main(self) -> None:
        with mock.patch.object(cli.neuroscape, "projection_optimize_main", return_value=27) as optimize_main:
            result = cli.main(["optimize-projections", "--top-k", "3"])

        self.assertEqual(result, 27)
        optimize_main.assert_called_once_with(["--top-k", "3"])

    def test_analyze_stage2_subcommand_delegates_to_stage2_analysis_main(self) -> None:
        with mock.patch.object(cli.neuroscape, "stage2_analysis_main", return_value=24) as stage2_analysis_main:
            result = cli.main(["analyze-stage2", "--num-neighbors", "25"])

        self.assertEqual(result, 24)
        stage2_analysis_main.assert_called_once_with(["--num-neighbors", "25"])

    def test_reference_metadata_subcommand_delegates_to_openalex_main(self) -> None:
        with mock.patch.object(cli.openalex, "main", return_value=24) as openalex_main:
            result = cli.main(["reference-metadata", "--use-title-search"])

        self.assertEqual(result, 24)
        openalex_main.assert_called_once_with(["--use-title-search"])

    def test_title_audit_subcommand_delegates_to_titles_main(self) -> None:
        with mock.patch.object(cli.titles, "main", return_value=32) as titles_main:
            result = cli.main(["title-audit", "--output", "tmp/title_modifications.json"])

        self.assertEqual(result, 32)
        titles_main.assert_called_once_with(["--output", "tmp/title_modifications.json"])

    def test_export_ui_subcommand_delegates_to_ui_export_main(self) -> None:
        with mock.patch.object(cli.ui, "export_ui_main", return_value=29) as export_ui_main:
            result = cli.main(["export-ui", "--output-dir", "tmp/site-data"])

        self.assertEqual(result, 29)
        export_ui_main.assert_called_once_with(["--output-dir", "tmp/site-data"])

    def test_build_ui_subcommand_delegates_to_ui_build_main(self) -> None:
        with mock.patch.object(cli.ui, "build_ui_main", return_value=30) as build_ui_main:
            result = cli.main(["build-ui", "--site-output-dir", "tmp/site"])

        self.assertEqual(result, 30)
        build_ui_main.assert_called_once_with(["--site-output-dir", "tmp/site"])

    def test_write_manifest_subcommand_delegates_to_manifest_main(self) -> None:
        with mock.patch.object(cli.neuroscape, "manifest_main", return_value=25) as manifest_main:
            result = cli.main(["write-manifest", "--output", "manifest.json"])

        self.assertEqual(result, 25)
        manifest_main.assert_called_once_with(["--output", "manifest.json"])


class TestIngestSubcommandRemoved(unittest.TestCase):
    """T011 — `ohbmcli ingest` is REMOVED (no backward-compat alias).
    Per spec FR-014 + Clarifications session 2026-05-12.

    Hermetic safety net: we mock `cli.assets.main` so that, in red
    phase (where `ingest` is still routed), the test fails FAST with
    no live API calls. Once `ingest` is removed in T017, argparse
    will reject it at parse time and raise SystemExit.
    """

    def test_ingest_subcommand_is_not_a_known_choice(self) -> None:
        with mock.patch.object(cli.assets, "main", return_value=0):
            with self.assertRaises(SystemExit):
                cli.main(["ingest"])


class TestFetchAbstractsSubcommand(unittest.TestCase):
    """T011 — `ohbmcli fetch-abstracts` wires to fetch_stage.main.

    Hermetic safety net: if `ohbm2026.fetch_stage` does not exist
    yet (red phase), the test fails on ImportError before any other
    code runs — no live API call possible.
    """

    def test_fetch_abstracts_delegates_to_fetch_stage_main(self) -> None:
        from ohbm2026 import fetch_stage as fetch_stage_module

        with mock.patch.object(fetch_stage_module, "main", return_value=0) as fs_main:
            result = cli.main(["fetch-abstracts", "--allow-empty"])

        self.assertEqual(result, 0)
        fs_main.assert_called_once_with(["--allow-empty"])


if __name__ == "__main__":
    unittest.main()
