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


class CacheProbeTests(unittest.TestCase):
    """Spec 022 (US3) — edge-cache evidence: cf-cache-status classification,
    cold→warm timing, BYPASS flagging, and range byte-parity."""

    def _seq_http(self, statuses, bodies=None):
        """A stateful mock returning responses in call order, with a
        per-call cf-cache-status (and optional body)."""

        calls = {"i": 0}

        def http_request(method, url, headers):
            i = calls["i"]
            calls["i"] += 1
            st = statuses[min(i, len(statuses) - 1)]
            body = (bodies[i] if bodies and i < len(bodies) else b"DATA")
            code = 206 if "Range" in headers else 200
            hdrs = {
                "cf-cache-status": st,
                "age": "7",
                "cache-control": "public, max-age=31536000, immutable",
            }
            return FakeResp(code, hdrs, body)

        return http_request

    def test_warm_hit_is_cached_warmed_and_parity_clean(self) -> None:
        # call order: full cold, full warm, range cold, range warm
        http = self._seq_http(["MISS", "HIT", "MISS", "HIT"])
        full, rng = compare.probe_cache("https://h/x", origin=ORIGIN, http_request=http)
        self.assertTrue(full.cached)
        self.assertTrue(full.warmed)
        self.assertIsNone(full.flag)
        self.assertIsNotNone(full.cold_ms)
        self.assertIsNotNone(full.warm_ms)
        self.assertTrue(rng.cached)
        self.assertTrue(rng.range_byte_parity)
        self.assertIsNone(rng.flag)
        self.assertEqual(full.cache_control, "public, max-age=31536000, immutable")

    def test_bypass_is_flagged_not_cached(self) -> None:
        http = self._seq_http(["DYNAMIC", "DYNAMIC", "BYPASS", "BYPASS"])
        full, rng = compare.probe_cache("https://h/x", origin=ORIGIN, http_request=http)
        self.assertFalse(full.cached)
        self.assertIsNotNone(full.flag)
        self.assertFalse(rng.cached)
        self.assertIsNotNone(rng.flag)

    def test_unexpected_status_is_flagged_not_cached(self) -> None:
        # A range request that returns 200 (not 206) — even cached as HIT — is
        # not a valid range cache hit and must flag (PR #62 review).
        def http(method, url, headers):
            return FakeResp(200, {"cf-cache-status": "HIT"}, b"DATA")

        full, rng = compare.probe_cache("https://h/x", origin=ORIGIN, http_request=http)
        self.assertTrue(full.cached)  # full expected 200, got 200 + HIT → ok
        self.assertFalse(rng.cached)  # range expected 206, got 200 → not a hit
        self.assertIn("unexpected status", rng.flag or "")

    def test_range_byte_mismatch_is_flagged(self) -> None:
        # full cold/warm fine; range cold vs warm bodies DIFFER → parity False
        http = self._seq_http(
            ["HIT", "HIT", "HIT", "HIT"],
            bodies=[b"AAAA", b"AAAA", b"COLDBYTES", b"WARMBYTES"],
        )
        _full, rng = compare.probe_cache("https://h/x", origin=ORIGIN, http_request=http)
        self.assertFalse(rng.range_byte_parity)
        self.assertIsNotNone(rng.flag)

    def test_compare_channels_cache_effective_aggregate(self) -> None:
        d_url, r_url = "https://dropbox.example/o.parquet", "https://aadata.cirrusscience.org/abc/o.parquet"
        content = b"SAME"
        hit = {
            "cf-cache-status": "HIT",
            "cache-control": "public, max-age=31536000, immutable",
        }
        r_range = FakeResp(
            206,
            {"Content-Range": "bytes 0-99/12345", "Access-Control-Allow-Origin": ORIGIN, **hit},
            content,
        )
        r_full = FakeResp(200, {**hit}, content)
        table = {
            d_url: {"range": _ok_range(), "full": FakeResp(200, {}, content)},
            r_url: {"range": r_range, "full": r_full},
        }
        report = compare.compare_channels(
            dropbox_channel={"ohbm2026": _channel(d_url, "x")},
            r2_channel={"ohbm2026": _channel(r_url, "x")},
            origin=ORIGIN,
            generated_utc="2026-05-31T12:00:00+00:00",
            cache_probe=True,
            http_request=_make_http(table),
        )
        self.assertTrue(report.cache_effective)
        self.assertIn("cache_effective", report.to_dict())
        self.assertIsNotNone(report.artifacts[0].r2_cache)

    def test_cache_effective_absent_by_default(self) -> None:
        # cache_probe defaults False → no cache section (Stage-20 shape kept).
        d_url, r_url = "https://dropbox.example/o.parquet", "https://aadata.cirrusscience.org/abc/o.parquet"
        content = b"SAME"
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
        self.assertIsNone(report.cache_effective)
        self.assertNotIn("cache_effective", report.to_dict())
        self.assertNotIn("r2_cache", report.to_dict()["artifacts"][0])


if __name__ == "__main__":
    unittest.main()
