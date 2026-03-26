import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


def _load_plot_module():
    module_path = Path(__file__).resolve().parents[1] / "scripts" / "plot_poster_layout_day_comparison.py"
    spec = importlib.util.spec_from_file_location("plot_poster_layout_day_comparison", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load plot_poster_layout_day_comparison module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class PosterLayoutDayPlotTest(unittest.TestCase):
    def test_main_writes_session_umap_html(self) -> None:
        module = _load_plot_module()
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            proposal_dir = root / "proposal"
            proposal_dir.mkdir(parents=True, exist_ok=True)
            proposal = {
                "assignments": [
                    {"abstract_id": 1, "standby_session": 1, "poster_number": 1},
                    {"abstract_id": 2, "standby_session": 2, "poster_number": 2},
                    {"abstract_id": 3, "standby_session": 3, "poster_number": 3},
                    {"abstract_id": 4, "standby_session": 4, "poster_number": 4},
                ]
            }
            (proposal_dir / "proposal.json").write_text(json.dumps(proposal, indent=2), encoding="utf-8")

            umap_path = root / "umap.json"
            umap_path.write_text(
                json.dumps(
                    {
                        "points": [
                            {
                                "id": 1,
                                "title": "One",
                                "accepted_for": "Poster",
                                "primary_topic": "Topic A",
                                "keywords": ["one"],
                                "x": 0.1,
                                "y": 0.2,
                            },
                            {
                                "id": 2,
                                "title": "Two",
                                "accepted_for": "Poster",
                                "primary_topic": "Topic B",
                                "keywords": ["two"],
                                "x": 0.3,
                                "y": 0.4,
                            },
                            {
                                "id": 3,
                                "title": "Three",
                                "accepted_for": "Poster",
                                "primary_topic": "Topic C",
                                "keywords": ["three"],
                                "x": 0.5,
                                "y": 0.6,
                            },
                            {
                                "id": 4,
                                "title": "Four",
                                "accepted_for": "Poster",
                                "primary_topic": "Topic D",
                                "keywords": ["four"],
                                "x": 0.7,
                                "y": 0.8,
                            },
                        ]
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )

            result = module.main(
                [
                    "--proposal-dir",
                    str(proposal_dir),
                    "--umap-input",
                    str(umap_path),
                ]
            )

            self.assertEqual(result, 0)
            html = (proposal_dir / "session_day_umap.html").read_text(encoding="utf-8")

        self.assertIn("Accepted Abstract Standby Pattern Selection on UI UMAP", html)
        self.assertIn("All accepted", html)
        self.assertIn("Poster %{customdata[1]}", html)


if __name__ == "__main__":
    unittest.main()
