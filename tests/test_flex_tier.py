"""Tests for `src/ohbm2026/flex_tier.py`.

Verifies the retry/fallback semantics:
- Flex call succeeds → flex tier used, no fallback.
- Flex call times out → standard-tier retry → success.
- Both tiers fail → typed EnrichmentError raised.
- Flex disabled → only standard tier attempted.
"""

from __future__ import annotations

import unittest

import openai

from ohbm2026 import flex_tier
from ohbm2026.exceptions import EnrichmentError


class _FakeResponse:
    """Mimics the SDK response shape just enough for the helper's
    return value to carry timing info."""
    def __init__(self, marker: str) -> None:
        self.marker = marker


class CallWithFlexFallbackTests(unittest.TestCase):
    def test_flex_success_uses_flex_tier_no_fallback(self) -> None:
        calls = []

        def fake_call(*, service_tier: str, timeout: float):
            calls.append(service_tier)
            return _FakeResponse(service_tier)

        result = flex_tier.call_with_flex_fallback(
            fake_call, flex_enabled=True, timeout_seconds=5.0, component="test",
        )
        self.assertEqual(result.tier_used, "flex")
        self.assertEqual(result.attempts, 1)
        self.assertFalse(result.flex_timed_out)
        self.assertEqual(calls, ["flex"])

    def test_flex_timeout_falls_back_to_standard(self) -> None:
        calls = []

        def fake_call(*, service_tier: str, timeout: float):
            calls.append(service_tier)
            if service_tier == "flex":
                raise openai.APITimeoutError(request=None)
            return _FakeResponse(service_tier)

        result = flex_tier.call_with_flex_fallback(
            fake_call, flex_enabled=True, timeout_seconds=5.0, component="figures",
        )
        self.assertEqual(result.tier_used, "standard")
        self.assertTrue(result.flex_timed_out)
        self.assertEqual(result.attempts, 2)
        self.assertEqual(calls, ["flex", "standard"])

    def test_both_tiers_fail_raises_enrichment_error(self) -> None:
        def fake_call(*, service_tier: str, timeout: float):
            raise openai.APITimeoutError(request=None)

        with self.assertRaises(EnrichmentError) as ctx:
            flex_tier.call_with_flex_fallback(
                fake_call, flex_enabled=True, timeout_seconds=5.0, component="claims",
            )
        self.assertIn("claims", str(ctx.exception))
        self.assertIn("retry budget exhausted", str(ctx.exception))

    def test_flex_disabled_uses_standard_only(self) -> None:
        calls = []

        def fake_call(*, service_tier: str, timeout: float):
            calls.append(service_tier)
            return _FakeResponse(service_tier)

        result = flex_tier.call_with_flex_fallback(
            fake_call, flex_enabled=False, timeout_seconds=5.0, component="figures",
        )
        self.assertEqual(result.tier_used, "standard")
        self.assertEqual(calls, ["standard"])
        self.assertFalse(result.flex_timed_out)

    def test_default_timeouts_module_constants(self) -> None:
        # Sanity: constants exist and are positive.
        self.assertGreater(flex_tier.DEFAULT_FIGURES_TIMEOUT_SECONDS, 0)
        self.assertGreater(flex_tier.DEFAULT_CLAIMS_TIMEOUT_SECONDS, 0)
        self.assertEqual(flex_tier.DEFAULT_FIGURES_TIMEOUT_SECONDS, 120)
        self.assertEqual(flex_tier.DEFAULT_CLAIMS_TIMEOUT_SECONDS, 180)

    def test_connection_error_also_retries(self) -> None:
        calls = []

        def fake_call(*, service_tier: str, timeout: float):
            calls.append(service_tier)
            if service_tier == "flex":
                raise openai.APIConnectionError(request=None)
            return _FakeResponse(service_tier)

        result = flex_tier.call_with_flex_fallback(
            fake_call, flex_enabled=True, timeout_seconds=5.0, component="figures",
        )
        self.assertEqual(result.tier_used, "standard")
        self.assertTrue(result.flex_timed_out)


if __name__ == "__main__":
    unittest.main()
