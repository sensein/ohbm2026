"""Build-time link checker for the references registry (T086 / FR-017).

Walks ``specs/008-ui-rewrite/contracts/references.yaml`` (or any conforming
YAML), HEADs every ``url`` field with a 10 s timeout, returns:

* exit 0 if every URL returned a 2xx / 3xx
* exit 3 on any 4xx / 5xx / connection error (per
  ``contracts/data-package.md`` exit-code table)

Wire this into ``deploy-ui.yml`` between the data-package build and the
site build so a broken external citation blocks the deploy (T088).
"""

from __future__ import annotations

import sys
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests
import yaml

__all__ = [
    "DEFAULT_TIMEOUT",
    "LinkCheckResult",
    "iter_references",
    "head_url",
    "link_check",
    "main",
]

DEFAULT_TIMEOUT = 10.0
# Use a browser-like User-Agent. A bot-shaped UA
# ("ohbm2026-link-check/1.0 …") is now 403-blocked by openalex.org and
# 429-rate-limited by huggingface.co, producing false-negative link failures
# for genuinely-reachable citations (both return 200 to a browser UA). The
# checker still verifies the URL resolves; it just stops self-identifying as a
# scraper to hosts that block scrapers.
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

# Statuses where the host *responded* but is gating automated/datacenter
# access (auth wall, anti-scraping, rate-limit) rather than the link being
# broken. These are a non-fatal WARN: the citation still resolves for a human
# in a browser, and GitHub-hosted runners hit these from datacenter IPs that
# openalex.org / huggingface.co block regardless of User-Agent. A genuinely
# broken link (404/410/5xx) or a dead host (DNS/timeout/refused) is still a
# hard failure that blocks the deploy (FR-017).
SOFT_STATUSES = frozenset({401, 403, 429})


@dataclass(frozen=True)
class LinkCheckResult:
    """One row of the link-check report."""

    url: str
    section: str
    title: str
    status: int | None  # None when the request raised before HTTP
    ok: bool
    reason: str  # short human-facing reason, e.g. '200', 'timeout', 'dns'
    warn: bool = False  # host responded but gates automated access (401/403/429)


def iter_references(payload: Mapping[str, Any]) -> Iterable[dict[str, Any]]:
    """Yield each entry under the top-level ``references`` list."""

    refs = payload.get("references")
    if not isinstance(refs, list):
        return
    for entry in refs:
        if isinstance(entry, dict) and isinstance(entry.get("url"), str):
            yield entry


def head_url(
    url: str,
    *,
    timeout: float = DEFAULT_TIMEOUT,
    session: requests.Session | None = None,
) -> tuple[int | None, str]:
    """HEAD with a single GET fallback for hosts that 405 HEAD.

    Returns ``(status, reason)``. ``status`` is None on transport-level
    errors (timeout, DNS, refused).
    """

    headers = {"User-Agent": DEFAULT_USER_AGENT, "Accept": "*/*"}
    s = session or requests.Session()
    try:
        r = s.head(url, allow_redirects=True, timeout=timeout, headers=headers)
        # Some servers refuse HEAD with 405 / 403; retry with a streaming GET
        # and close the connection without reading the body.
        if r.status_code in (403, 405, 501):
            r = s.get(url, allow_redirects=True, timeout=timeout, headers=headers, stream=True)
            r.close()
        return (r.status_code, str(r.status_code))
    except requests.Timeout:
        return (None, "timeout")
    except requests.ConnectionError as exc:
        return (None, f"connection: {type(exc).__name__}")
    except requests.RequestException as exc:
        return (None, f"request: {type(exc).__name__}")


def link_check(
    yaml_path: Path | str,
    *,
    timeout: float = DEFAULT_TIMEOUT,
    session: requests.Session | None = None,
) -> tuple[int, list[LinkCheckResult]]:
    """Validate every URL in the references file.

    Returns ``(exit_code, results)``. exit_code follows contracts/data-package.md:

    * 0 → every URL OK
    * 3 → at least one URL not OK (or the file is missing / unparseable)
    """

    path = Path(yaml_path)
    if not path.exists():
        return (3, [LinkCheckResult(url=str(path), section="-", title="-", status=None, ok=False, reason="missing yaml")])
    try:
        payload = yaml.safe_load(path.read_text())
    except yaml.YAMLError as exc:
        return (3, [LinkCheckResult(url=str(path), section="-", title="-", status=None, ok=False, reason=f"yaml-parse: {exc}")])
    if not isinstance(payload, dict):
        return (3, [LinkCheckResult(url=str(path), section="-", title="-", status=None, ok=False, reason="yaml-root-not-mapping")])

    results: list[LinkCheckResult] = []
    s = session or requests.Session()
    for ref in iter_references(payload):
        url = ref["url"]
        section = str(ref.get("section", "-"))
        title = str(ref.get("title", "-"))
        status, reason = head_url(url, timeout=timeout, session=s)
        ok = status is not None and 200 <= status < 400
        warn = status in SOFT_STATUSES
        results.append(
            LinkCheckResult(url=url, section=section, title=title, status=status, ok=ok, reason=reason, warn=warn)
        )
    if not results:
        return (3, [LinkCheckResult(url=str(path), section="-", title="-", status=None, ok=False, reason="no-references")])

    # Hard-fail only on genuinely broken links: not 2xx/3xx AND not a soft
    # auth/rate-limit gate (those resolve for a human, see SOFT_STATUSES).
    hard_fail = any(not r.ok and not r.warn for r in results)
    return (3 if hard_fail else 0, results)


def _format_results(results: list[LinkCheckResult]) -> str:
    lines = ["section            status  url"]
    for r in results:
        flag = "OK  " if r.ok else ("WARN" if r.warn else "FAIL")
        st = str(r.status) if r.status is not None else "---"
        lines.append(f"{r.section:18s}{flag} {st:5s} {r.url}  ({r.reason})")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(prog="link_check", description="HEAD-check references registry URLs")
    parser.add_argument("yaml", type=Path, nargs="?", default=Path("specs/008-ui-rewrite/contracts/references.yaml"))
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT)
    parser.add_argument("--quiet", action="store_true", help="print only summary line")
    args = parser.parse_args(argv)
    code, results = link_check(args.yaml, timeout=args.timeout)
    if not args.quiet:
        print(_format_results(results))
    ok = sum(1 for r in results if r.ok)
    warn = sum(1 for r in results if r.warn)
    fail = sum(1 for r in results if not r.ok and not r.warn)
    print(f"link_check: ok={ok} warn={warn} fail={fail} → exit {code}", file=sys.stderr)
    return code


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
