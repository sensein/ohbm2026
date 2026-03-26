import importlib.util
import math
import unittest
from pathlib import Path

import plotly.graph_objects as go


def _load_module():
    module_path = Path(__file__).resolve().parents[1] / "scripts" / "plot_voyage_stage2_umap_3d.py"
    spec = importlib.util.spec_from_file_location("plot_voyage_stage2_umap_3d", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load plot_voyage_stage2_umap_3d module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class PlotVoyageStage2Umap3dTest(unittest.TestCase):
    def test_extract_primary_topic_from_response(self) -> None:
        module = _load_module()
        abstract = {
            "responses": [
                {
                    "question_name": "Primary Parent Category & Sub-Category",
                    "value": '["Modeling and Analysis Methods", "Connectivity and Network Modeling"]',
                }
            ]
        }

        topic = module._extract_primary_topic(abstract)

        self.assertEqual(topic, "Modeling and Analysis Methods")

    def test_camera_eye_traces_expected_orbit(self) -> None:
        module = _load_module()

        eye = module._camera_eye(math.pi / 2.0, radius=2.0, height=0.75)

        self.assertAlmostEqual(eye["x"], 0.0, places=6)
        self.assertAlmostEqual(eye["y"], 2.0, places=6)
        self.assertAlmostEqual(eye["z"], 0.75, places=6)

    def test_render_rotating_html_includes_explicit_controls_and_legend(self) -> None:
        module = _load_module()
        figure = go.Figure(go.Scatter3d(x=[0], y=[0], z=[0], mode="markers"))

        html = module.render_rotating_html(
            figure,
            legend_rows=[{"label": "alpha", "count": 3, "color": "#ff0000"}],
            frame_count=120,
            orbit_radius=1.9,
            orbit_height=0.8,
        )

        self.assertIn("rotate-button", html)
        self.assertIn("pause-button", html)
        self.assertIn("Rotation: running", html)
        self.assertIn("Voyage 31 Clusters", html)
        self.assertIn("alpha", html)


if __name__ == "__main__":
    unittest.main()
