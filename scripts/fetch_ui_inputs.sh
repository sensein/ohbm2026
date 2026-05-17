#!/usr/bin/env bash
# T007 / Stage 6 — fetch_ui_inputs.sh
#
# The GitHub Action calls this script to materialize the Stage 1–4 inputs that
# scripts/build_ui_data.py consumes (corpus + authors + enriched + analysis
# rollup + minilm bundles). These artifacts live outside the repo (Constitution
# II: no committed data).
#
# Per CA-007, this script MUST NOT hardcode any state-key. The downstream
# builder discovers the active state-key at build time via
# `ohbm2026.ui_data.state_key`.
#
# Local dev: skip this script and follow specs/008-ui-rewrite/quickstart.md
# to populate the inputs manually from your existing pipeline runs.
#
# CI: this script is the integration point with whatever storage strategy the
# repo adopts (DVC, GitHub release artifact, S3, etc.). For now it's a
# placeholder that exits 0 IF the inputs already exist and 2 otherwise, with a
# clear error pointing operators to the docs.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

REQUIRED_PATHS=(
	"data/primary/abstracts.json"
	"data/primary/abstracts_withdrawn.json"
	"data/primary/authors.json"
	"data/primary/abstracts_enriched.sqlite"
	"data/outputs/analysis"
	"data/outputs/embeddings/minilm"
)

missing=()
for path in "${REQUIRED_PATHS[@]}"; do
	if [[ ! -e "$path" ]]; then
		missing+=("$path")
	fi
done

if [[ ${#missing[@]} -gt 0 ]]; then
	echo "fetch_ui_inputs.sh: required inputs missing:" >&2
	for path in "${missing[@]}"; do
		echo "  - $path" >&2
	done
	echo "" >&2
	echo "Local dev: follow specs/008-ui-rewrite/quickstart.md (Prerequisites)." >&2
	echo "CI: wire this script to your artifact-store fetch (DVC / release / S3)." >&2
	exit 2
fi

echo "fetch_ui_inputs.sh: all required inputs present; nothing to fetch."
