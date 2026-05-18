"""T058a / SC-010 — typo-recall evaluation.

Generates single-typo variants of a sample of known-correct queries
(abstract titles + author surnames) and verifies the original abstract
still appears in the top-10 lexical results when typed against the
deployed UI's lexical search.

The "deployed UI" is reached via the same data-package shards the
SvelteKit site loads at runtime — there is no need to render the page:
we can replay the lexical-search algorithm in Python against the
abstracts shard and arrive at the same ranking. That keeps the eval
cheap (no headless browser) AND deterministic across runs.

Usage:
    PYTHONPATH=src .venv/bin/python scripts/eval_typo_recall.py \\
        --shards site/static/data \\
        --threshold 0.90

Exit code:
    0  recall ≥ threshold
    3  recall < threshold (script ran cleanly but the gate failed)
    2  invocation / shard error

The matching pipeline mirrors `site/src/lib/filter.ts`:
    - NFD + accent-fold + lower-case
    - tokenise on non-alnum, keep tokens length ≥ 2
    - per-token Damerau-Levenshtein threshold:
          n < 4  → DL = 0 (exact only)
          n < 7  → DL ≤ 1
          n ≥ 7  → DL ≤ 2
    - intersect per-token postings across the query
    - rank by exactness-count (descending)

This is a port of the lexical search core to Python so the eval doesn't
depend on Node/Playwright; if `filter.ts` ever changes, this script
must be updated in lock-step (the spec defines the contract; both
implementations satisfy it).
"""

from __future__ import annotations

import argparse
import json
import random
import re
import sys
import unicodedata
import zlib
from collections import defaultdict
from pathlib import Path


def normalize(value: str) -> str:
    decomposed = unicodedata.normalize("NFD", value)
    folded = "".join(ch for ch in decomposed if unicodedata.category(ch) != "Mn")
    return folded.lower()


_TOKEN_SPLIT = re.compile(r"[^a-z0-9]+")


def tokenize(text: str) -> list[str]:
    return [t for t in _TOKEN_SPLIT.split(normalize(text)) if len(t) >= 2]


def threshold_for(token: str) -> int:
    n = len(token)
    if n < 4:
        return 0
    if n < 7:
        return 1
    return 2


def damerau_levenshtein(a: str, b: str, max_dist: int) -> int:
    """Standard DL with early-exit. Returns max_dist + 1 when over."""
    if a == b:
        return 0
    la, lb = len(a), len(b)
    if abs(la - lb) > max_dist:
        return max_dist + 1
    if la == 0:
        return lb
    if lb == 0:
        return la
    prev2: list[int] = []
    prev = list(range(lb + 1))
    curr = [0] * (lb + 1)
    for i in range(1, la + 1):
        curr[0] = i
        row_min = i
        for j in range(1, lb + 1):
            cost = 0 if a[i - 1] == b[j - 1] else 1
            curr[j] = min(
                curr[j - 1] + 1,
                prev[j] + 1,
                prev[j - 1] + cost,
            )
            if (
                i > 1
                and j > 1
                and a[i - 1] == b[j - 2]
                and a[i - 2] == b[j - 1]
            ):
                curr[j] = min(curr[j], prev2[j - 2] + 1)
            if curr[j] < row_min:
                row_min = curr[j]
        if row_min > max_dist:
            return max_dist + 1
        prev2 = prev
        prev = curr
        curr = [0] * (lb + 1)
    return prev[lb]


def build_index(abstracts: list[dict], authors_by_id: dict[int, dict]) -> tuple[dict, list[str]]:
    """Per-token postings + token vocabulary, mirroring `filter.ts`."""
    postings: dict[str, set[int]] = defaultdict(set)
    for a in abstracts:
        author_names = " ".join(
            authors_by_id.get(aid, {}).get("name", "")
            for aid in a.get("author_ids", [])
        )
        facet_blob = " ".join(
            " ".join(v) if isinstance(v, list) else str(v)
            for v in (a.get("facets") or {}).values()
        )
        corpus = " ".join(
            [
                a.get("title", ""),
                a.get("poster_id", ""),
                (a.get("topics") or {}).get("primary", ""),
                (a.get("topics") or {}).get("primary_subcategory", ""),
                (a.get("topics") or {}).get("secondary", ""),
                (a.get("topics") or {}).get("secondary_subcategory", ""),
                " ".join(a.get("methods_checklist", []) or []),
                (a.get("sections") or {}).get("introduction", ""),
                (a.get("sections") or {}).get("methods", ""),
                (a.get("sections") or {}).get("results", ""),
                (a.get("sections") or {}).get("conclusion", ""),
                author_names,
                facet_blob,
            ]
        )
        for tok in set(tokenize(corpus)):
            postings[tok].add(a["abstract_id"])
    return postings, list(postings.keys())


def lexical_search(
    query: str, postings: dict[str, set[int]], vocab: list[str]
) -> list[tuple[int, int]]:
    """Return [(abstract_id, exactness_count)] sorted by exactness desc."""
    qtokens = tokenize(query)
    if not qtokens:
        return []
    per_token: list[tuple[set[int], set[int]]] = []
    for qt in qtokens:
        thr = threshold_for(qt)
        all_set: set[int] = set()
        exact_set: set[int] = set()
        for ctok in vocab:
            if abs(len(ctok) - len(qt)) > thr:
                continue
            is_exact = ctok == qt
            if is_exact or damerau_levenshtein(qt, ctok, thr) <= thr:
                all_set.update(postings[ctok])
                if is_exact:
                    exact_set.update(postings[ctok])
        per_token.append((all_set, exact_set))
    final = set.intersection(*(p[0] for p in per_token))
    exactness: dict[int, int] = {}
    for aid in final:
        exactness[aid] = sum(1 for _, exact in per_token if aid in exact)
    return sorted(exactness.items(), key=lambda kv: (-kv[1], kv[0]))


def single_typo_variants(word: str) -> list[str]:
    """Generate one variant per typo class (insert / delete / substitute / transpose),
    filtered to those the live threshold scheme can recover.

    A variant is "recoverable" iff the live algorithm's per-token threshold
    on the VARIANT's length permits its actual DL distance from `word`. For
    a DELETE on a 4-char word the variant is 3 chars → threshold 0 → not
    recoverable (the algorithm requires exact match below length 4). The
    eval should not penalise the algorithm for typos it never promised to
    recover; SC-010 reads "MUST tolerate" under the FR-008 threshold scheme.
    """
    if len(word) < 4 or not word.isalpha():
        return []
    # `hash(...)` is randomised between Python processes via `PYTHONHASHSEED`,
    # which would break the docstring's determinism promise. `adler32` is a
    # 32-bit stable hash that's plenty for seeding a per-word PRNG.
    rng = random.Random(zlib.adler32(word.encode("utf-8")))
    raw: list[str] = []
    # Delete a non-edge character.
    i = rng.randrange(1, len(word) - 1)
    raw.append(word[:i] + word[i + 1 :])
    # Substitute a non-edge character with an adjacent letter.
    i = rng.randrange(1, len(word) - 1)
    sub = chr(((ord(word[i]) - ord("a") + 1) % 26) + ord("a"))
    raw.append(word[:i] + sub + word[i + 1 :])
    # Insert a duplicate of a non-edge character.
    i = rng.randrange(1, len(word) - 1)
    raw.append(word[:i] + word[i] + word[i:])
    # Transpose two adjacent non-edge characters.
    if len(word) >= 5:
        i = rng.randrange(1, len(word) - 2)
        raw.append(word[:i] + word[i + 1] + word[i] + word[i + 2 :])
    out: list[str] = []
    for v in raw:
        if v == word:
            continue
        t = threshold_for(v)
        if damerau_levenshtein(v, word, t) <= t:
            out.append(v)
    return out


def main() -> int:
    parser = argparse.ArgumentParser(prog="eval_typo_recall")
    parser.add_argument("--shards", required=True, help="Path to the UI data-package shards root.")
    parser.add_argument("--threshold", type=float, default=0.90, help="Required recall@10.")
    parser.add_argument(
        "--sample", type=int, default=200, help="Number of (abstract, word) probes."
    )
    parser.add_argument("--seed", type=int, default=2026, help="RNG seed.")
    args = parser.parse_args()

    shards = Path(args.shards)
    abstracts_path = shards / "abstracts.json"
    authors_path = shards / "authors.json"
    if not abstracts_path.exists() or not authors_path.exists():
        print(
            f"ERROR: data package not found under {shards}. "
            "Run `scripts/build_ui_data.py` first.",
            file=sys.stderr,
        )
        return 2

    abstracts = json.loads(abstracts_path.read_text())["abstracts"]
    authors = json.loads(authors_path.read_text()).get("authors") or []
    authors_by_id = {a["author_id"]: a for a in authors}

    postings, vocab = build_index(abstracts, authors_by_id)

    rng = random.Random(args.seed)
    probes: list[tuple[int, str, str]] = []
    # SC-010 reads "single-typo queries against known abstract titles" —
    # i.e., the QUERY is the title (or a substantial chunk) with one typo,
    # which is what a user actually types when they remember "I read this
    # paper about working memory in aging" and mistype one word. A short
    # 3-token window admits too many candidate abstracts because common
    # 2-char tokens (`in`, `of`, `to`) survive AND-intersection trivially
    # and the exactness tie-breaker can't separate the top 10. We use the
    # full title (capped at 8 tokens to keep the eval cheap) and apply a
    # typo to one ≥ 4-char content word.
    MAX_TOKENS_PER_PROBE = 8
    for a in rng.sample(abstracts, min(len(abstracts), args.sample)):
        title_tokens = [w for w in tokenize(a.get("title", "")) if len(w) >= 2]
        if len(title_tokens) < 4:
            continue
        window = title_tokens[:MAX_TOKENS_PER_PROBE]
        # Pick a typo target: an alpha word ≥ 4 chars (typo-recoverable
        # under the live threshold scheme).
        candidate_indices = [
            i for i, w in enumerate(window) if len(w) >= 4 and w.isalpha()
        ]
        if not candidate_indices:
            continue
        typo_target_idx = rng.choice(candidate_indices)
        target_word = window[typo_target_idx]
        for variant_of_target in single_typo_variants(target_word):
            mutated = list(window)
            mutated[typo_target_idx] = variant_of_target
            query = " ".join(mutated)
            probes.append((a["abstract_id"], target_word, query))

    if not probes:
        print("ERROR: no probes generated. Check the abstracts shard's title field.", file=sys.stderr)
        return 2

    hits = 0
    for expected_id, original, variant in probes:
        ranked = lexical_search(variant, postings, vocab)[:10]
        if any(aid == expected_id for aid, _ in ranked):
            hits += 1
    total = len(probes)
    recall = hits / total
    print(
        json.dumps(
            {
                "probes": total,
                "hits": hits,
                "recall_at_10": round(recall, 4),
                "threshold": args.threshold,
                "passed": recall >= args.threshold,
            },
            indent=2,
        )
    )
    return 0 if recall >= args.threshold else 3


if __name__ == "__main__":
    raise SystemExit(main())
