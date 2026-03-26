import importlib.util
import tempfile
import unittest
from pathlib import Path


def _load_runner_module():
    module_path = Path(__file__).resolve().parents[1] / "scripts" / "run_advanced_global_path_experiment.py"
    spec = importlib.util.spec_from_file_location("run_advanced_global_path_experiment", module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class RunAdvancedGlobalPathExperimentScriptTest(unittest.TestCase):
    def test_validate_output_root_rejects_non_empty_directory(self) -> None:
        runner = _load_runner_module()
        with tempfile.TemporaryDirectory() as tmpdir:
            output_root = Path(tmpdir) / "outputs"
            output_root.mkdir(parents=True, exist_ok=True)
            (output_root / "summary.json").write_text("{}", encoding="utf-8")

            with self.assertRaises(FileExistsError):
                runner.validate_output_root(output_root, allow_existing_output=False)

    def test_validate_output_root_allows_empty_directory(self) -> None:
        runner = _load_runner_module()
        with tempfile.TemporaryDirectory() as tmpdir:
            output_root = Path(tmpdir) / "outputs"
            output_root.mkdir(parents=True, exist_ok=True)

            runner.validate_output_root(output_root, allow_existing_output=False)


if __name__ == "__main__":
    unittest.main()
