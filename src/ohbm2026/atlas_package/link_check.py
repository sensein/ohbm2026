"""Build-time link check for the Stage 15 atlas package.

Spec: ``specs/015-neuroscape-context/`` — FR-024 + research R-013.

Stage 15 narrows the build-time link-check scope to a **small fixed
set of non-PubMed-record URLs**:

- the NeuroScape Zenodo release page (where the build inputs came from)
- the NeuroScape citation URL
- the OHBM 2026 site root
- the cross-conference landing page (the new bare root)
- the NCBI E-utilities base URL (the endpoint the SvelteKit subsite
  hits at view time per R-015)

**Per-PubMed-record URL health is NOT checked at build time** —
~461K HEAD requests against NCBI is infeasible (violates NCBI's rate
limits and adds ~55 hours per build). Dead per-record URLs surface
at view time via the runtime PubMed fetch's offline-state UI.

Public surface:

- :data:`DEFAULT_LINKS` — the five-URL set above as
  ``[{"name": ..., "url": ...}, ...]``.
- :func:`run_link_check` — HEAD-check each URL, return the provenance
  block documented in ``contracts/cli-build-atlas-package.md``.
- :func:`raise_if_failed` — orchestrator-side helper that lifts a
  non-empty ``deploy_blocking_failures`` list into a single
  :class:`AtlasLinkCheckError` per R-009.

The HTTP transport mirrors the existing Stage-6 ``link_check.py``
conventions (``HEAD`` with a GET fallback for hosts that 405 HEAD; a
shared ``requests.Session`` for connection reuse; a documented
default 10 s timeout).
"""

from __future__ import annotations

import time
from typing import Any, Callable, Sequence

import requests

from ohbm2026.exceptions import AtlasLinkCheckError

__all__ = [
    "DEFAULT_LINKS",
    "DEFAULT_TIMEOUT",
    "run_link_check",
    "raise_if_failed",
]


DEFAULT_TIMEOUT = 10.0
DEFAULT_USER_AGENT = "ohbm2026-atlas-link-check/1.0 (+https://github.com/sensein/ohbm2026)"


# The five URLs documented in R-013. The Zenodo and citation URLs
# point at the canonical NeuroScape v1.0.1 record; the others are
# self-hosted. Operators rebuild Stage 15 against a new NeuroScape
# release by updating these constants (and re-running the centroid
# table derivation per CA-007).
DEFAULT_LINKS: tuple[dict[str, str], ...] = (
    {
        "name": "neuroscape_zenodo",
        "url": "https://zenodo.org/records/14865161",
    },
    {
        "name": "neuroscape_citation",
        "url": "https://doi.org/10.5281/zenodo.14865161",
    },
    {
        "name": "ohbm2026_site",
        "url": "https://abstractatlas.brainkb.org/ohbm2026/",
    },
    {
        "name": "cross_conference_landing",
        "url": "https://abstractatlas.brainkb.org/",
    },
    {
        # NCBI's E-utilities bare directory returns 400 to any
        # request (it requires a specific endpoint). Use `einfo.fcgi`
        # with `db=pubmed` — the cheapest valid call: returns 200
        # via the GET fallback inside `_head()` (NCBI's HEAD is 405).
        # This still verifies that (a) the host is reachable, (b)
        # the entrez/eutils path is live, and (c) PubMed is a
        # configured E-utilities database. The runtime fetch (R-015)
        # hits `efetch.fcgi`; success on `einfo.fcgi` implies the
        # E-utilities surface is up.
        "name": "ncbi_eutils_base",
        "url": "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/einfo.fcgi?db=pubmed",
    },
)


def _head(
    url: str,
    *,
    session: Any,
    timeout: float,
) -> tuple[int | None, str]:
    """HEAD with a single GET fallback. Returns ``(status, reason)``."""

    headers = {"User-Agent": DEFAULT_USER_AGENT, "Accept": "*/*"}
    try:
        r = session.head(url, allow_redirects=True, timeout=timeout, headers=headers)
        if r.status_code in (403, 405, 501):
            r = session.get(
                url,
                allow_redirects=True,
                timeout=timeout,
                headers=headers,
                stream=True,
            )
            r.close()
        return (r.status_code, str(r.status_code))
    except requests.Timeout:
        return (None, "timeout")
    except requests.ConnectionError as exc:
        return (None, f"connection: {type(exc).__name__}")
    except requests.RequestException as exc:
        return (None, f"request: {type(exc).__name__}")


def run_link_check(
    links: Sequence[dict[str, str]] = DEFAULT_LINKS,
    *,
    session: Any | None = None,
    timeout: float = DEFAULT_TIMEOUT,
    rate_per_second: float = 3.0,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    """HEAD-check every URL in *links* and return the provenance block.

    The shape of the returned dict matches the ``link_check`` field
    in :data:`contracts/cli-build-atlas-package.md`:

    .. code-block:: python

        {
            "scope": "non-pubmed-record only (per FR-024 / R-013)",
            "checked_urls": [{"name": ..., "url": ...}, ...],
            "n_total": int,
            "n_2xx": int,
            "n_3xx": int,
            "n_4xx": int,
            "n_5xx": int,
            "deploy_blocking_failures": [
                {"name": ..., "url": ..., "status": int | None, "reason": str},
                ...
            ],
        }

    Set ``rate_per_second=0`` to disable the inter-request sleep
    (used by unit tests to avoid wall-clock dependency).

    Failure classification:

    - 2xx, 3xx → not a failure (3xx exists for the no-follow case;
      `allow_redirects=True` normally lands on the final 2xx).
    - 4xx, 5xx → deploy-blocking failure.
    - Transport-level error (timeout, DNS, connection) → deploy-
      blocking failure with ``status=None``.
    """

    s = session or requests.Session()

    counts = {"n_total": 0, "n_2xx": 0, "n_3xx": 0, "n_4xx": 0, "n_5xx": 0}
    failures: list[dict[str, Any]] = []

    inter_request_sleep = 1.0 / rate_per_second if rate_per_second > 0 else 0.0

    for i, entry in enumerate(links):
        if i > 0 and inter_request_sleep > 0:
            sleep(inter_request_sleep)
        status, reason = _head(entry["url"], session=s, timeout=timeout)
        counts["n_total"] += 1
        if status is None:
            failures.append(
                {
                    "name": entry["name"],
                    "url": entry["url"],
                    "status": None,
                    "reason": reason,
                }
            )
        elif 200 <= status < 300:
            counts["n_2xx"] += 1
        elif 300 <= status < 400:
            counts["n_3xx"] += 1
        elif 400 <= status < 500:
            counts["n_4xx"] += 1
            failures.append(
                {
                    "name": entry["name"],
                    "url": entry["url"],
                    "status": status,
                    "reason": reason,
                }
            )
        elif 500 <= status < 600:
            counts["n_5xx"] += 1
            failures.append(
                {
                    "name": entry["name"],
                    "url": entry["url"],
                    "status": status,
                    "reason": reason,
                }
            )
        else:
            # Out-of-range status (e.g. 1xx, 6xx) — record as a
            # blocking failure rather than silently ignoring.
            failures.append(
                {
                    "name": entry["name"],
                    "url": entry["url"],
                    "status": status,
                    "reason": reason,
                }
            )

    return {
        "scope": "non-pubmed-record only (per FR-024 / R-013)",
        "checked_urls": [dict(entry) for entry in links],
        **counts,
        "deploy_blocking_failures": failures,
    }


def raise_if_failed(report: dict[str, Any]) -> None:
    """Raise :class:`AtlasLinkCheckError` iff the report records any failure.

    The orchestrator calls this at the end of the link-check pass
    per R-009. Carries the FIRST failing url + status in the raised
    exception so the exit-code mapping in
    ``contracts/cli-build-atlas-package.md`` gets a single
    representative cause.
    """

    failures = report.get("deploy_blocking_failures") or []
    if not failures:
        return
    first = failures[0]
    raise AtlasLinkCheckError(
        f"{len(failures)} non-pubmed-record URL(s) failed at build time",
        url=first.get("url"),
        status=first.get("status"),
    )
