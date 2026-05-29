#!/usr/bin/env bash
#
# Resolve the data-package parquet URLs for a build from the keyed JSON
# registry variable, selecting the channel the checked-out branch declares.
#
# WHY this exists (spec 019): production and every PR preview used to read
# the same flat `vars.OHBM2026_UI_DATA_PACKAGE_URL_*` strings, so swapping
# the data for one surface (e.g. a PR evaluating a new parquet layout)
# silently swapped it for ALL surfaces — they share the same Dropbox links.
# Instead we keep ONE registry variable, `OHBM2026_UI_DATA_PACKAGE_URLS`,
# whose top-level keys are named data sets ("channels"). The active key is
# committed per-branch in `site/data-channel.json`, so the choice travels
# with the code: a PR's preview, and later its sandbox/prod deploy, resolve
# whichever channel that branch declares. Distinct channels point at
# distinct URLs, so multiple in-flight PRs never overwrite each other's or
# production's data.
#
# Registry shape (value of vars.OHBM2026_UI_DATA_PACKAGE_URLS):
#   {
#     "<channel-key>": {
#       "ohbm2026":           {"url": "https://…/ohbm2026.parquet?…",  "sha256": "…"},
#       "neuroscape":         {"url": "https://…/neuroscape.parquet?…"},
#       "atlas":              {"url": "https://…/atlas.parquet?…"},
#       "neuroscape_vectors": {"url": "https://…/neuroscape_vectors.parquet?…"}
#     },
#     ...
#   }
#
# Emits to $GITHUB_ENV (consumed by the SvelteKit build):
#   VITE_DATA_PACKAGE_URL_OHBM2026 / _NEUROSCAPE / _ATLAS  (required)
#   VITE_DATA_PACKAGE_URL_NEUROSCAPE_VECTORS               (optional — unset
#       leaves the loader on its designed KNN-only semantic fallback)
#
# Inputs (environment):
#   DATA_URLS_REGISTRY  — the raw JSON of vars.OHBM2026_UI_DATA_PACKAGE_URLS
#   GITHUB_ENV          — set by Actions; the file we append resolved vars to
# Inputs (filesystem):
#   site/data-channel.json — { "key": "<channel-key>" }
#
# Fails loudly (Constitution VI): a missing registry, missing channel file,
# unknown key, or missing required URL is a misconfiguration and aborts the
# build — never a silent fallback to stale/wrong data.

set -euo pipefail

CHANNEL_FILE="${DATA_CHANNEL_FILE:-site/data-channel.json}"

if [ -z "${DATA_URLS_REGISTRY:-}" ]; then
  echo "::error::vars.OHBM2026_UI_DATA_PACKAGE_URLS is unset — cannot resolve any data channel"
  exit 1
fi
if [ ! -f "$CHANNEL_FILE" ]; then
  echo "::error::$CHANNEL_FILE missing — the branch must declare its data channel key"
  exit 1
fi

KEY="$(jq -r '.key // empty' "$CHANNEL_FILE")"
if [ -z "$KEY" ]; then
  echo "::error::$CHANNEL_FILE has no string \".key\""
  exit 1
fi
echo "Data channel key (from $CHANNEL_FILE): $KEY"

channel="$(jq -ec --arg k "$KEY" '.[$k] // empty' <<<"$DATA_URLS_REGISTRY" || true)"
if [ -z "$channel" ]; then
  available="$(jq -r 'keys | join(", ")' <<<"$DATA_URLS_REGISTRY" 2>/dev/null || echo '<unparseable>')"
  echo "::error::channel '$KEY' not present in OHBM2026_UI_DATA_PACKAGE_URLS (available: $available)"
  exit 1
fi

emit() {
  # emit <registry-subkey> <VITE env name> <required|optional>
  local subkey="$1" envname="$2" mode="$3" url
  url="$(jq -r --arg k "$subkey" '.[$k].url // empty' <<<"$channel")"
  if [ -z "$url" ]; then
    if [ "$mode" = "required" ]; then
      echo "::error::channel '$KEY' is missing a required url for '$subkey'"
      exit 1
    fi
    echo "  (optional) $subkey: no url in channel '$KEY' — leaving $envname unset"
    return 0
  fi
  printf '%s=%s\n' "$envname" "$url" >>"$GITHUB_ENV"
  echo "  $envname  ←  $KEY.$subkey"
}

emit ohbm2026           VITE_DATA_PACKAGE_URL_OHBM2026          required
emit neuroscape         VITE_DATA_PACKAGE_URL_NEUROSCAPE        required
emit atlas              VITE_DATA_PACKAGE_URL_ATLAS             required
emit neuroscape_vectors VITE_DATA_PACKAGE_URL_NEUROSCAPE_VECTORS optional
