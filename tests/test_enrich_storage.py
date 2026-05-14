"""Behavioral tests for `src/ohbm2026/enrich_storage.py`.

Pure SQLite + zlib I/O — no orchestration. Per Principle IV these
tests land before `EnrichedCorpusWriter` exists and MUST initially
fail. Each class corresponds to one storage contract from the spec.
"""

from __future__ import annotations

import json
import os
import random
import sqlite3
import time
import unittest
import zlib
from pathlib import Path
from tempfile import TemporaryDirectory


def _record(abstract_id: int, *, payload_size: int = 800) -> dict[str, object]:
    """A synthetic enriched abstract record. Deterministic per id."""
    return {
        "id": abstract_id,
        "poster_id": f"P-{abstract_id:04d}",
        "title": f"Synthetic abstract {abstract_id}",
        "accepted_for": "Poster",
        "authors": [{"author_order": 1, "first_name": "Test", "last_name": "Person"}],
        "responses": [],
        "external_urls": [],
        "figure_urls": [],
        "program_sessions": [],
        "local_assets": [],
        "figure_interpretation": [],
        "claims": [
            {
                "claim_text": f"Claim {abstract_id}.{i} — " + ("padding " * (payload_size // 10)),
                "confidence": None,
                "model_id": "gpt-4o-2024-08-06",
                "cache_key": "0" * 64,
            }
            for i in range(3)
        ],
        "references": [],
    }


class TestRoundTrip(unittest.TestCase):
    def test_write_then_read_one_round_trips_record_bytes(self) -> None:
        from ohbm2026.enrich import storage as enrich_storage

        with TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "out.sqlite"
            with enrich_storage.EnrichedCorpusWriter(
                db_path,
                state_key="abc123def456",
                source_corpus_hash="d" * 64,
            ) as writer:
                writer.write_record(_record(1))

            got = enrich_storage.read_one_by_id(db_path, 1)
            self.assertEqual(got["id"], 1)
            self.assertEqual(got["title"], "Synthetic abstract 1")
            self.assertEqual(len(got["claims"]), 3)

    def test_zlib_round_trip_at_raw_blob_level(self) -> None:
        """The on-disk payload column is `zlib(json(record))`."""
        from ohbm2026.enrich import storage as enrich_storage

        with TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "out.sqlite"
            with enrich_storage.EnrichedCorpusWriter(
                db_path,
                state_key="abc123def456",
                source_corpus_hash="d" * 64,
            ) as writer:
                writer.write_record(_record(42))

            con = sqlite3.connect(db_path)
            try:
                row = con.execute(
                    "SELECT payload FROM abstracts WHERE id = ?", (42,)
                ).fetchone()
            finally:
                con.close()
            self.assertIsNotNone(row)
            decoded = json.loads(zlib.decompress(row[0]))
            self.assertEqual(decoded["id"], 42)

    def test_duplicate_id_in_same_write_raises(self) -> None:
        from ohbm2026.enrich import storage as enrich_storage

        with TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "out.sqlite"
            with self.assertRaises(sqlite3.IntegrityError):
                with enrich_storage.EnrichedCorpusWriter(
                    db_path,
                    state_key="abc123def456",
                    source_corpus_hash="d" * 64,
                ) as writer:
                    writer.write_record(_record(7))
                    writer.write_record(_record(7))


class TestRandomByID(unittest.TestCase):
    def test_random_lookup_returns_correct_payloads_for_100_ids(self) -> None:
        from ohbm2026.enrich import storage as enrich_storage

        ids = list(range(1, 251))
        with TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "out.sqlite"
            with enrich_storage.EnrichedCorpusWriter(
                db_path,
                state_key="abc123def456",
                source_corpus_hash="d" * 64,
            ) as writer:
                for aid in ids:
                    writer.write_record(_record(aid))

            sampler = random.Random(42)
            sample = sampler.sample(ids, 100)
            for aid in sample:
                got = enrich_storage.read_one_by_id(db_path, aid)
                self.assertEqual(got["id"], aid)
                self.assertEqual(got["title"], f"Synthetic abstract {aid}")

    def test_random_lookup_average_latency_is_under_ten_ms(self) -> None:
        """SC-006: under 10 ms random by ID."""
        from ohbm2026.enrich import storage as enrich_storage

        ids = list(range(1, 251))
        with TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "out.sqlite"
            with enrich_storage.EnrichedCorpusWriter(
                db_path,
                state_key="abc123def456",
                source_corpus_hash="d" * 64,
            ) as writer:
                for aid in ids:
                    writer.write_record(_record(aid))

            sampler = random.Random(42)
            sample = sampler.sample(ids, 100)
            t0 = time.perf_counter()
            for aid in sample:
                enrich_storage.read_one_by_id(db_path, aid)
            elapsed = time.perf_counter() - t0
        avg_ms = (elapsed / len(sample)) * 1000.0
        # Generous bound — research.md §1 measured 0.09 ms on the
        # 3333-record corpus; 10 ms is the SC-006 ceiling.
        self.assertLess(avg_ms, 10.0, f"random lookup avg {avg_ms:.3f} ms exceeds SC-006 budget")

    def test_missing_id_returns_none(self) -> None:
        from ohbm2026.enrich import storage as enrich_storage

        with TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "out.sqlite"
            with enrich_storage.EnrichedCorpusWriter(
                db_path,
                state_key="abc123def456",
                source_corpus_hash="d" * 64,
            ) as writer:
                writer.write_record(_record(1))

            self.assertIsNone(enrich_storage.read_one_by_id(db_path, 999_999))


class TestSequentialIteration(unittest.TestCase):
    def test_iter_enriched_yields_all_records_in_id_order(self) -> None:
        from ohbm2026.enrich import storage as enrich_storage

        ids = list(range(1, 51))
        with TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "out.sqlite"
            with enrich_storage.EnrichedCorpusWriter(
                db_path,
                state_key="abc123def456",
                source_corpus_hash="d" * 64,
            ) as writer:
                for aid in reversed(ids):  # write out of order
                    writer.write_record(_record(aid))

            yielded = [rec["id"] for rec in enrich_storage.iter_enriched(db_path)]
        self.assertEqual(yielded, sorted(ids))


class TestAtomicWrite(unittest.TestCase):
    def test_canonical_path_is_only_populated_on_clean_close(self) -> None:
        """The writer writes to a temp path; the rename only happens on
        successful close. An exception inside the with-block MUST leave
        the canonical path absent (or unchanged)."""
        from ohbm2026.enrich import storage as enrich_storage

        with TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "out.sqlite"
            with self.assertRaises(RuntimeError):
                with enrich_storage.EnrichedCorpusWriter(
                    db_path,
                    state_key="abc123def456",
                    source_corpus_hash="d" * 64,
                ) as writer:
                    writer.write_record(_record(1))
                    raise RuntimeError("simulated mid-write failure")

            self.assertFalse(
                db_path.exists(),
                "canonical SQLite file MUST NOT exist when the writer raises mid-run",
            )

    def test_pre_existing_canonical_file_is_preserved_on_failure(self) -> None:
        """A pre-existing 'previous good' SQLite file at the canonical
        path MUST remain untouched if the new run aborts."""
        from ohbm2026.enrich import storage as enrich_storage

        with TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "out.sqlite"
            # Land a previous good corpus.
            with enrich_storage.EnrichedCorpusWriter(
                db_path,
                state_key="abc123def456",
                source_corpus_hash="d" * 64,
            ) as writer:
                writer.write_record(_record(100))
            previous_bytes = db_path.read_bytes()

            with self.assertRaises(RuntimeError):
                with enrich_storage.EnrichedCorpusWriter(
                    db_path,
                    state_key="newkey123456",
                    source_corpus_hash="e" * 64,
                ) as writer:
                    writer.write_record(_record(200))
                    raise RuntimeError("simulated abort during second run")

            self.assertTrue(db_path.exists())
            self.assertEqual(
                db_path.read_bytes(),
                previous_bytes,
                "previous canonical corpus MUST NOT be clobbered by a failed run",
            )

    def test_no_stray_temp_files_after_clean_run(self) -> None:
        from ohbm2026.enrich import storage as enrich_storage

        with TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "out.sqlite"
            with enrich_storage.EnrichedCorpusWriter(
                db_path,
                state_key="abc123def456",
                source_corpus_hash="d" * 64,
            ) as writer:
                writer.write_record(_record(1))

            stray = [p for p in Path(tmp).iterdir() if p.name != "out.sqlite"]
            self.assertEqual(stray, [], f"stray temp files left behind: {stray}")


class TestCorpusMetadataTable(unittest.TestCase):
    def test_corpus_metadata_seeded_with_version_and_state_key(self) -> None:
        from ohbm2026.enrich import storage as enrich_storage

        with TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "out.sqlite"
            with enrich_storage.EnrichedCorpusWriter(
                db_path,
                state_key="abcdef012345",
                source_corpus_hash="d" * 64,
            ) as writer:
                writer.write_record(_record(1))

            meta = enrich_storage.corpus_metadata(db_path)

        self.assertEqual(meta["storage_version"], enrich_storage.STORAGE_VERSION)
        self.assertEqual(meta["corpus_kind"], "accepted")
        self.assertEqual(meta["state_key"], "abcdef012345")
        self.assertEqual(meta["source_corpus_hash"], "d" * 64)
        self.assertIn("built_at", meta)


class TestEnrichedRecordSchema(unittest.TestCase):
    """One round-tripped record validates against
    `contracts/enriched_record.schema.json`."""

    def _load_contract_schema(self) -> dict:
        contract_path = (
            Path(__file__).resolve().parents[1]
            / "specs"
            / "003-enrich-abstracts"
            / "contracts"
            / "enriched_record.schema.json"
        )
        return json.loads(contract_path.read_text(encoding="utf-8"))

    def _check_required(self, record: dict, schema: dict, *, path: str = "") -> None:
        for field in schema.get("required", []):
            self.assertIn(
                field,
                record,
                f"required field '{path}{field}' missing from record",
            )

    def _check_type(self, value, expected, *, path: str) -> None:
        type_map = {
            "integer": int,
            "string": str,
            "number": (int, float),
            "array": list,
            "object": dict,
            "boolean": bool,
            "null": type(None),
        }
        if isinstance(expected, list):
            allowed = tuple(type_map[t] for t in expected)
            self.assertIsInstance(value, allowed, f"{path} type mismatch")
        else:
            self.assertIsInstance(value, type_map[expected], f"{path} type mismatch")

    def test_round_tripped_record_satisfies_contract_schema(self) -> None:
        from ohbm2026.enrich import storage as enrich_storage

        schema = self._load_contract_schema()
        defs = schema["$defs"]

        with TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "out.sqlite"
            with enrich_storage.EnrichedCorpusWriter(
                db_path,
                state_key="abc123def456",
                source_corpus_hash="d" * 64,
            ) as writer:
                writer.write_record(_record(1))

            got = enrich_storage.read_one_by_id(db_path, 1)

        # Top-level required fields.
        self._check_required(got, schema)
        # Per-item shape walks.
        for claim in got["claims"]:
            self._check_required(claim, defs["Claim"], path="claims[].")
            self.assertIsInstance(claim["claim_text"], str)
            self.assertIsInstance(claim["model_id"], str)
            self.assertRegex(claim["cache_key"], r"^[0-9a-f]{64}$")
        for fig in got["figure_interpretation"]:
            self._check_required(fig, defs["FigureInterpretation"], path="figure_interpretation[].")
        for ref in got["references"]:
            self._check_required(ref, defs["ReferenceResolution"], path="references[].")
            self.assertIn(ref["resolution_status"], {"resolved", "partial", "unresolved"})


if __name__ == "__main__":
    unittest.main()
