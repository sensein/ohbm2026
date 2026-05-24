"""Tests for ``ohbm2026.atlas_package.link_check``.

Spec: ``specs/015-neuroscape-context/`` — FR-024 + research R-013
(narrowed scope: only the small fixed set of non-PubMed-record URLs
is pre-checked at build time) + R-009 (``AtlasLinkCheckError``).

Per-PubMed-record URL health is enforced at view time by the
runtime PubMed fetch (R-015), NOT at build time — 461K HEAD requests
against NCBI is infeasible.

All tests mock the HTTP transport via a fake ``requests.Session``-
like object so no network call leaves the process.
"""

from __future__ import annotations

import unittest
from dataclasses import dataclass
from typing import Mapping

from ohbm2026 import exceptions
from ohbm2026.atlas_package import link_check as lc


# ---------------------------------------------------------------------------
# Fake HTTP transport — mirrors the slice of `requests.Session` the
# under-test code touches.
# ---------------------------------------------------------------------------


@dataclass
class _FakeResponse:
    status_code: int

    def close(self) -> None:  # pragma: no cover — drained by GET fallback only
        pass


class _FakeSession:
    """In-memory `requests.Session` stand-in.

    ``answers`` is a mapping ``url → status_code | Exception``. When
    the under-test code calls ``head(url)`` the fake returns the
    canned status (or raises the canned exception).
    """

    def __init__(self, answers: Mapping[str, int | Exception]):
        self.answers = dict(answers)
        self.head_calls: list[str] = []
        self.get_calls: list[str] = []

    def head(self, url: str, *, allow_redirects: bool, timeout: float, headers: dict) -> _FakeResponse:
        self.head_calls.append(url)
        ans = self.answers.get(url, 599)
        if isinstance(ans, Exception):
            raise ans
        return _FakeResponse(status_code=int(ans))

    def get(self, url: str, *, allow_redirects: bool, timeout: float, headers: dict, stream: bool) -> _FakeResponse:
        self.get_calls.append(url)
        ans = self.answers.get(url, 599)
        if isinstance(ans, Exception):
            raise ans
        return _FakeResponse(status_code=int(ans))


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class LinkSetTests(unittest.TestCase):
    def test_default_url_set_covers_R013_scope(self) -> None:
        urls = lc.DEFAULT_LINKS
        names = {entry["name"] for entry in urls}
        # R-013 enumerates these 5 URLs explicitly.
        self.assertIn("neuroscape_zenodo", names)
        self.assertIn("neuroscape_citation", names)
        self.assertIn("ohbm2026_site", names)
        self.assertIn("cross_conference_landing", names)
        self.assertIn("ncbi_eutils_base", names)

    def test_no_per_pubmed_url_pattern_in_default_set(self) -> None:
        # Per FR-024 the per-PubMed-record URL pattern
        # `pubmed.ncbi.nlm.nih.gov/<id>/` MUST NOT be in the build-
        # time set — it is enforced at view time only.
        for entry in lc.DEFAULT_LINKS:
            self.assertNotIn("/pubmed.ncbi.nlm.nih.gov/", entry["url"])


class RunLinkCheckHappyPathTests(unittest.TestCase):
    def test_all_2xx_returns_no_blocking_failures(self) -> None:
        session = _FakeSession({entry["url"]: 200 for entry in lc.DEFAULT_LINKS})
        report = lc.run_link_check(
            lc.DEFAULT_LINKS,
            session=session,
            rate_per_second=0,  # disable sleep in tests
        )
        self.assertEqual(report["n_total"], len(lc.DEFAULT_LINKS))
        self.assertEqual(report["n_2xx"], len(lc.DEFAULT_LINKS))
        self.assertEqual(report["n_4xx"], 0)
        self.assertEqual(report["n_5xx"], 0)
        self.assertEqual(report["deploy_blocking_failures"], [])
        self.assertEqual(report["scope"], "non-pubmed-record only (per FR-024 / R-013)")

    def test_one_404_lands_in_deploy_blocking_failures(self) -> None:
        answers: dict[str, int | Exception] = {
            entry["url"]: 200 for entry in lc.DEFAULT_LINKS
        }
        target = lc.DEFAULT_LINKS[0]
        answers[target["url"]] = 404
        session = _FakeSession(answers)
        report = lc.run_link_check(
            lc.DEFAULT_LINKS, session=session, rate_per_second=0
        )
        self.assertEqual(report["n_4xx"], 1)
        self.assertEqual(report["n_2xx"], len(lc.DEFAULT_LINKS) - 1)
        self.assertEqual(len(report["deploy_blocking_failures"]), 1)
        failure = report["deploy_blocking_failures"][0]
        self.assertEqual(failure["name"], target["name"])
        self.assertEqual(failure["url"], target["url"])
        self.assertEqual(failure["status"], 404)

    def test_one_5xx_lands_in_deploy_blocking_failures(self) -> None:
        answers: dict[str, int | Exception] = {
            entry["url"]: 200 for entry in lc.DEFAULT_LINKS
        }
        target = lc.DEFAULT_LINKS[1]
        answers[target["url"]] = 503
        session = _FakeSession(answers)
        report = lc.run_link_check(
            lc.DEFAULT_LINKS, session=session, rate_per_second=0
        )
        self.assertEqual(report["n_5xx"], 1)
        self.assertEqual(len(report["deploy_blocking_failures"]), 1)
        self.assertEqual(report["deploy_blocking_failures"][0]["status"], 503)

    def test_3xx_does_not_block_deploy(self) -> None:
        # The HTTP path follows redirects (`allow_redirects=True`), so
        # the FakeSession returning 301/302 is a degenerate case (the
        # real `requests.Session` would land on the final 2xx after
        # the redirect). But if a 3xx leaks through (e.g. an explicit
        # no-follow request), it MUST still be recorded — it's not a
        # deploy-blocking failure.
        answers: dict[str, int | Exception] = {
            entry["url"]: 200 for entry in lc.DEFAULT_LINKS
        }
        target = lc.DEFAULT_LINKS[2]
        answers[target["url"]] = 308
        session = _FakeSession(answers)
        report = lc.run_link_check(
            lc.DEFAULT_LINKS, session=session, rate_per_second=0
        )
        self.assertEqual(report["n_3xx"], 1)
        self.assertEqual(report["deploy_blocking_failures"], [])


class RunLinkCheckExceptionTests(unittest.TestCase):
    def test_connection_error_is_recorded_as_a_blocking_failure(self) -> None:
        import requests

        answers: dict[str, int | Exception] = {
            entry["url"]: 200 for entry in lc.DEFAULT_LINKS
        }
        target = lc.DEFAULT_LINKS[3]
        answers[target["url"]] = requests.ConnectionError("dns")
        session = _FakeSession(answers)
        report = lc.run_link_check(
            lc.DEFAULT_LINKS, session=session, rate_per_second=0
        )
        self.assertEqual(len(report["deploy_blocking_failures"]), 1)
        failure = report["deploy_blocking_failures"][0]
        self.assertEqual(failure["name"], target["name"])
        self.assertIsNone(failure["status"])
        self.assertIn("connection", failure["reason"])

    def test_timeout_is_recorded_as_a_blocking_failure(self) -> None:
        import requests

        answers: dict[str, int | Exception] = {
            entry["url"]: 200 for entry in lc.DEFAULT_LINKS
        }
        target = lc.DEFAULT_LINKS[4]
        answers[target["url"]] = requests.Timeout("slow")
        session = _FakeSession(answers)
        report = lc.run_link_check(
            lc.DEFAULT_LINKS, session=session, rate_per_second=0
        )
        self.assertEqual(len(report["deploy_blocking_failures"]), 1)
        self.assertEqual(report["deploy_blocking_failures"][0]["reason"], "timeout")


class RaiseIfFailedTests(unittest.TestCase):
    """Orchestrator-side helper that lifts a non-empty
    ``deploy_blocking_failures`` list into a single
    ``AtlasLinkCheckError`` per R-009."""

    def test_noop_when_no_failures(self) -> None:
        report = {
            "scope": "non-pubmed-record only (per FR-024 / R-013)",
            "checked_urls": list(lc.DEFAULT_LINKS),
            "n_total": 5,
            "n_2xx": 5,
            "n_3xx": 0,
            "n_4xx": 0,
            "n_5xx": 0,
            "deploy_blocking_failures": [],
        }
        # MUST NOT raise.
        lc.raise_if_failed(report)

    def test_raises_with_first_failure_url_status(self) -> None:
        failures = [
            {"name": "a", "url": "https://example.test/a", "status": 404, "reason": "404"},
            {"name": "b", "url": "https://example.test/b", "status": 500, "reason": "500"},
        ]
        report = {
            "scope": "non-pubmed-record only (per FR-024 / R-013)",
            "checked_urls": [],
            "n_total": 2,
            "n_2xx": 0,
            "n_3xx": 0,
            "n_4xx": 1,
            "n_5xx": 1,
            "deploy_blocking_failures": failures,
        }
        with self.assertRaises(exceptions.AtlasLinkCheckError) as ctx:
            lc.raise_if_failed(report)
        # The exception kwargs name the FIRST failing url + status so
        # the orchestrator's exit-code mapping (per
        # contracts/cli-build-atlas-package.md) gets a single
        # representative cause.
        self.assertEqual(ctx.exception.url, "https://example.test/a")
        self.assertEqual(ctx.exception.status, 404)


class RateLimitTests(unittest.TestCase):
    def test_sleep_is_called_between_requests_at_documented_rate(self) -> None:
        calls: list[float] = []

        def fake_sleep(seconds: float) -> None:
            calls.append(seconds)

        session = _FakeSession({entry["url"]: 200 for entry in lc.DEFAULT_LINKS})
        lc.run_link_check(
            lc.DEFAULT_LINKS,
            session=session,
            rate_per_second=3.0,
            sleep=fake_sleep,
        )
        # n URLs → n−1 inter-request sleeps. Each sleep is 1/rate seconds.
        self.assertEqual(len(calls), len(lc.DEFAULT_LINKS) - 1)
        for s in calls:
            self.assertAlmostEqual(s, 1.0 / 3.0, places=5)


if __name__ == "__main__":
    unittest.main()
