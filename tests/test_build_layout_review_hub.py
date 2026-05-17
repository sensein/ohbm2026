import importlib.util
import unittest
from pathlib import Path


def _load_hub_module():
    module_path = Path(__file__).resolve().parents[1] / "scripts" / "layout" / "build_layout_review_hub.py"
    spec = importlib.util.spec_from_file_location("build_layout_review_hub", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load build_layout_review_hub module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class LayoutReviewHubTest(unittest.TestCase):
    def test_layout_system_display_name_handles_olo_taxonomy(self) -> None:
        module = _load_hub_module()
        self.assertEqual(
            module._layout_system_display_name("voyage_stage2_olo_contiguous_31"),
            "Voyage OLO contiguous categories (31 clusters)",
        )
        self.assertEqual(
            module._layout_system_display_name("voyage_stage2_nocd_structural_17"),
            "Voyage Stage 2 NOCD structural (17 communities)",
        )

    def test_short_proposal_label_keeps_long_variant_names_compact(self) -> None:
        module = _load_hub_module()
        self.assertEqual(
            module._short_proposal_label("semantic_path_voyage31_olo_two_opt_knn20_p8"),
            "Voyage31 OLO + 2-opt k20",
        )
        self.assertEqual(module._short_proposal_label("semantic_layout_nocd17"), "NOCD 17")

    def test_render_hub_html_includes_selector_and_navigator_controls(self) -> None:
        module = _load_hub_module()
        html = module.render_hub_html(
            [
                {
                    "slug": "alpha",
                    "label": "Alpha proposal",
                    "short_label": "alpha",
                    "taxonomy": "Alpha taxonomy",
                    "layout_count_label": "10 layout categories",
                    "session_count_label": "Sessions 10/10/10/10",
                    "adjacent_match": "90.0%",
                    "semantic_distance": "0.420",
                    "claims_match": "35.0%",
                    "author_conflicts": "0",
                    "screenshot": "layout_review_checks/alpha.png",
                    "review": {
                        "facet_markup": "<section>facet a</section>",
                        "filter_records": [],
                        "plot_configs": {},
                        "block_navigation": {
                            "1": {"label": "June 15-16 block", "records": []},
                            "2": {"label": "June 17-18 block", "records": []},
                        },
                        "default_color_field": "categorical_primary_label",
                        "block_one_figure": {"data": [], "layout": {}},
                        "block_two_figure": {"data": [], "layout": {}},
                        "umap_figure": {"data": [], "layout": {}},
                    },
                    "plotly_js": "window.Plotly = window.Plotly || {};",
                },
                {
                    "slug": "beta",
                    "label": "Beta proposal",
                    "short_label": "beta",
                    "taxonomy": "Beta taxonomy",
                    "layout_count_label": "12 layout categories",
                    "session_count_label": "Sessions 11/11/11/11",
                    "adjacent_match": "91.0%",
                    "semantic_distance": "0.410",
                    "claims_match": "36.0%",
                    "author_conflicts": "0",
                    "screenshot": "layout_review_checks/beta.png",
                    "review": {
                        "facet_markup": "<section>facet b</section>",
                        "filter_records": [],
                        "plot_configs": {},
                        "block_navigation": {
                            "1": {"label": "June 15-16 block", "records": []},
                            "2": {"label": "June 17-18 block", "records": []},
                        },
                        "default_color_field": "voyage25_label",
                        "block_one_figure": {"data": [], "layout": {}},
                        "block_two_figure": {"data": [], "layout": {}},
                        "umap_figure": {"data": [], "layout": {}},
                    },
                },
            ]
        )
        self.assertIn("Poster Layout Review Hub", html)
        self.assertIn("data-proposal-slug=\"alpha\"", html)
        self.assertIn("block-1-plot", html)
        self.assertIn("sidebar-category-selectors", html)
        self.assertIn("Alpha proposal", html)
        self.assertIn("Alpha taxonomy", html)
        self.assertIn("Poster Details", html)
        self.assertIn("poster-detail-card", html)
        self.assertIn("block-nav-slider", html)
        self.assertIn("expand-all-filters", html)
        self.assertIn("expand-proposals", html)
        self.assertIn("Plotly.newPlot('block-1-plot'", html)


if __name__ == "__main__":
    unittest.main()
