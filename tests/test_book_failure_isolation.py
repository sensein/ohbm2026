"""T008 — per-abstract failure isolation.

The pipeline MUST tolerate a single broken-abstract: it drops out, the
rest renders, and `provenance.json` records the failure under
`failed_abstracts[]` (FR-002 / SC-003).

A broken-fixture abstract is created in setUp (raw-tex `\\bogus{}` in
its Methods body) so the test runs hermetically against the fixture
corpus without polluting the committed fixtures. The test chdir's
into the workdir for the duration of the build so the provenance
writer's project-relative-path guard (CA-008) accepts the input
paths.
"""

from __future__ import annotations

import json
import os
import pathlib
import shutil
import tempfile
import unittest


_FIX = pathlib.Path(__file__).parent / "fixtures" / "book"


def _pandoc_engine_ok() -> bool:
    if not shutil.which("pandoc"):
        return False
    return bool(shutil.which("xelatex")) or bool(shutil.which("tectonic"))


@unittest.skipUnless(
    _pandoc_engine_ok(),
    "pandoc + a LaTeX engine (xelatex or tectonic) required",
)
class TestFailureIsolation(unittest.TestCase):
    def setUp(self) -> None:
        # Build a temp corpus = fixture corpus + ONE broken abstract.
        try:
            from ohbm2026.book.cli import main  # noqa: F401
        except ImportError as exc:
            self.skipTest(f"book CLI not importable: {exc}")

        self.tmp = tempfile.TemporaryDirectory()
        self.workdir = pathlib.Path(self.tmp.name)
        # Copy fixture inputs into the workdir so the build can use
        # workdir-relative paths (provenance writer rejects /tmp/...).
        for name in (
            "authors.json",
            "abstracts_withdrawn.json",
        ):
            shutil.copy2(_FIX / name, self.workdir / name)
        shutil.copytree(_FIX / "assets", self.workdir / "assets")
        self.broken_corpus = self.workdir / "abstracts.json"
        self._original_cwd = pathlib.Path.cwd()
        os.chdir(self.workdir)

        corpus = json.loads((_FIX / "abstracts.json").read_text())
        # Compute the next available poster_id + submission_id.
        # Some fixture entries may have null poster_id (withdrawn-shape
        # placeholders); skip those when finding the max.
        existing_poster_ids = [
            int(a["poster_id"])
            for a in corpus["abstracts"]
            if a.get("poster_id") is not None
        ]
        next_poster = f"{max(existing_poster_ids) + 1:04d}"
        next_submission = max(int(a["id"]) for a in corpus["abstracts"]) + 1

        broken = {
            "id": next_submission,
            "poster_id": next_poster,
            "title": "Broken abstract for isolation test",
            "accepted_for": "Poster",
            "authors": [{"author_order": 0, "id": 80001}],
            "responses": [
                {
                    "question_name": "Title",
                    "value": "Broken abstract for isolation test",
                },
                {
                    "question_name": "4. Country",
                    "value": "United States",
                },
                {
                    "question_name": "Introduction",
                    "value": "<p>Intro for the broken case.</p>",
                },
                # raw-tex command pandoc passes through; Tectonic
                # / xelatex fails on \bogus{} because no such macro.
                {
                    "question_name": "Methods",
                    "value": "<p>Methods text. \\bogus{} should break.</p>",
                },
                {
                    "question_name": "Results",
                    "value": "<p>Results body.</p>",
                },
                {
                    "question_name": "Conclusion",
                    "value": "<p>Conclusion body.</p>",
                },
                {
                    "question_name": "Acknowledgement",
                    "value": "Acks.",
                },
                {
                    "question_name": "References/Citations",
                    "value": "<ol><li>Smith 2020.</li></ol>",
                },
            ],
            "external_urls": [],
            "figure_urls": [],
            "program_sessions": [],
        }
        corpus["abstracts"].append(broken)
        corpus["abstract_count"] = len(corpus["abstracts"])
        self.broken_corpus.write_text(json.dumps(corpus, indent=2))
        self.expected_total = corpus["abstract_count"]
        self.broken_poster_id = int(next_poster)

    def tearDown(self) -> None:
        os.chdir(self._original_cwd)
        self.tmp.cleanup()

    def test_broken_abstract_drops_out_others_render(self) -> None:
        from ohbm2026.book.cli import main

        # cwd is self.workdir per setUp; use workdir-relative paths so
        # the provenance writer's project-relative-path guard passes.
        exit_code = main(
            [
                "--corpus",
                "abstracts.json",
                "--authors",
                "authors.json",
                "--withdrawn",
                "abstracts_withdrawn.json",
                "--assets-root",
                "assets",
                "--standby-csv",
                "",
                "--output-root",
                "out",
                "--format",
                "pdf",
                "--sort",
                "poster_id",
                "--workers",
                "1",
                "--cache-dir",
                ".cache/book",
            ]
        )
        output_root = self.workdir / "out"
        self.assertEqual(exit_code, 0, "build should succeed despite broken abstract")

        # Locate the produced book__<state-key>/ dir.
        book_dirs = list(output_root.glob("book__*"))
        self.assertEqual(len(book_dirs), 1, f"unexpected outputs: {book_dirs}")
        book_dir = book_dirs[0]

        prov = json.loads((book_dir / "provenance.json").read_text())

        # Provenance MUST list the broken poster_id under failed_abstracts.
        failed = prov.get("failed_abstracts", [])
        self.assertEqual(
            len(failed),
            1,
            f"expected exactly one failed abstract; got {failed}",
        )
        self.assertEqual(failed[0]["poster_id"], self.broken_poster_id)
        self.assertIn("pandoc_exit_code", failed[0])
        self.assertIn("stderr_tail", failed[0])

        # The assembled PDF MUST contain (filtered_total - 1) abstracts:
        # provenance.abstract_count is the count POST-filter (corpus
        # loader drops null-poster_id placeholders), so surviving =
        # abstract_count - 1.
        rendered = prov.get("abstract_count")
        included = prov.get("included_poster_ids", [])
        self.assertIsInstance(rendered, int)
        self.assertEqual(
            len(included),
            rendered - 1,
            f"expected {rendered - 1} included, got {len(included)}: {included}",
        )
        self.assertNotIn(self.broken_poster_id, included)

        # The assembled PDF exists + is non-trivial in size.
        pdf = book_dir / "book.pdf"
        self.assertTrue(pdf.exists())
        self.assertGreater(pdf.stat().st_size, 1024)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
