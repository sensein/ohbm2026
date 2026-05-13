#!/usr/bin/env bash
# Constitution lint — automatable subset of OHBM 2026 Pipeline Constitution checks.
#
# Modes:
#   --staged (default; what .githooks/pre-commit runs): scan staged diff +
#            tracked files for principle violations
#   --full   (CI / manual sweep): scan the whole working tree exhaustively
#
# Covers (necessary, not sufficient):
#   II  no tracked files under gitignored data/export/cache roots
#   V   no token-shaped strings in the staged diff (or working tree in --full)
#   VI  no bare 'except:' in src/, no '--no-verify' in committed code
#
# Principles I, III, IV, VII, VIII require human judgment and are NOT
# automated here. See .specify/memory/constitution.md.
#
# Exits 0 on clean, 1 on any violation, 2 on usage/environment error.

set -euo pipefail

mode="${1:---staged}"

repo_root="$(git rev-parse --show-toplevel 2>/dev/null || true)"
if [[ -z "${repo_root}" ]]; then
  echo "constitution-check: not inside a git repository" >&2
  exit 2
fi
cd "${repo_root}"

case "${mode}" in
  --staged|--full) ;;
  *)
    echo "constitution-check: unknown mode '${mode}' (use --staged or --full)" >&2
    exit 2
    ;;
esac

violations=0

# ── Principle II: no tracked files under gitignored data/export/cache roots ──
data_roots=(data export tmp archive memory/archive .claude)
tracked_bad="$(git ls-files -- "${data_roots[@]}" 2>/dev/null || true)"
if [[ -n "${tracked_bad}" ]]; then
  echo "constitution-check: Principle II violation — tracked files under gitignored data roots:" >&2
  printf '  %s\n' ${tracked_bad} >&2
  violations=$(( violations + 1 ))
fi

# ── Principle V: token-shaped strings ──
# Patterns chosen to be high-signal: known issuer prefixes + length, PEM
# headers. The leading (^|[^A-Za-z0-9_]) guard rejects matches mid-word
# (e.g. "task-formats-..." which would otherwise hit "sk-formats-...").
secret_patterns='(^|[^A-Za-z0-9_])(sk-[A-Za-z0-9_-]{20,}|sk-ant-[A-Za-z0-9_-]{20,}|ghp_[A-Za-z0-9]{20,}|gho_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|AKIA[A-Z0-9]{16}|xox[baprs]-[A-Za-z0-9-]{20,})|-----BEGIN [A-Z ]*PRIVATE KEY-----'

# Files exempt from the secret scan: this lint, the constitution itself
# (which names example patterns in prose), CLAUDE.md, README.md, the
# behavioral test (which constructs synthetic token-shaped fixtures),
# and spec/plan/task docs under specs/ (which describe prohibited
# patterns as part of documenting the rule).
secret_excludes=(
  ':!**/constitution-check.sh'
  ':!**/constitution.md'
  ':!CONSTITUTION.md'
  ':!CLAUDE.md'
  ':!README.md'
  ':!**/test_constitution_check.py'
  ':!specs/**'
)

if [[ "${mode}" == "--staged" ]]; then
  secret_input="$(git diff --cached -U0 -- "${secret_excludes[@]}" || true)"
else
  secret_input="$(git grep -nE "${secret_patterns}" -- "${secret_excludes[@]}" 2>/dev/null || true)"
fi

if [[ -n "${secret_input}" ]]; then
  hits="$(echo "${secret_input}" | grep -nE "${secret_patterns}" || true)"
  if [[ -n "${hits}" ]]; then
    echo "constitution-check: Principle V violation — token-shaped string detected:" >&2
    echo "${hits}" >&2
    violations=$(( violations + 1 ))
  fi
fi

# ── Principle VI: no bare 'except:' in src/ ──
if [[ -d src ]]; then
  bare_except="$(git grep -nE '^[[:space:]]*except[[:space:]]*:' -- ':(glob)src/**/*.py' 2>/dev/null || true)"
  if [[ -n "${bare_except}" ]]; then
    echo "constitution-check: Principle VI violation — bare 'except:' in src/:" >&2
    echo "${bare_except}" >&2
    violations=$(( violations + 1 ))
  fi
fi

# ── Principle VI: no '--no-verify' in committed code ──
no_verify_excludes=(
  ':!docs/**'
  ':!**/constitution-check.sh'
  ':!**/constitution.md'
  ':!CONSTITUTION.md'
  ':!CLAUDE.md'
  ':!README.md'
  ':!**/test_constitution_check.py'
  ':!.githooks/**'
  ':!.agents/**'
  ':!.specify/templates/**'
  ':!.specify/extensions/**'
  ':!specs/**'
)
no_verify="$(git grep -nE -- '--no-verify' -- "${no_verify_excludes[@]}" 2>/dev/null || true)"
if [[ -n "${no_verify}" ]]; then
  echo "constitution-check: Principle VI violation — '--no-verify' present in committed code:" >&2
  echo "${no_verify}" >&2
  violations=$(( violations + 1 ))
fi

if (( violations > 0 )); then
  echo "" >&2
  echo "constitution-check: ${violations} violation(s); see .specify/memory/constitution.md" >&2
  exit 1
fi

exit 0
