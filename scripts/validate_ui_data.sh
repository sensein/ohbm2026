#!/usr/bin/env bash
# Validate every shard of a UI data package against the LinkML schema.
#
# Usage:
#   scripts/validate_ui_data.sh [DATA_ROOT]
#
# DATA_ROOT defaults to `site/static/data/` — the locally-built package.
# Exits 0 if every shard validates, 1 otherwise.

set -euo pipefail

ROOT="${1:-site/static/data}"
SCH="specs/008-ui-rewrite/contracts/ui_data.linkml.yaml"
STAGE10_SCH="specs/010-export-redesign/contracts/shards.linkml.yaml"
LINKML="${LINKML:-.venv/bin/linkml-validate}"
PYTHON="${PYTHON:-.venv/bin/python}"

# Stage-10 lint gate (FR-201 + FR-202). Runs first so a malformed
# Stage-10 schema fails fast before the per-shard JSON validation
# (which still validates against the Stage-6 schema for the legacy
# json-shards format).
if [[ -f "$STAGE10_SCH" ]] && [[ -x "$PYTHON" ]]; then
  echo "lint: $STAGE10_SCH"
  "$PYTHON" scripts/lint_schema.py "$STAGE10_SCH"
fi

if [[ ! -d "$ROOT" ]]; then
  echo "no data dir at $ROOT" >&2
  exit 1
fi
if [[ ! -x "$LINKML" ]]; then
  echo "linkml-validate not found at $LINKML — install via 'uv pip install linkml'" >&2
  exit 1
fi

PASS=0
FAIL=0
declare -a FAILED=()

check() {
  local cls="$1" path="$2"
  local out
  if [[ ! -f "$path" ]]; then return; fi
  out=$("$LINKML" --schema "$SCH" --target-class "$cls" "$path" 2>&1 | grep -E "ERROR|No issues" | head -1 || true)
  if [[ "$out" == *"No issues found"* ]]; then
    PASS=$((PASS+1))
  else
    FAIL=$((FAIL+1))
    FAILED+=("$cls / $path: $out")
  fi
}

check Manifest             "$ROOT/manifest.json"
check AbstractsShard       "$ROOT/abstracts.json"
check AuthorsShard         "$ROOT/authors.json"
check EnrichmentShard      "$ROOT/enrichment.json"
check MinilmVectorsSidecar "$ROOT/search/minilm_vectors.build_info.json"
for f in "$ROOT"/cells/*.json; do check CellShard "$f"; done
for f in "$ROOT"/topics/*.json; do check TopicShard "$f"; done
for f in "$ROOT"/neighbors/*.json; do check NeighborsShard "$f"; done

echo "passed: $PASS  failed: $FAIL"
if [[ $FAIL -gt 0 ]]; then
  printf '  FAIL: %s\n' "${FAILED[@]}"
  exit 1
fi
