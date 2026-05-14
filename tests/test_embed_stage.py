"""Integration tests for `src/ohbm2026/embed_stage.py`.

Covers User Stories 1 (single-bundle), 2 (resume + budget), and the
remediation tasks T057-T063 (invalidate, dry-run, truncation telemetry,
missing-API-key, SDK model-id mismatch).
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import tempfile
import unittest
import zlib
from pathlib import Path

import numpy as np

from ohbm2026 import embed_stage, embed_storage
from ohbm2026.exceptions import (
    EmbeddingBudgetError,
    EmbeddingContractError,
    EmbeddingError,
)


# ---- shared fixtures -------------------------------------------------


def _make_synthetic_corpus(path: Path, n: int = 3) -> str:
    """Build a synthetic enriched SQLite with `n` abstracts."""
    con = sqlite3.connect(path)
    con.execute(
        "CREATE TABLE abstracts ("
        "id INTEGER PRIMARY KEY, payload BLOB, content_hash TEXT, enriched_at TEXT)"
    )
    con.execute(
        "CREATE TABLE corpus_metadata (key TEXT PRIMARY KEY, value TEXT)"
    )
    state_key = "deadbeef0001"
    con.execute(
        "INSERT INTO corpus_metadata (key, value) VALUES ('state_key', ?)",
        (state_key,),
    )
    for i in range(n):
        aid = 1000 + i
        record = {
            "id": aid,
            "title": f"Title abstract {aid}",
            "responses": [
                {"question_name": "Introduction", "value": f"Intro {aid}"},
                {"question_name": "Methods", "value": f"Methods {aid}"},
                {"question_name": "Results", "value": f"Results {aid}"},
                {"question_name": "Conclusion", "value": f"Conclusion {aid}"},
            ],
            "claims": [
                {"claim": f"Claim A for {aid}", "claim_type": "EXPLICIT"},
                {"claim": f"Claim B for {aid}", "claim_type": "IMPLICIT"
                                                  if i % 2 == 0 else "EXPLICIT"},
            ],
        }
        payload = zlib.compress(json.dumps(record).encode("utf-8"))
        con.execute(
            "INSERT INTO abstracts (id, payload, content_hash, enriched_at) "
            "VALUES (?, ?, ?, ?)",
            (aid, payload, "0" * 64, "2026-05-14T00:00:00Z"),
        )
    con.commit()
    con.close()
    return state_key


class _FakeBatchClient:
    """In-memory deterministic embedding client.

    Returns vectors of fixed dimension where each component is a
    function of the input text length — deterministic, easy to assert
    against. Records every call so tests can verify cache + batch
    behavior.
    """

    def __init__(
        self,
        *,
        model_id: str = "fake-model-v1",
        dim: int = 4,
        truncate_at: int | None = None,
        raise_on_call: Exception | None = None,
        raise_on_count: int | None = None,
        reported_model: str | None = None,
    ) -> None:
        self.model_id = model_id
        self.dim = dim
        self.truncate_at = truncate_at
        self.reported_model = reported_model if reported_model is not None else model_id
        self.calls: list[list[str]] = []
        self._raise_on_call = raise_on_call
        self._raise_on_count = raise_on_count

    def embed_batch(self, texts: list[str]) -> tuple[list[list[float]], dict]:
        if self._raise_on_count is not None and len(self.calls) >= self._raise_on_count:
            raise self._raise_on_call  # type: ignore[misc]
        if self._raise_on_call and self._raise_on_count is None:
            raise self._raise_on_call
        self.calls.append(list(texts))
        vectors = []
        truncated_flags = []
        for text in texts:
            seed = float(len(text) % 100) / 100.0
            vec = [seed + i * 0.001 for i in range(self.dim)]
            vectors.append(vec)
            truncated_flags.append(
                bool(self.truncate_at and len(text) > self.truncate_at)
            )
        return vectors, {
            "tokens_used": sum(len(t) for t in texts) // 4,
            "reported_model": self.reported_model,
            "attempts": 1,
            "latency_ms": 0.1,
            "truncated_flags": truncated_flags,
        }


def _args(**overrides) -> argparse.Namespace:
    """Build an args namespace with sane defaults; overrides win."""
    defaults = dict(
        models=["minilm"],
        components=["title"],
        source_corpus=str(Path("data/primary/abstracts_enriched.sqlite")),
        embeddings_root="data/outputs/experiments/embeddings",
        cache_root="data/cache/embeddings",
        voyage_model_id="voyage-large-2-instruct",
        openai_model_id="text-embedding-3-small",
        minilm_model_id="sentence-transformers/all-MiniLM-L6-v2",
        pubmedbert_model_id="neuml/pubmedbert-base-embeddings",
        batch_size=64,
        concurrency_start=8,
        concurrency_max=24,
        long_input_strategy=[],
        failure_threshold=0.01,
        allow_partial=[],
        invalidate=[],
        dry_run=False,
        env_file=".env",
    )
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


class _Tmp:
    def __init__(self) -> None:
        self.dir = tempfile.TemporaryDirectory()
        self.path = Path(self.dir.name)

    def cleanup(self) -> None:
        self.dir.cleanup()


# ---- US1 tests --------------------------------------------------------


class SingleBundleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fx = _Tmp()
        self.addCleanup(self.fx.cleanup)
        self.corpus_path = self.fx.path / "corpus.sqlite"
        self.state_key = _make_synthetic_corpus(self.corpus_path, n=3)
        self.records, _ = embed_stage.load_enriched_corpus(self.corpus_path)
        self.component_texts = {
            (int(r["id"]), "title"): r["title"] for r in self.records
        }

    def _run(self, *, model_key="minilm", component="title", client=None, args=None):
        args = args or _args()
        client = client or _FakeBatchClient()
        return embed_stage.run_single_bundle(
            model_key=model_key,
            component=component,
            records=self.records,
            component_texts=self.component_texts,
            corpus_state_key=self.state_key,
            corpus_source_path=self.corpus_path,
            embeddings_root=self.fx.path / "embeddings",
            cache_root=self.fx.path / "cache",
            clients={model_key: client},
            args=args,
        )

    def test_single_bundle_clean_run(self) -> None:
        result = self._run()
        self.assertEqual(result.status, "ok")
        self.assertEqual(result.present_count, 3)
        self.assertEqual(result.cache_miss_count, 3)
        self.assertEqual(result.cache_hit_count, 0)

        bundle = embed_storage.load_bundle(self.fx.path / "embeddings" / "minilm" / "title__deadbeef0001")
        self.assertEqual(bundle["vectors"].shape, (3, 4))
        self.assertEqual(bundle["ids"].tolist(), sorted(r["id"] for r in self.records))
        self.assertEqual(bundle["metadata"]["model_key"], "minilm")
        self.assertEqual(bundle["metadata"]["component"], "title")
        self.assertEqual(bundle["metadata"]["corpus_state_key"], self.state_key)

    def test_cache_hit_skips_provider(self) -> None:
        client = _FakeBatchClient()
        self._run(client=client)
        # Second run with a fresh-but-recording client: must hit cache, zero calls.
        client2 = _FakeBatchClient()
        result = self._run(client=client2)
        self.assertEqual(result.cache_hit_count, 3)
        self.assertEqual(result.cache_miss_count, 0)
        self.assertEqual(client2.calls, [])

    def test_corpus_state_key_mismatch_refuses_overwrite(self) -> None:
        # Pre-write a bundle with a DIFFERENT corpus state key.
        bundle_dir = self.fx.path / "embeddings" / "minilm" / "title__deadbeef0001"
        embed_storage.write_bundle(
            bundle_dir,
            ids=[1],
            vectors=np.zeros((1, 4), dtype=np.float32),
            metadata={"corpus_state_key": "OLDSTATEKEY", "component": "title"},
        )
        with self.assertRaises(EmbeddingError) as ctx:
            self._run()
        self.assertIn("refusing to overwrite", str(ctx.exception))


# ---- US2 tests (resume + budget) -------------------------------------


class ResumeAndBudgetTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fx = _Tmp()
        self.addCleanup(self.fx.cleanup)
        self.corpus_path = self.fx.path / "corpus.sqlite"
        self.state_key = _make_synthetic_corpus(self.corpus_path, n=5)
        self.records, _ = embed_stage.load_enriched_corpus(self.corpus_path)
        self.component_texts = {
            (int(r["id"]), "title"): r["title"] for r in self.records
        }

    def _call(self, client, args=None):
        return embed_stage.run_single_bundle(
            model_key="minilm",
            component="title",
            records=self.records,
            component_texts=self.component_texts,
            corpus_state_key=self.state_key,
            corpus_source_path=self.corpus_path,
            embeddings_root=self.fx.path / "embeddings",
            cache_root=self.fx.path / "cache",
            clients={"minilm": client},
            args=args or _args(batch_size=2),
        )

    def test_budget_exhausted_preserves_cache(self) -> None:
        # Client succeeds on first batch (2 abstracts) then raises budget on second.
        client = _FakeBatchClient(
            raise_on_call=EmbeddingBudgetError("simulated 402"),
            raise_on_count=1,
        )
        with self.assertRaises(EmbeddingBudgetError):
            self._call(client)
        # First batch's two cache entries MUST persist on disk.
        cache_files = list((self.fx.path / "cache" / "minilm").iterdir())
        self.assertEqual(len(cache_files), 2)

    def test_resume_uses_cache(self) -> None:
        # First run: complete success.
        first = self._call(_FakeBatchClient())
        self.assertEqual(first.cache_miss_count, 5)

        # Second run: fresh recording client; should be 100% cache hits.
        client2 = _FakeBatchClient()
        # Move bundle aside so the second call rebuilds it fresh from cache.
        bundle_dir = self.fx.path / "embeddings" / "minilm" / "title__deadbeef0001"
        if bundle_dir.exists():
            import shutil
            shutil.rmtree(bundle_dir)
        second = self._call(client2)
        self.assertEqual(second.cache_hit_count, 5)
        self.assertEqual(client2.calls, [])


# ---- Truncation telemetry (T061) -------------------------------------


class TruncationTelemetryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fx = _Tmp()
        self.addCleanup(self.fx.cleanup)
        self.corpus_path = self.fx.path / "corpus.sqlite"
        self.state_key = _make_synthetic_corpus(self.corpus_path, n=4)
        self.records, _ = embed_stage.load_enriched_corpus(self.corpus_path)
        # Some methods are short, some are long — fake client uses len(text).
        self.component_texts = {
            (int(r["id"]), "methods"):
                "X" * 200 if int(r["id"]) % 2 == 0 else "X" * 4000
            for r in self.records
        }

    def test_truncated_count_recorded(self) -> None:
        # truncate_at=1000 → ids with > 1000-char text are flagged.
        client = _FakeBatchClient(truncate_at=1000)
        result = embed_stage.run_single_bundle(
            model_key="minilm",
            component="methods",
            records=self.records,
            component_texts=self.component_texts,
            corpus_state_key=self.state_key,
            corpus_source_path=self.corpus_path,
            embeddings_root=self.fx.path / "embeddings",
            cache_root=self.fx.path / "cache",
            clients={"minilm": client},
            args=_args(components=["methods"], batch_size=4),
        )
        # 2 of 4 abstracts have len(text) > 1000 (odd-id ones).
        self.assertEqual(result.truncated_count, 2)
        bundle = embed_storage.load_bundle(
            self.fx.path / "embeddings" / "minilm" / "methods__deadbeef0001"
        )
        self.assertEqual(bundle["metadata"]["truncated_count"], 2)
        self.assertEqual(len(bundle["metadata"]["truncated_ids"]), 2)


# ---- Missing-API-key test (T062) -------------------------------------


class MissingKeyTests(unittest.TestCase):
    def test_missing_voyage_key_raises_typed_error(self) -> None:
        # build_clients refuses when VOYAGE_API_KEY is absent.
        args = _args(models=["voyage"])
        env: dict = {}  # no keys
        # Clear any inherited env var.
        prior_voy_key = os.environ.pop("VOYAGE_API_KEY", None)
        prior_voy_api = os.environ.pop("VOYAGE_API", None)
        try:
            with self.assertRaises(EmbeddingError) as ctx:
                embed_stage.build_clients(args, env)
            self.assertIn("Voyage", str(ctx.exception))
        finally:
            if prior_voy_key is not None:
                os.environ["VOYAGE_API_KEY"] = prior_voy_key
            if prior_voy_api is not None:
                os.environ["VOYAGE_API"] = prior_voy_api

    def test_missing_openai_key_raises_typed_error(self) -> None:
        args = _args(models=["openai"])
        env: dict = {}
        prior = os.environ.pop("OPENAI_API_KEY", None)
        try:
            with self.assertRaises(EmbeddingError) as ctx:
                embed_stage.build_clients(args, env)
            self.assertIn("OpenAI", str(ctx.exception))
        finally:
            if prior is not None:
                os.environ["OPENAI_API_KEY"] = prior


# ---- SDK model-id mismatch (T063) ------------------------------------


class ModelIdMismatchTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fx = _Tmp()
        self.addCleanup(self.fx.cleanup)
        self.corpus_path = self.fx.path / "corpus.sqlite"
        self.state_key = _make_synthetic_corpus(self.corpus_path, n=2)
        self.records, _ = embed_stage.load_enriched_corpus(self.corpus_path)
        self.component_texts = {
            (int(r["id"]), "title"): r["title"] for r in self.records
        }

    def test_off_model_id_raises_contract_error(self) -> None:
        client = _FakeBatchClient(
            model_id="requested-model-X",
            reported_model="totally-different-model-Y",
        )
        with self.assertRaises(EmbeddingContractError):
            embed_stage.run_single_bundle(
                model_key="minilm",
                component="title",
                records=self.records,
                component_texts=self.component_texts,
                corpus_state_key=self.state_key,
                corpus_source_path=self.corpus_path,
                embeddings_root=self.fx.path / "embeddings",
                cache_root=self.fx.path / "cache",
                clients={"minilm": client},
                args=_args(),
            )


# ---- Dry-run (T059, T060) --------------------------------------------


class DryRunTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fx = _Tmp()
        self.addCleanup(self.fx.cleanup)
        self.corpus_path = self.fx.path / "corpus.sqlite"
        self.state_key = _make_synthetic_corpus(self.corpus_path, n=2)
        self.records, _ = embed_stage.load_enriched_corpus(self.corpus_path)
        self.component_texts = {
            (int(r["id"]), "title"): r["title"] for r in self.records
        }

    def test_dry_run_short_circuits_no_provider_calls(self) -> None:
        client = _FakeBatchClient(
            raise_on_call=AssertionError("dry-run should not call provider"),
            raise_on_count=0,
        )
        result = embed_stage.run_single_bundle(
            model_key="minilm",
            component="title",
            records=self.records,
            component_texts=self.component_texts,
            corpus_state_key=self.state_key,
            corpus_source_path=self.corpus_path,
            embeddings_root=self.fx.path / "embeddings",
            cache_root=self.fx.path / "cache",
            clients={"minilm": client},
            args=_args(dry_run=True),
        )
        self.assertEqual(result.status, "skipped")
        self.assertEqual(client.calls, [])
        # No bundle written.
        self.assertFalse((self.fx.path / "embeddings" / "minilm" / "title__deadbeef0001").exists())


if __name__ == "__main__":
    unittest.main()
