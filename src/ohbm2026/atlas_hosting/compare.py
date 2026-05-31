"""Dropbox-vs-R2 hosting comparison (US3).

Spec: ``specs/020-cloudflare-r2-migration/`` —
``contracts/cli-compare-data-hosting.md``,
``contracts/comparison-report.schema.json``.

Per logical artifact, probe both the Dropbox-served and R2-served URLs
for byte-parity, HTTP Range support, and CORS, and aggregate a pass/fail
report (FR-014/FR-015). A probe that *runs but fails* is RECORDED with an
``error`` (never omitted) and makes the artifact non-passing; a probe
that *cannot be attempted* (malformed URL, or a required artifact
present in only one channel) raises :class:`HostingComparisonError`.
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass
from typing import Callable, Optional

from ohbm2026.exceptions import HostingComparisonError

SCHEMA_VERSION = "data_hosting_comparison.v1"
_ORDER = ("ohbm2026", "neuroscape", "atlas", "neuroscape_vectors")
_REACHABLE_STATUSES = {200, 206, 301, 302, 303, 307, 308}

#: http_get(url, headers) -> response with .status_code, .headers, .content
HttpGet = Callable[[str, dict], object]


@dataclass
class EndpointProbe:
    url: str
    reachable: bool
    sha256: Optional[str]
    status: Optional[int]
    range_supported: bool
    cors_allowed: bool
    latency_ms: Optional[float]
    error: Optional[str]

    def to_dict(self) -> dict:
        return {
            "url": self.url,
            "reachable": self.reachable,
            "sha256": self.sha256,
            "status": self.status,
            "range_supported": self.range_supported,
            "cors_allowed": self.cors_allowed,
            "latency_ms": self.latency_ms,
            "error": self.error,
        }


@dataclass
class ArtifactComparison:
    logical_name: str
    dropbox: EndpointProbe
    r2: EndpointProbe
    byte_parity: bool
    passed: bool

    def to_dict(self) -> dict:
        return {
            "logical_name": self.logical_name,
            "dropbox": self.dropbox.to_dict(),
            "r2": self.r2.to_dict(),
            "byte_parity": self.byte_parity,
            "pass": self.passed,
        }


@dataclass
class ComparisonReport:
    generated_utc: str
    origin: str
    dropbox_channel: str
    r2_channel: str
    artifacts: list[ArtifactComparison]
    overall_pass: bool

    def to_dict(self) -> dict:
        return {
            "schema_version": SCHEMA_VERSION,
            "generated_utc": self.generated_utc,
            "origin": self.origin,
            "dropbox_channel": self.dropbox_channel,
            "r2_channel": self.r2_channel,
            "artifacts": [a.to_dict() for a in self.artifacts],
            "overall_pass": self.overall_pass,
        }


def _header(headers, name: str) -> Optional[str]:
    """Case-insensitive header lookup over a dict / CaseInsensitiveDict."""

    try:
        items = headers.items()
    except AttributeError:
        return None
    lowered = {str(k).lower(): v for k, v in items}
    return lowered.get(name.lower())


def _default_http_get(url: str, headers: dict):
    import requests

    return requests.get(url, headers=headers, timeout=30)


def probe_endpoint(
    url: str,
    *,
    origin: str,
    range_bytes: int = 100,
    compute_sha: bool = True,
    recorded_sha256: Optional[str] = None,
    http_get: HttpGet = _default_http_get,
) -> EndpointProbe:
    """Probe one URL for reachability, Range support, CORS, and (optionally)
    its content hash.

    A malformed URL is unattemptable → :class:`HostingComparisonError`.
    A network failure is a *recorded* failure (``reachable=False`` +
    ``error``), not raised.
    """

    if not isinstance(url, str) or not url.lower().startswith(("http://", "https://")):
        raise HostingComparisonError(
            f"malformed URL, cannot probe: {url!r}",
            url=str(url),
            probe="url",
            reason="malformed_url",
        )

    status: Optional[int] = None
    reachable = False
    range_supported = False
    cors_allowed = False
    latency_ms: Optional[float] = None
    error: Optional[str] = None

    started = time.perf_counter()
    try:
        resp = http_get(
            url,
            {"Range": f"bytes=0-{range_bytes - 1}", "Origin": origin},
        )
        latency_ms = (time.perf_counter() - started) * 1000.0
        status = int(getattr(resp, "status_code"))
        reachable = status in _REACHABLE_STATUSES or 200 <= status < 400
        content_range = _header(resp.headers, "content-range")
        range_supported = status == 206 and bool(content_range)
        acao = _header(resp.headers, "access-control-allow-origin")
        cors_allowed = acao is not None and acao in ("*", origin)
        if not range_supported:
            error = f"range not honored (status={status}, content-range={content_range!r})"
        elif not cors_allowed:
            error = f"CORS not allowed for origin {origin} (acao={acao!r})"
    except HostingComparisonError:
        raise
    except Exception as exc:  # noqa: BLE001 — a network/HTTP failure is a RECORDED verdict, not a raise
        error = f"{type(exc).__name__}: {exc}"

    sha256: Optional[str] = None
    if compute_sha and reachable and error is None:
        try:
            full = http_get(url, {"Origin": origin})
            sha256 = hashlib.sha256(getattr(full, "content")).hexdigest()
        except Exception as exc:  # noqa: BLE001 — recorded, not raised
            error = f"sha256 download failed: {type(exc).__name__}: {exc}"
    elif not compute_sha:
        sha256 = None  # recorded hash used by the caller instead

    return EndpointProbe(
        url=url,
        reachable=reachable,
        sha256=sha256,
        status=status,
        range_supported=range_supported,
        cors_allowed=cors_allowed,
        latency_ms=latency_ms,
        error=error,
    )


def compare_channels(
    *,
    dropbox_channel: dict,
    r2_channel: dict,
    origin: str,
    generated_utc: str,
    dropbox_channel_key: str = "",
    r2_channel_key: str = "",
    range_bytes: int = 100,
    trust_recorded_sha256: bool = False,
    http_get: HttpGet = _default_http_get,
) -> ComparisonReport:
    """Compare two registry channels and return a :class:`ComparisonReport`.

    Channels are ``{logical_name: {"url", "sha256"}}`` dicts. An artifact
    present in only ONE channel is unattemptable →
    :class:`HostingComparisonError`.
    """

    comparisons: list[ArtifactComparison] = []
    overall = True

    for logical in _ORDER:
        d = dropbox_channel.get(logical)
        r = r2_channel.get(logical)
        if d is None and r is None:
            continue  # neither channel carries it (e.g. a legacy no-vectors channel)
        if d is None or r is None:
            raise HostingComparisonError(
                f"artifact {logical!r} present in only one channel",
                probe="channel",
                reason="missing_in_one_channel",
            )

        d_probe = probe_endpoint(
            d["url"],
            origin=origin,
            range_bytes=range_bytes,
            compute_sha=not trust_recorded_sha256,
            recorded_sha256=d.get("sha256"),
            http_get=http_get,
        )
        r_probe = probe_endpoint(
            r["url"],
            origin=origin,
            range_bytes=range_bytes,
            compute_sha=not trust_recorded_sha256,
            recorded_sha256=r.get("sha256"),
            http_get=http_get,
        )

        d_sha = d_probe.sha256 or d.get("sha256")
        r_sha = r_probe.sha256 or r.get("sha256")
        byte_parity = bool(d_sha and r_sha and d_sha == r_sha)
        passed = bool(
            byte_parity
            and r_probe.range_supported
            and r_probe.cors_allowed
            and r_probe.reachable
        )
        comparisons.append(
            ArtifactComparison(logical, d_probe, r_probe, byte_parity, passed)
        )
        overall = overall and passed

    if not comparisons:
        raise HostingComparisonError(
            "no comparable artifacts across the two channels",
            probe="channel",
            reason="no_common_artifacts",
        )

    return ComparisonReport(
        generated_utc=generated_utc,
        origin=origin,
        dropbox_channel=dropbox_channel_key,
        r2_channel=r2_channel_key,
        artifacts=comparisons,
        overall_pass=overall,
    )
