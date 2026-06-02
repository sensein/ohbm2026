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

#: Spec 022 — `cf-cache-status` values that mean "served from the edge".
_EDGE_HIT = {"HIT", "REVALIDATED"}

#: http_request(method, url, headers) -> response with .status_code, .headers, .content
HttpRequest = Callable[[str, str, dict], object]


@dataclass
class EndpointProbe:
    url: str
    reachable: bool
    sha256: Optional[str]
    status: Optional[int]
    range_supported: bool
    cors_allowed: bool
    # CORS preflight for the browser cache's conditional revalidation
    # (HEAD + If-None-Match). A plain GET passing CORS does NOT imply this
    # passes — they're separate preflights (this is the gap that let the
    # If-None-Match CORS failure ship; see r2-storage-layout.md).
    revalidation_cors: bool
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
            "revalidation_cors": self.revalidation_cors,
            "latency_ms": self.latency_ms,
            "error": self.error,
        }


@dataclass
class CacheProbe:
    """Spec 022 — edge-cache evidence for one request (full or range).

    Issued cold→warm: the second (warm) request's ``cf-cache-status`` is the
    authoritative "served from the edge" signal; the two timings make the
    SC-003 latency drop an observed measurement. For a range probe,
    ``range_byte_parity`` confirms the cached 206 bytes match the origin's.
    """

    url: str
    kind: str  # "full" | "range"
    cf_cache_status: Optional[str]
    age: Optional[str]
    cache_control: Optional[str]
    cached: bool
    warmed: bool
    cold_ms: Optional[float]
    warm_ms: Optional[float]
    range_byte_parity: Optional[bool]
    flag: Optional[str]

    def to_dict(self) -> dict:
        return {
            "url": self.url,
            "kind": self.kind,
            "cf_cache_status": self.cf_cache_status,
            "age": self.age,
            "cache_control": self.cache_control,
            "cached": self.cached,
            "warmed": self.warmed,
            "cold_ms": self.cold_ms,
            "warm_ms": self.warm_ms,
            "range_byte_parity": self.range_byte_parity,
            "flag": self.flag,
        }


@dataclass
class ArtifactComparison:
    logical_name: str
    dropbox: EndpointProbe
    r2: EndpointProbe
    byte_parity: bool
    passed: bool
    #: Spec 022 — edge-cache evidence for the R2 endpoint (full + range),
    #: populated only when cache probing is requested; None otherwise so the
    #: Stage-20 report shape is unchanged when caching isn't being verified.
    r2_cache: Optional[list["CacheProbe"]] = None

    def to_dict(self) -> dict:
        out = {
            "logical_name": self.logical_name,
            "dropbox": self.dropbox.to_dict(),
            "r2": self.r2.to_dict(),
            "byte_parity": self.byte_parity,
            "pass": self.passed,
        }
        if self.r2_cache is not None:
            out["r2_cache"] = [c.to_dict() for c in self.r2_cache]
        return out


@dataclass
class ComparisonReport:
    generated_utc: str
    origin: str
    dropbox_channel: str
    r2_channel: str
    artifacts: list[ArtifactComparison]
    overall_pass: bool
    #: Spec 022 — aggregate edge-cache verdict for the R2 host: True iff every
    #: cache probe was served from the edge (warm HIT) with range byte-parity
    #: and no flags. None when cache probing wasn't requested (verdict absent →
    #: Stage-20 report shape unchanged). This is a SEPARATE verdict from
    #: `overall_pass` (byte-parity/CORS/Range), so a pre-rule "not yet cached"
    #: run doesn't fail the parity check.
    cache_effective: Optional[bool] = None

    def to_dict(self) -> dict:
        out = {
            "schema_version": SCHEMA_VERSION,
            "generated_utc": self.generated_utc,
            "origin": self.origin,
            "dropbox_channel": self.dropbox_channel,
            "r2_channel": self.r2_channel,
            "artifacts": [a.to_dict() for a in self.artifacts],
            "overall_pass": self.overall_pass,
        }
        if self.cache_effective is not None:
            out["cache_effective"] = self.cache_effective
        return out


def _header(headers, name: str) -> Optional[str]:
    """Case-insensitive header lookup over a dict / CaseInsensitiveDict."""

    try:
        items = headers.items()
    except AttributeError:
        return None
    lowered = {str(k).lower(): v for k, v in items}
    return lowered.get(name.lower())


def _default_http_request(method: str, url: str, headers: dict):
    import requests

    return requests.request(method, url, headers=headers, timeout=30)


def probe_endpoint(
    url: str,
    *,
    origin: str,
    range_bytes: int = 100,
    compute_sha: bool = True,
    recorded_sha256: Optional[str] = None,
    http_request: HttpRequest = _default_http_request,
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
    revalidation_cors = False
    latency_ms: Optional[float] = None
    error: Optional[str] = None

    started = time.perf_counter()
    try:
        resp = http_request(
            "GET",
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

    # CORS preflight for the browser cache's conditional revalidation:
    # an OPTIONS for a `HEAD` + `If-None-Match` request. A plain GET passing
    # CORS does NOT cover this — they're separate preflights, and the
    # If-None-Match one is what the loader's cache layer (cache.ts) actually
    # issues on a warm-cache reload. Probing it here closes the gap that let
    # the missing-`If-None-Match` CORS rule ship undetected.
    try:
        pf = http_request(
            "OPTIONS",
            url,
            {
                "Origin": origin,
                "Access-Control-Request-Method": "HEAD",
                "Access-Control-Request-Headers": "if-none-match",
            },
        )
        pf_status = int(getattr(pf, "status_code"))
        pf_acao = _header(pf.headers, "access-control-allow-origin")
        pf_methods = (_header(pf.headers, "access-control-allow-methods") or "").upper()
        pf_headers = (_header(pf.headers, "access-control-allow-headers") or "").lower()
        revalidation_cors = (
            200 <= pf_status < 400
            and pf_acao in ("*", origin)
            and "HEAD" in pf_methods
            and ("if-none-match" in pf_headers or "*" in pf_headers)
        )
        if reachable and not revalidation_cors:
            rv = (
                f"revalidation preflight not allowed (status={pf_status}, "
                f"acao={pf_acao!r}, allow-headers={pf_headers!r})"
            )
            error = f"{error} | {rv}" if error else rv
    except Exception as exc:  # noqa: BLE001 — recorded, not raised
        rv = f"revalidation preflight failed: {type(exc).__name__}: {exc}"
        error = f"{error} | {rv}" if error else rv

    # Verify byte-parity whenever the URL is REACHABLE — a CORS or Range
    # failure doesn't affect file integrity, so it must not block the hash
    # check (PR #53 review). Any download failure is appended to `error`,
    # not skipped. With `compute_sha=False` (--trust-recorded-sha256) the
    # caller compares the recorded hashes instead, so sha256 stays None.
    sha256: Optional[str] = None
    if compute_sha and reachable:
        try:
            full = http_request("GET", url, {"Origin": origin})
            sha256 = hashlib.sha256(getattr(full, "content")).hexdigest()
        except Exception as exc:  # noqa: BLE001 — recorded, not raised
            sha_err = f"sha256 download failed: {type(exc).__name__}: {exc}"
            error = f"{error} | {sha_err}" if error else sha_err

    return EndpointProbe(
        url=url,
        reachable=reachable,
        sha256=sha256,
        status=status,
        range_supported=range_supported,
        cors_allowed=cors_allowed,
        revalidation_cors=revalidation_cors,
        latency_ms=latency_ms,
        error=error,
    )


def _norm_status(s: Optional[str]) -> str:
    return (s or "").strip().upper()


def _cache_probe_one(
    url: str,
    *,
    origin: str,
    range_bytes: Optional[int],
    http_request: HttpRequest,
) -> CacheProbe:
    """One cold→warm cache probe (full GET when ``range_bytes`` is None, else a
    Range GET). The warm ``cf-cache-status`` is the edge-served signal; a
    range probe also checks cached-vs-origin byte-parity. A network failure is
    a RECORDED flag, never raised (Principle VI)."""

    kind = "range" if range_bytes is not None else "full"
    headers = {"Origin": origin}
    if range_bytes is not None:
        headers["Range"] = f"bytes=0-{range_bytes - 1}"

    cf = age = cc = None
    cold_ms = warm_ms = None
    cached = warmed = False
    parity: Optional[bool] = None
    flag: Optional[str] = None
    try:
        t0 = time.perf_counter()
        cold = http_request("GET", url, headers)
        cold_ms = (time.perf_counter() - t0) * 1000.0
        t1 = time.perf_counter()
        warm = http_request("GET", url, headers)
        warm_ms = (time.perf_counter() - t1) * 1000.0

        cold_code = int(getattr(cold, "status_code", 0) or 0)
        warm_code = int(getattr(warm, "status_code", 0) or 0)
        expected = 206 if range_bytes is not None else 200
        cold_status = _norm_status(_header(cold.headers, "cf-cache-status"))
        warm_status = _norm_status(_header(warm.headers, "cf-cache-status"))
        cf = _header(warm.headers, "cf-cache-status")
        age = _header(warm.headers, "age")
        cc = _header(warm.headers, "cache-control")
        cached = warm_status in _EDGE_HIT
        warmed = cold_status not in _EDGE_HIT and warm_status in _EDGE_HIT
        # PR #62 review: an error/unexpected status is NOT a valid cache hit even
        # if the edge cached it (a cached 403/404/500 must flag, not pass). Force
        # `cached=False` so the aggregate verdict fails too.
        if cold_code != expected or warm_code != expected:
            cached = False
            flag = (
                f"unexpected status ({kind}: cold={cold_code}, warm={warm_code}, "
                f"expected={expected})"
            )
        elif not cached:
            flag = f"not edge-cached ({kind}: cf-cache-status={cf!r})"
        if range_bytes is not None:
            cold_body = getattr(cold, "content", None)
            warm_body = getattr(warm, "content", None)
            if cold_body is not None and warm_body is not None:
                parity = cold_body == warm_body
                if not parity:
                    pmsg = "range byte mismatch (cached 206 != origin 206)"
                    flag = f"{flag} | {pmsg}" if flag else pmsg
            else:
                pmsg = "missing response content for range parity check"
                flag = f"{flag} | {pmsg}" if flag else pmsg
    except Exception as exc:  # noqa: BLE001 — recorded verdict, not raised
        flag = f"cache probe failed: {type(exc).__name__}: {exc}"

    return CacheProbe(
        url=url,
        kind=kind,
        cf_cache_status=cf,
        age=age,
        cache_control=cc,
        cached=cached,
        warmed=warmed,
        cold_ms=cold_ms,
        warm_ms=warm_ms,
        range_byte_parity=parity,
        flag=flag,
    )


def probe_cache(
    url: str,
    *,
    origin: str,
    range_bytes: int = 100,
    http_request: HttpRequest = _default_http_request,
) -> list[CacheProbe]:
    """Edge-cache evidence for one URL: a full GET and an inner-table Range,
    each issued cold→warm. Returns ``[full_probe, range_probe]``."""

    return [
        _cache_probe_one(url, origin=origin, range_bytes=None, http_request=http_request),
        _cache_probe_one(url, origin=origin, range_bytes=range_bytes, http_request=http_request),
    ]


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
    cache_probe: bool = False,
    http_request: Optional[HttpRequest] = None,
) -> ComparisonReport:
    """Compare two registry channels and return a :class:`ComparisonReport`.

    Channels are ``{logical_name: {"url", "sha256"}}`` dicts. An artifact
    present in only ONE channel is unattemptable →
    :class:`HostingComparisonError`.

    When ``http_request`` is not injected, a shared :class:`requests.Session`
    is used so the probes reuse one TCP/TLS connection (keep-alive) instead of
    reconnecting per request (PR #53 review). The session's connection pool is
    released when the function returns (single CLI use).
    """

    if http_request is None:
        import requests

        _session = requests.Session()
        http_request = lambda method, url, headers: _session.request(  # noqa: E731
            method, url, headers=headers, timeout=30
        )

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
            http_request=http_request,
        )
        r_probe = probe_endpoint(
            r["url"],
            origin=origin,
            range_bytes=range_bytes,
            compute_sha=not trust_recorded_sha256,
            recorded_sha256=r.get("sha256"),
            http_request=http_request,
        )

        d_sha = d_probe.sha256 or d.get("sha256")
        r_sha = r_probe.sha256 or r.get("sha256")
        byte_parity = bool(d_sha and r_sha and d_sha == r_sha)
        passed = bool(
            byte_parity
            and r_probe.range_supported
            and r_probe.cors_allowed
            and r_probe.revalidation_cors
            and r_probe.reachable
        )
        r2_cache = (
            probe_cache(
                r["url"], origin=origin, range_bytes=range_bytes, http_request=http_request
            )
            if cache_probe
            else None
        )
        comparisons.append(
            ArtifactComparison(logical, d_probe, r_probe, byte_parity, passed, r2_cache)
        )
        overall = overall and passed

    if not comparisons:
        raise HostingComparisonError(
            "no comparable artifacts across the two channels",
            probe="channel",
            reason="no_common_artifacts",
        )

    # Spec 022 — aggregate edge-cache verdict (separate from `overall_pass`):
    # every cache probe must be a warm HIT, range-parity-clean, and flag-free.
    cache_effective: Optional[bool] = None
    if cache_probe:
        cache_effective = all(
            cp.flag is None
            and cp.cached
            and (cp.kind != "range" or cp.range_byte_parity)
            for a in comparisons
            if a.r2_cache
            for cp in a.r2_cache
        )

    return ComparisonReport(
        generated_utc=generated_utc,
        origin=origin,
        dropbox_channel=dropbox_channel_key,
        r2_channel=r2_channel_key,
        artifacts=comparisons,
        overall_pass=overall,
        cache_effective=cache_effective,
    )
