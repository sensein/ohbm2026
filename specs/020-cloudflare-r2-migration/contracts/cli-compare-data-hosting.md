# CLI Contract: `ohbmcli compare-data-hosting`

Probe the Dropbox-served and R2-served copies of each artifact for byte-parity,
HTTP Range support, and CORS, and write a pass/fail comparison report. This is
the auditable evidence for the deferred production-cutover decision (US3).

## Invocation

```bash
PYTHONPATH=src .venv/bin/python -m ohbm2026.cli compare-data-hosting \
  --registry path/to/registry.json \
  --dropbox-channel <dropbox-key> \
  --r2-channel <r2-key> \
  --origin https://abstractatlas.brainkb.org \
  [--report-out data/outputs/] \
  [--trust-recorded-sha256] \
  [--range-bytes 100]
```

The registry JSON is the value of `OHBM2026_UI_DATA_PACKAGE_URLS` (operator
exports it locally; never committed). Alternatively `--dropbox-url`/`--r2-url`
pairs per artifact may be passed directly for ad-hoc comparison.

## Arguments

| Flag | Type | Default | Meaning |
|---|---|---|---|
| `--registry` | path | required* | JSON registry of channels (value of the GH variable). |
| `--dropbox-channel` | str | required* | Channel key for the Dropbox side. |
| `--r2-channel` | str | required* | Channel key for the R2 side. |
| `--origin` | str | required | Origin used in the CORS probe (the production site origin). |
| `--report-out` | path | `data/outputs/` | Directory for the report. |
| `--trust-recorded-sha256` | flag | off | Skip downloads; compare each channel's recorded `sha256` (and R2 key) instead of re-hashing bytes. |
| `--range-bytes` | int | 100 | Size of the range probe window. |

\* `--registry`+channels OR explicit `--dropbox-url`/`--r2-url` per logical name.

## Behaviour (per logical artifact present on both sides)

1. **Range**: `GET` with `Range: bytes=0-<range-bytes-1>`. Pass = `206` + a
   `Content-Range` whose length matches. `200` (range ignored) = **fail**.
2. **CORS (range GET)**: `GET` with `Origin: <origin>` + a `Range` request
   header. Pass = response carries `Access-Control-Allow-Origin` equal to
   `<origin>` or `*`.
3. **CORS (revalidation)** — `revalidation_cors`: an `OPTIONS` preflight for the
   browser cache's conditional `HEAD` + `If-None-Match` revalidation
   (`Access-Control-Request-Method: HEAD`, `Access-Control-Request-Headers:
   if-none-match`). Pass = `2xx/3xx` + matching `Access-Control-Allow-Origin` +
   `HEAD` in `Access-Control-Allow-Methods` + `if-none-match` (or `*`) in
   `Access-Control-Allow-Headers`. This is a SEPARATE preflight from the range
   GET — a plain GET passing CORS does NOT imply it (the gap that let a
   missing-`If-None-Match` bucket rule ship and freeze warm-cache reloads).
4. **Byte-parity**: unless `--trust-recorded-sha256`, stream-download both URLs,
   sha256 each, compare. With the flag, compare recorded `sha256` values / R2
   key. Pass = hashes equal.
5. **Latency**: wall-time of the range probe, recorded (informational only).
6. Aggregate into `ArtifactComparison.pass` (byte-parity ∧ R2 range ∧ R2 CORS ∧
   R2 revalidation_cors ∧ R2 reachable) and the report's `overall_pass`.

A probe verdict that fails is **recorded** (`error` set), never omitted
(FR-015). A probe that cannot be attempted at all (malformed URL, channel
missing a required artifact) raises `HostingComparisonError`.

## Exit codes

| Code | Condition |
|---|---|
| 0 | `overall_pass == true` (every artifact byte-identical + R2 Range + R2 CORS OK). |
| 1 | `overall_pass == false` (report still written, listing each failure). |
| non-zero (>1) | `HostingComparisonError` — a probe could not be attempted. |

## Output

- Report JSON at `--report-out/data-hosting-comparison__<ts>.json`
  (schema: `comparison-report.schema.json`).
- A human summary table to stdout (per-artifact ✓/✗ for parity/Range/CORS).
