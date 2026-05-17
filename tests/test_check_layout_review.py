import importlib.util
import unittest
from pathlib import Path


def _load_check_module():
    module_path = Path(__file__).resolve().parents[1] / "scripts" / "layout" / "check_layout_review.py"
    spec = importlib.util.spec_from_file_location("check_layout_review", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load check_layout_review module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class CheckLayoutReviewTest(unittest.TestCase):
    def test_file_url_escapes_spaces(self) -> None:
        module = _load_check_module()
        url = module._file_url(Path("/tmp/example folder/layout review.html"))
        self.assertTrue(url.startswith("file://"))
        self.assertIn("%20", url)


if __name__ == "__main__":
    unittest.main()
