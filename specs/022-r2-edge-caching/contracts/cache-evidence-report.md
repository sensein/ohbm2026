# Contract: cache-evidence in `compare-data-hosting`

**Surface**: `ohbmcli compare-data-hosting` (`atlas_hosting/compare.py` + `cli.py`), extending the existing comparison report (`data/outputs/data-hosting-comparison__<ts>.json`).

## Inputs

- The R2 host base URL (`R2_PUBLIC_BASE_URL`) + a known object key (a published parquet) and a representative inner-table byte range (reuse the Range probe the command already issues).
- Injected `http_request(method, url, headers)` (already the seam in `compare.py`) so the logic is unit-testable with mocks.

## Behavior

| # | Rule |
|---|------|
| C1 | For a representative **full GET** and at least one **inner-table Range** request, the command MUST capture `cf-cache-status`, `age`, and `cache-control` from the response. |
| C2 | Each probe MUST be issued **twice** (cold → warm); the report records both so a first-request MISS is distinguished from a persistent BYPASS. |
| C2a | The command MUST record the wall-clock duration of the cold and warm probes (`cold_ms`/`warm_ms`) so the SC-003 latency drop is an observed measurement (not an assertion). |
| C3 | A warm response with `cf-cache-status` ∈ {DYNAMIC, BYPASS} or absent MUST be **flagged** as not-cache-effective (FR-006) — never silently passed. |
| C4 | For the Range probe, the command MUST verify **byte-parity** between the cached 206 partial and the origin/cold 206 partial for the same range (FR-007); a mismatch is a flag. |
| C5 | The command MUST preserve the existing reachability / Range-honored / CORS / If-None-Match probes (no regression to Stage 20 evidence). |
| C6 | Network/credential absence is surfaced explicitly (skip/guard with a clear message), never a silent "cache OK" (CA-006/CA-007). |
| C7 | The aggregate result MUST make the before/after auditable: a host that is bypassing cache yields a clearly-flagged report (and a non-zero or explicitly-failing aggregate), so "rule worked" is provable. |

## Output

- The existing timestamped comparison JSON gains a `cache` section per probed URL/kind with the [data-model](../data-model.md) fields (`cf_cache_status`, `age`, `cache_control`, `cached`, `warmed`, `cold_ms`, `warm_ms`, `range_byte_parity`, `flag`).
- Human-readable summary line(s) stating whether the host is edge-cache-effective.

## Out of scope

- Changing which channel the site uses (FR-009). This command only reports evidence for the R2 host.
