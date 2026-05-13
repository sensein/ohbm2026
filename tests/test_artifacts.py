import subprocess
import unittest
from pathlib import Path

from ohbm2026 import artifacts


class ArtifactHelpersTest(unittest.TestCase):
    def test_build_state_key_is_deterministic_for_same_basis(self) -> None:
        basis = artifacts.build_dependency_basis(
            input_sources=[str(artifacts.PRIMARY_ABSTRACTS_PATH)],
            input_digest="abc123",
            backend="openai",
            model="gpt-4.1-mini",
            options={"max_images": 5, "temperature": 0},
            env_boundary=["OPENAI_API_KEY"],
        )

        left = artifacts.build_state_key(basis)
        right = artifacts.build_state_key(dict(basis))

        self.assertEqual(left, right)
        self.assertEqual(len(left), 12)

    def test_build_state_key_changes_when_dependency_basis_changes(self) -> None:
        baseline = artifacts.build_dependency_basis(
            input_sources=[str(artifacts.PRIMARY_ABSTRACTS_PATH)],
            input_digest="abc123",
            backend="openai",
            model="gpt-4.1-mini",
            options={"max_images": 5},
        )
        changed = artifacts.build_dependency_basis(
            input_sources=[str(artifacts.PRIMARY_ABSTRACTS_PATH)],
            input_digest="abc123",
            backend="openai",
            model="gpt-4.1-mini",
            options={"max_images": 10},
        )

        self.assertNotEqual(artifacts.build_state_key(baseline), artifacts.build_state_key(changed))

    def test_build_input_snapshot_path_uses_inputs_root(self) -> None:
        path = artifacts.build_input_snapshot_path("abstracts_graphql", "abc123def456")
        self.assertEqual(path, Path("data/inputs/abstracts_graphql__abc123def456.json"))

    def test_build_cache_path_uses_workflow_namespace(self) -> None:
        path = artifacts.build_cache_path("figure_analysis", "image_analyses_openai", "abc123def456")
        self.assertEqual(path, Path("data/cache/figure_analysis/image_analyses_openai__abc123def456.json"))

    def test_build_output_path_uses_family_root(self) -> None:
        path = artifacts.build_output_path("exported-sites", "ui-site", "abc123def456")
        self.assertEqual(path, Path("data/outputs/exported-sites/ui-site__abc123def456"))

    def test_build_publish_path_uses_export_root(self) -> None:
        path = artifacts.build_publish_path("ui-site")
        self.assertEqual(path, Path("export/ui-site"))

    def test_build_schema_artifact_path_lives_under_inputs(self) -> None:
        state_key = "abc123def456"
        path = artifacts.build_schema_artifact_path(state_key)

        self.assertEqual(
            path,
            Path("data/inputs/abstracts_graphql_schema__abc123def456.json"),
        )
        self.assertFalse(path.is_absolute(), "schema artifact path must be project-relative")
        self.assertIn(state_key, path.name)

    def test_build_provenance_path_lives_under_inputs(self) -> None:
        state_key = "abc123def456"
        path = artifacts.build_provenance_path(state_key)

        self.assertEqual(
            path,
            Path("data/inputs/abstracts_fetch_provenance__abc123def456.json"),
        )
        self.assertFalse(path.is_absolute(), "provenance path must be project-relative")
        self.assertIn(state_key, path.name)

    def test_build_fetch_checkpoint_path_lives_under_cache(self) -> None:
        state_key = "abc123def456"
        path = artifacts.build_fetch_checkpoint_path(state_key)

        self.assertEqual(
            path,
            Path("data/cache/fetch_abstracts/checkpoint__abc123def456.json"),
        )
        self.assertFalse(path.is_absolute(), "checkpoint path must be project-relative")
        self.assertIn(state_key, path.name)

    def test_build_artifact_metadata_redacts_secret_values(self) -> None:
        basis = artifacts.build_dependency_basis(
            input_sources=[str(artifacts.PRIMARY_ABSTRACTS_PATH)],
            input_digest="abc123",
            backend="openai",
            model="gpt-4.1-mini",
            env_boundary=["OPENAI_API_KEY"],
        )

        metadata = artifacts.build_artifact_metadata(
            workflow="figure_analysis",
            artifact_name="image_analyses_openai",
            artifact_class="cache",
            state_key=artifacts.build_state_key(basis),
            dependency_basis=basis,
        )

        self.assertEqual(metadata["artifact_class"], "cache")
        self.assertEqual(metadata["dependency_basis"]["env_boundary"], ["OPENAI_API_KEY"])
        self.assertNotIn("sk-", str(metadata))

    def test_invalidation_action_supports_resume_and_selective_rebuild(self) -> None:
        basis = artifacts.build_dependency_basis(input_sources=[str(artifacts.PRIMARY_ABSTRACTS_PATH)], input_digest="abc123")
        state_key = artifacts.build_state_key(basis)

        running = artifacts.build_artifact_metadata(
            workflow="claim_analysis",
            artifact_name="claim_analyses_cllm",
            artifact_class="cache",
            state_key=state_key,
            dependency_basis=basis,
            status="running",
        )
        stale = artifacts.build_artifact_metadata(
            workflow="claim_analysis",
            artifact_name="claim_analyses_cllm",
            artifact_class="cache",
            state_key="different1234",
            dependency_basis=basis,
            status="ready",
        )

        self.assertEqual(artifacts.regeneration_action(running, expected_state_key=state_key), "resume")
        self.assertEqual(artifacts.regeneration_action(stale, expected_state_key=state_key), "selective_rebuild")

    def test_git_ignore_covers_local_artifact_paths(self) -> None:
        root = Path(__file__).resolve().parents[1]
        command = [
            "git",
            "check-ignore",
            "data/inputs/abstracts_graphql__state-key.json",
            "data/cache/figure_analysis/sample__state-key.json",
            "data/outputs/exported-sites/site_bundle__state-key/manifest.json",
        ]
        completed = subprocess.run(command, cwd=root, check=False, capture_output=True, text=True)

        self.assertEqual(completed.returncode, 0, completed.stderr)
        ignored = {line.strip() for line in completed.stdout.splitlines() if line.strip()}
        self.assertIn("data/inputs/abstracts_graphql__state-key.json", ignored)
        self.assertIn("data/cache/figure_analysis/sample__state-key.json", ignored)
        self.assertIn("data/outputs/exported-sites/site_bundle__state-key/manifest.json", ignored)


if __name__ == "__main__":
    unittest.main()
