"""Tests for the Stage 20 Dropbox-vs-R2 comparison (US3).

Spec: ``specs/020-cloudflare-r2-migration/`` —
``contracts/cli-compare-data-hosting.md``,
``contracts/comparison-report.schema.json``. No network: a fake
``http_request(method, url, headers)`` returns canned responses keyed by URL.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

import jsonschema

from ohbm2026.atlas_hosting import compare
from ohbm2026.exceptions import HostingComparisonError

ORIGIN = "https://abstractatlas.brainkb.org"
_SCHEMA_PATH = (
    Path(__file__).resolve().parent.parent
    / "specs/020-cloudflare-r2-migration/contracts/comparison-report.schema.json"
)


class FakeResp:
    def __init__(self, status_code: int, headers: dict | None = None, content: bytes = b"") -> None:
        self.status_code = status_code
        self.headers = headers or {}
        self.content = content


def _ok_range(content_len: int = 12345) -> FakeResp:
    return FakeResp(
        206,
        {"Content-Range": f"bytes 0-99/{content_len}", "Access-Control-Allow-Origin": ORIGIN},
    )


def _ok_preflight() -> FakeResp:
    # A correctly-configured bucket: the conditional-HEAD preflight is allowed.
    return FakeResp(
        204,
        {
            "Access-Control-Allow-Origin": ORIGIN,
            "Access-Control-Allow-Methods": "GET, HEAD",
            "Access-Control-Allow-Headers": "range, if-none-match",
        },
    )


def _make_http(table: dict[str, dict]):
    """table: {url: {"range": FakeResp, "full": FakeResp, "preflight"?: FakeResp}}.

    OPTIONS defaults to an ALLOWED preflight unless a per-url ``preflight`` is
    given (so tests that don't care about revalidation CORS still pass).
    """

    def http_request(method: str, url: str, headers: dict):
        entry = table[url]
        if method == "OPTIONS":
            return entry.get("preflight", _ok_preflight())
        if "Range" in headers:
            return entry["range"]
        return entry.get("full", entry["range"])

    return http_request


def _channel(url: str, sha: str) -> dict:
    return {"url": url, "sha256": sha}


class GoodComparisonTests(unittest.TestCase):
    def test_matching_endpoints_pass(self) -> None:
        d_url, r_url = "https://dropbox.example/o.parquet", "https://aadata.cirrusscience.org/abc/o.parquet"
        content = b"PARQUET-BYTES"
        table = {
            d_url: {"range": _ok_range(), "full": FakeResp(200, {}, content)},
            r_url: {"range": _ok_range(), "full": FakeResp(200, {}, content)},
        }
        report = compare.compare_channels(
            dropbox_channel={"ohbm2026": _channel(d_url, "x")},
            r2_channel={"ohbm2026": _channel(r_url, "x")},
            origin=ORIGIN,
            generated_utc="2026-05-31T12:00:00+00:00",
            http_request=_make_http(table),
        )
        self.assertTrue(report.overall_pass)
        art = report.artifacts[0]
        self.assertTrue(art.byte_parity)
        self.assertTrue(art.r2.range_supported)
        self.assertTrue(art.r2.cors_allowed)
        self.assertTrue(art.r2.revalidation_cors)
        self.assertTrue(art.passed)

    def test_report_validates_against_schema(self) -> None:
        url = "https://aadata.cirrusscience.org/abc/o.parquet"
        d_url = "https://dropbox.example/o.parquet"
        content = b"PARQUET-BYTES"
        table = {
            d_url: {"range": _ok_range(), "full": FakeResp(200, {}, content)},
            url: {"range": _ok_range(), "full": FakeResp(200, {}, content)},
        }
        report = compare.compare_channels(
            dropbox_channel={"ohbm2026": _channel(d_url, "x")},
            r2_channel={"ohbm2026": _channel(url, "x")},
            origin=ORIGIN,
            generated_utc="2026-05-31T12:00:00+00:00",
            http_request=_make_http(table),
        )
        schema = json.loads(_SCHEMA_PATH.read_text())
        jsonschema.validate(instance=report.to_dict(), schema=schema)


class FailureVerdictTests(unittest.TestCase):
    def _run(self, r2_range: FakeResp, r2_full: FakeResp, d_content=b"SAME"):
        d_url, r_url = "https://dropbox.example/o.parquet", "https://aadata.cirrusscience.org/abc/o.parquet"
        table = {
            d_url: {"range": _ok_range(), "full": FakeResp(200, {}, d_content)},
            r_url: {"range": r2_range, "full": r2_full},
        }
        return compare.compare_channels(
            dropbox_channel={"ohbm2026": _channel(d_url, "x")},
            r2_channel={"ohbm2026": _channel(r_url, "x")},
            origin=ORIGIN,
            generated_utc="2026-05-31T12:00:00+00:00",
            http_request=_make_http(table),
        )

    def test_range_ignored_200_fails_and_is_recorded(self) -> None:
        report = self._run(
            r2_range=FakeResp(200, {"Access-Control-Allow-Origin": ORIGIN}, b"SAME"),
            r2_full=FakeResp(200, {}, b"SAME"),
        )
        self.assertFalse(report.overall_pass)
        self.assertFalse(report.artifacts[0].r2.range_supported)
        self.assertIsNotNone(report.artifacts[0].r2.error)

    def test_cors_missing_fails_and_is_recorded(self) -> None:
        report = self._run(
            r2_range=FakeResp(206, {"Content-Range": "bytes 0-99/9"}),  # no ACAO
            r2_full=FakeResp(200, {}, b"SAME"),
        )
        self.assertFalse(report.overall_pass)
        self.assertFalse(report.artifacts[0].r2.cors_allowed)
        self.assertIsNotNone(report.artifacts[0].r2.error)

    def test_byte_parity_mismatch_fails(self) -> None:
        report = self._run(
            r2_range=_ok_range(),
            r2_full=FakeResp(200, {}, b"DIFFERENT"),
        )
        self.assertFalse(report.overall_pass)
        self.assertFalse(report.artifacts[0].byte_parity)


class RevalidationCorsTests(unittest.TestCase):
    """The gap that shipped: range + CORS + parity all pass on a plain GET,
    but the conditional-HEAD (If-None-Match) preflight is NOT allowed — which
    is what froze warm-cache reloads. The compare must catch it."""

    def _run_with_preflight(self, preflight: FakeResp):
        d_url, r_url = "https://dropbox.example/o.parquet", "https://aadata.cirrusscience.org/abc/o.parquet"
        same = b"SAME"
        table = {
            d_url: {"range": _ok_range(), "full": FakeResp(200, {}, same)},
            r_url: {
                "range": _ok_range(),  # range OK
                "full": FakeResp(200, {}, same),  # parity OK
                "preflight": preflight,  # ← the revalidation preflight under test
            },
        }
        return compare.compare_channels(
            dropbox_channel={"ohbm2026": _channel(d_url, "x")},
            r2_channel={"ohbm2026": _channel(r_url, "x")},
            origin=ORIGIN,
            generated_utc="2026-05-31T12:00:00+00:00",
            http_request=_make_http(table),
        )

    def test_preflight_403_fails_despite_range_cors_parity_ok(self) -> None:
        report = self._run_with_preflight(FakeResp(403, {}))
        art = report.artifacts[0]
        self.assertTrue(art.byte_parity and art.r2.range_supported and art.r2.cors_allowed)
        self.assertFalse(art.r2.revalidation_cors)
        self.assertFalse(art.passed)  # caught despite GET-level CORS passing
        self.assertIsNotNone(art.r2.error)

    def test_preflight_missing_if_none_match_header_fails(self) -> None:
        # 204 + ACAO + HEAD allowed, but If-None-Match NOT in allow-headers
        # (exactly the bucket misconfig we hit: only `range` was allowed).
        report = self._run_with_preflight(
            FakeResp(
                204,
                {
                    "Access-Control-Allow-Origin": ORIGIN,
                    "Access-Control-Allow-Methods": "GET, HEAD",
                    "Access-Control-Allow-Headers": "range",
                },
            )
        )
        self.assertFalse(report.artifacts[0].r2.revalidation_cors)
        self.assertFalse(report.artifacts[0].passed)


class TrustRecordedShaTests(unittest.TestCase):
    def test_no_download_uses_recorded_hashes(self) -> None:
        d_url, r_url = "https://dropbox.example/o.parquet", "https://aadata.cirrusscience.org/abc/o.parquet"

        # A full GET would raise — proving it is NOT called under
        # --trust-recorded-sha256. Range + OPTIONS still happen.
        def http_request(method, url, headers):
            if method == "OPTIONS":
                return _ok_preflight()
            if "Range" not in headers:
                raise AssertionError("full GET should not happen under trust_recorded_sha256")
            return _ok_range()

        report = compare.compare_channels(
            dropbox_channel={"ohbm2026": _channel(d_url, "deadbeef")},
            r2_channel={"ohbm2026": _channel(r_url, "deadbeef")},
            origin=ORIGIN,
            generated_utc="2026-05-31T12:00:00+00:00",
            trust_recorded_sha256=True,
            http_request=http_request,
        )
        self.assertTrue(report.artifacts[0].byte_parity)  # recorded shas equal
        self.assertIsNone(report.artifacts[0].r2.sha256)  # not downloaded


class UnattemptableProbeTests(unittest.TestCase):
    def test_malformed_url_raises(self) -> None:
        with self.assertRaises(HostingComparisonError):
            compare.compare_channels(
                dropbox_channel={"ohbm2026": _channel("not-a-url", "x")},
                r2_channel={"ohbm2026": _channel("https://aadata.cirrusscience.org/a/o.parquet", "x")},
                origin=ORIGIN,
                generated_utc="2026-05-31T12:00:00+00:00",
                http_request=_make_http({}),
            )

    def test_artifact_missing_in_one_channel_raises(self) -> None:
        d_url = "https://dropbox.example/o.parquet"
        with self.assertRaises(HostingComparisonError):
            compare.compare_channels(
                dropbox_channel={
                    "ohbm2026": _channel(d_url, "x"),
                    "neuroscape": _channel("https://dropbox.example/n.parquet", "y"),
                },
                r2_channel={"ohbm2026": _channel("https://aadata.cirrusscience.org/a/o.parquet", "x")},
                origin=ORIGIN,
                generated_utc="2026-05-31T12:00:00+00:00",
                http_request=_make_http({}),
            )

    def test_no_common_artifacts_raises(self) -> None:
        with self.assertRaises(HostingComparisonError):
            compare.compare_channels(
                dropbox_channel={},
                r2_channel={},
                origin=ORIGIN,
                generated_utc="2026-05-31T12:00:00+00:00",
                http_request=_make_http({}),
            )


if __name__ == "__main__":
    unittest.main()
