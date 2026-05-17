#!/usr/bin/env bash
# T007 / Stage 6 — fetch_ui_inputs.sh
#
# Materialize the data package the SvelteKit site consumes. The script has
# three modes (priority order):
#
# 1. OHBM2026_UI_DATA_PACKAGE_URL set → download + extract a pre-built
#    `data/` tarball directly into `site/static/data/`. This is the
#    production CI path: a local operator builds the package once via
#    `scripts/build_ui_data.py`, places the tarball at a shared URL
#    (Dropbox, S3, release artifact, …), and the deploy workflow consumes
#    it. No Stage 1–4 inputs need to land in CI; `build_ui_data.py` is
#    skipped downstream. Exit 0 + write a marker file.
#
# 2. Stage 1–4 inputs present in the working tree → exit 0 (local dev or
#    a runner that mounts the inputs). Downstream `build_ui_data.py`
#    builds the shards from scratch.
#
# 3. Neither → exit 2 with a clear error pointing operators at the docs.
#    Downstream skips the data-package build; the site still ships with
#    the build-info-only placeholder.
#
# Per CA-007, no state-key is hardcoded; the rollup state-key is discovered
# inside `build_ui_data.py` via `ohbm2026.ui_data.state_key`.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

UI_DATA_DIR="site/static/data"

# --- Mode 1: download pre-built tarball ---------------------------------
if [[ -n "${OHBM2026_UI_DATA_PACKAGE_URL:-}" ]]; then
	echo "fetch_ui_inputs.sh: downloading pre-built data package from \$OHBM2026_UI_DATA_PACKAGE_URL"
	mkdir -p "$UI_DATA_DIR"
	tmp=$(mktemp -d)
	trap "rm -rf '$tmp'" EXIT
	url="$OHBM2026_UI_DATA_PACKAGE_URL"
	# Sanity check that we got binary content, not an HTML interstitial
	# (Dropbox / Google Drive both wrap shared links in HTML now). If the
	# downloaded file doesn't gzip-decompress we exit early so the workflow
	# fails loudly instead of falling back to stale gh-pages data.
	if ! curl -fsSL "$url" -o "$tmp/package.tar.gz"; then
		echo "fetch_ui_inputs.sh: download failed from $url" >&2
		exit 3
	fi
	if ! gzip -t "$tmp/package.tar.gz" 2>/dev/null; then
		echo "fetch_ui_inputs.sh: downloaded file is not a valid gzip archive — the URL probably returned an HTML interstitial" >&2
		echo "  first 200 bytes follow:" >&2
		head -c 200 "$tmp/package.tar.gz" >&2
		echo "" >&2
		exit 5
	fi
	# Optional sha256 verify when OHBM2026_UI_DATA_PACKAGE_SHA256 is set.
	if [[ -n "${OHBM2026_UI_DATA_PACKAGE_SHA256:-}" ]]; then
		actual=$(shasum -a 256 "$tmp/package.tar.gz" | awk '{print $1}')
		if [[ "$actual" != "$OHBM2026_UI_DATA_PACKAGE_SHA256" ]]; then
			echo "fetch_ui_inputs.sh: sha256 mismatch — expected $OHBM2026_UI_DATA_PACKAGE_SHA256, got $actual" >&2
			exit 4
		fi
		echo "fetch_ui_inputs.sh: sha256 verified: $actual"
	fi
	# Extract — the tarball contains a top-level `data/` directory; we want
	# its contents to land directly under `site/static/data/`, so strip the
	# leading component.
	rm -rf "$UI_DATA_DIR"
	mkdir -p "$UI_DATA_DIR"
	tar -xzf "$tmp/package.tar.gz" -C "$UI_DATA_DIR" --strip-components=1
	echo "fetch_ui_inputs.sh: extracted $(find "$UI_DATA_DIR" -type f | wc -l | tr -d ' ') files into $UI_DATA_DIR"
	# Marker file so the deploy workflow knows to skip the local build_ui_data.py step.
	touch "$UI_DATA_DIR/.fetched-from-package"
	exit 0
fi

# --- Mode 2: raw inputs already in the working tree ---------------------
REQUIRED_PATHS=(
	"data/primary/abstracts.json"
	"data/primary/abstracts_withdrawn.json"
	"data/primary/authors.json"
	"data/primary/abstracts_enriched.sqlite"
	"data/outputs/analysis"
)

missing=()
for path in "${REQUIRED_PATHS[@]}"; do
	if [[ ! -e "$path" ]]; then
		missing+=("$path")
	fi
done

if [[ ${#missing[@]} -eq 0 ]]; then
	echo "fetch_ui_inputs.sh: Stage 1–4 inputs present locally; build_ui_data.py will run."
	exit 0
fi

# --- Mode 3: neither ----------------------------------------------------
echo "fetch_ui_inputs.sh: no data source available." >&2
echo "" >&2
echo "Required (mode 1 — package URL):" >&2
echo "  OHBM2026_UI_DATA_PACKAGE_URL=<url to ui-data-<state-key>.tar.gz>" >&2
echo "    Optional: OHBM2026_UI_DATA_PACKAGE_SHA256=<sha256 hex>" >&2
echo "" >&2
echo "OR (mode 2 — local inputs):" >&2
for path in "${missing[@]}"; do
	echo "  $path (missing)" >&2
done
echo "" >&2
echo "Local dev: see specs/008-ui-rewrite/quickstart.md." >&2
echo "CI: set OHBM2026_UI_DATA_PACKAGE_URL as a repo secret or workflow var." >&2
exit 2
