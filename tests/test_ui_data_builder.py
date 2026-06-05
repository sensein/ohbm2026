"""T020 + T020a — orchestrator deterministic-build + build_info envelope invariant."""

from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from ohbm2026.ui_data.builder import build_ui_data_package

from tests._ui_data_fixtures import BUILD_INFO, write_fixtures


def _sha256_dir(root: Path) -> dict[str, str]:
    """Return a path → sha256 map for every file under *root*."""

    out: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(root).as_posix()
        out[rel] = hashlib.sha256(path.read_bytes()).hexdigest()
    return out


class TestDeterministicBuild(unittest.TestCase):
    def test_two_runs_produce_byte_identical_shards(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = write_fixtures(Path(tmp) / "inputs")
            out1 = Path(tmp) / "build1" / "data"
            out2 = Path(tmp) / "build2" / "data"
            for output in (out1, out2):
                rc = build_ui_data_package(
                    corpus_path=paths["corpus"],
                    withdrawn_path=paths["withdrawn"],
                    authors_path=paths["authors"],
                    enriched_path=None,
                    references_path=None,
                    analysis_root=None,
                    rollup=paths["rollup"],
                    discover_rollup=False,
                    output_dir=output,
                    build_info=BUILD_INFO,  # pinned timestamp for determinism
                    # Pin to JSON-shards so the byte-identical comparison
                    # walks discrete files; the parquet-single emitter
                    # has its own deterministic test path.
                    output_format="gzip-json-shards",
                )
                self.assertEqual(rc, 0)
            sums1 = _sha256_dir(out1)
            sums2 = _sha256_dir(out2)
            self.assertEqual(sums1, sums2, msg="Builds should be byte-identical with pinned build_info")


class TestEveryShardCarriesBuildInfo(unittest.TestCase):
    """T020a — FR-019 + FR-022 + CA-008 enforcement."""

    REQUIRED_KEYS = {
        "corpus_state_key",
        "code_revision",
        "code_revision_short",
        "stage4_rollup_state_key",
        "built_at",
    }

    def test_every_shard_carries_build_info(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = write_fixtures(Path(tmp) / "inputs")
            output = Path(tmp) / "build" / "data"
            rc = build_ui_data_package(
                corpus_path=paths["corpus"],
                withdrawn_path=paths["withdrawn"],
                authors_path=paths["authors"],
                enriched_path=None,
                references_path=None,
                analysis_root=None,
                rollup=paths["rollup"],
                discover_rollup=False,
                output_dir=output,
                build_info=BUILD_INFO,
                # Stage-10 flipped the default emitter to `parquet-single`
                # (one `.parquet` file). The shard-level assertions below
                # walk JSON files, so pin to the legacy emitter for this
                # invariant test.
                output_format="gzip-json-shards",
            )
            self.assertEqual(rc, 0)

            shards = list(output.rglob("*.json"))
            self.assertGreater(len(shards), 0)
            seen_blocks: list[dict] = []
            for shard in shards:
                with shard.open() as fh:
                    payload = json.load(fh)
                self.assertIsInstance(
                    payload, dict, msg=f"Raw-array shard forbidden: {shard.relative_to(output)}"
                )
                build_info = payload.get("build_info")
                self.assertIsNotNone(
                    build_info, msg=f"Shard {shard.relative_to(output)} missing build_info"
                )
                missing = self.REQUIRED_KEYS - set(build_info.keys())
                self.assertEqual(
                    missing,
                    set(),
                    msg=f"Shard {shard.relative_to(output)} build_info missing keys: {missing}",
                )
                seen_blocks.append(build_info)
            # All build_info blocks across shards must be byte-identical.
            reference = seen_blocks[0]
            for idx, block in enumerate(seen_blocks):
                self.assertEqual(
                    block,
                    reference,
                    msg=f"build_info drift on shard #{idx} ({shards[idx].name})",
                )


class TestResearchDimensionsProvenance(unittest.TestCase):
    """Stage 23 (spec 023) — dimension provenance + determinism + opt-in."""

    def _manifest(self, output: Path) -> dict:
        import io

        import pyarrow.parquet as pq

        outer = pq.read_table(output / "ohbm2026.parquet")
        tables = dict(zip(outer.column("table_name").to_pylist(), outer.column("table_bytes").to_pylist()))
        man = pq.read_table(io.BytesIO(tables["manifest"])).to_pylist()[0]
        return json.loads(man["manifest_json"])

    def _build(self, paths, output, *, dimensions):
        return build_ui_data_package(
            corpus_path=paths["corpus"],
            withdrawn_path=paths["withdrawn"],
            authors_path=paths["authors"],
            enriched_path=None,
            references_path=None,
            analysis_root=None,
            rollup=paths["rollup"],
            discover_rollup=False,
            output_dir=output,
            build_info=BUILD_INFO,
            output_format="parquet-single",
            dimensions_path=dimensions,
        )

    def test_provenance_block_recorded(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = write_fixtures(Path(tmp) / "inputs")
            out = Path(tmp) / "b" / "data"
            self.assertEqual(self._build(paths, out, dimensions=paths["dimensions"]), 0)
            rd = self._manifest(out)["research_dimensions"]
            self.assertEqual(rd["source_file"], "dimensions.slim.json")  # basename only
            self.assertNotIn("/", rd["source_file"])  # CA-008 no path
            self.assertEqual(len(rd["source_sha256"]), 64)
            # exported fixture corpus = poster 101 (1001) + 103 (1003) = 2.
            self.assertEqual(rd["dimensions"]["focus"]["matched"], 2)  # both have focus
            self.assertEqual(rd["dimensions"]["theory_scope"]["matched"], 1)  # only 1001
            self.assertEqual(rd["unmatched_in_file"], 1)  # 9999 not exported

    def test_omitting_dimensions_succeeds_with_no_block(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = write_fixtures(Path(tmp) / "inputs")
            out = Path(tmp) / "b" / "data"
            self.assertEqual(self._build(paths, out, dimensions=None), 0)  # D4
            self.assertNotIn("research_dimensions", self._manifest(out))

    def test_build_with_dimensions_is_byte_identical(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = write_fixtures(Path(tmp) / "inputs")
            out1 = Path(tmp) / "b1" / "data"
            out2 = Path(tmp) / "b2" / "data"
            for out in (out1, out2):
                self.assertEqual(self._build(paths, out, dimensions=paths["dimensions"]), 0)
            self.assertEqual(
                hashlib.sha256((out1 / "ohbm2026.parquet").read_bytes()).hexdigest(),
                hashlib.sha256((out2 / "ohbm2026.parquet").read_bytes()).hexdigest(),
            )  # SC-005 / D5


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
