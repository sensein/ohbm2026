"""Unit tests for the Stage-6 link checker (T083 / T084).

Uses the `responses` library to mock HTTP HEAD / GET so the tests are
hermetic — no network IO, no external host dependencies.
"""

from __future__ import annotations

import unittest
from pathlib import Path

import requests.exceptions
import responses

from ohbm2026.ui_data.link_check import link_check, head_url


GOOD_YAML = """
references:
  - section: stage1
    title: Some good ref
    url: https://example.org/good
  - section: stage2
    title: Another good ref
    url: https://example.com/also-good
"""

BAD_YAML = """
references:
  - section: stage1
    title: Good
    url: https://example.org/ok
  - section: stage1
    title: Broken
    url: https://example.org/dead
"""

EMPTY_YAML = """
references: []
"""


class HeadUrlTests(unittest.TestCase):
    """`head_url` returns (status, reason) without raising."""

    @responses.activate
    def test_200_head_passes(self) -> None:
        responses.add(responses.HEAD, "https://x.example/ok", status=200)
        status, reason = head_url("https://x.example/ok")
        self.assertEqual(status, 200)
        self.assertEqual(reason, "200")

    @responses.activate
    def test_405_head_falls_back_to_get(self) -> None:
        # First HEAD returns 405; the module retries with GET.
        responses.add(responses.HEAD, "https://x.example/strict", status=405)
        responses.add(responses.GET, "https://x.example/strict", status=200, body="<html>")
        status, reason = head_url("https://x.example/strict")
        self.assertEqual(status, 200)


class LinkCheckTests(unittest.TestCase):
    def _write_yaml(self, body: str) -> Path:
        path = Path("/tmp/link-check-fixture.yaml")
        path.write_text(body)
        return path

    @responses.activate
    def test_passes_clean_yaml(self) -> None:
        responses.add(responses.HEAD, "https://example.org/good", status=200)
        responses.add(responses.HEAD, "https://example.com/also-good", status=301, headers={"Location": "https://example.com/landing"})
        responses.add(responses.HEAD, "https://example.com/landing", status=200)
        code, results = link_check(self._write_yaml(GOOD_YAML))
        self.assertEqual(code, 0, f"expected exit 0, got {code} with results={results}")
        self.assertEqual(len(results), 2)
        self.assertTrue(all(r.ok for r in results))

    @responses.activate
    def test_blocks_4xx_url(self) -> None:
        responses.add(responses.HEAD, "https://example.org/ok", status=200)
        responses.add(responses.HEAD, "https://example.org/dead", status=404)
        code, results = link_check(self._write_yaml(BAD_YAML))
        self.assertEqual(code, 3)
        self.assertEqual(sum(1 for r in results if not r.ok), 1)
        self.assertEqual([r for r in results if not r.ok][0].url, "https://example.org/dead")

    @responses.activate
    def test_blocks_5xx_url(self) -> None:
        body = """references:
- section: x
  title: server-error
  url: https://example.org/sad
"""
        responses.add(responses.HEAD, "https://example.org/sad", status=503)
        code, results = link_check(self._write_yaml(body))
        self.assertEqual(code, 3)
        self.assertEqual(results[0].status, 503)
        self.assertFalse(results[0].ok)

    @responses.activate
    def test_blocks_connection_error(self) -> None:
        body = """references:
- section: x
  title: refused
  url: https://example.org/refused
"""
        responses.add(responses.HEAD, "https://example.org/refused", body=requests.exceptions.ConnectionError("nope"))
        code, results = link_check(self._write_yaml(body))
        self.assertEqual(code, 3)
        self.assertIsNone(results[0].status)
        self.assertFalse(results[0].ok)

    @responses.activate
    def test_403_bot_block_is_soft_warn_not_fatal(self) -> None:
        # openalex.org-style: HEAD 403, GET fallback also 403 (datacenter-IP /
        # bot block). The host responded so the link resolves — it must NOT fail
        # the build; it's a WARN, exit 0.
        body = """references:
- section: x
  title: bot-blocked
  url: https://example.org/blocked
"""
        responses.add(responses.HEAD, "https://example.org/blocked", status=403)
        responses.add(responses.GET, "https://example.org/blocked", status=403)
        code, results = link_check(self._write_yaml(body))
        self.assertEqual(code, 0)
        self.assertEqual(results[0].status, 403)
        self.assertFalse(results[0].ok)
        self.assertTrue(results[0].warn)

    @responses.activate
    def test_429_rate_limit_is_soft_warn_not_fatal(self) -> None:
        body = """references:
- section: x
  title: rate-limited
  url: https://example.org/throttled
"""
        responses.add(responses.HEAD, "https://example.org/throttled", status=429)
        code, results = link_check(self._write_yaml(body))
        self.assertEqual(code, 0)
        self.assertEqual(results[0].status, 429)
        self.assertTrue(results[0].warn)

    def test_missing_yaml_is_fatal(self) -> None:
        code, _ = link_check(Path("/tmp/does-not-exist.yaml"))
        self.assertEqual(code, 3)

    def test_empty_references_is_fatal(self) -> None:
        code, results = link_check(self._write_yaml(EMPTY_YAML))
        self.assertEqual(code, 3)
        self.assertEqual(results[0].reason, "no-references")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
