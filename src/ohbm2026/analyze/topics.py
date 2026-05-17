"""Stage 4 topic pipeline (US5).

Per FR-009, every generated clustering kind (`communities` and
`topic_clusters`) ships a per-cluster `topics.json` artifact built by a
**two-stage hybrid pipeline**:

1. **Local phrase extraction** — spaCy noun-chunks + named entities,
   canonicalized (lowercase + lemma + dedupe), scored via class-based
   TF-IDF across the cluster set. Returns the top-N candidate phrases
   per cluster (default 60). Fully local; no API.

2. **LLM grouping pass (opt-out via `--skip-llm-topics`)** — one
   OpenAI call per cluster receives only the candidate-phrase list
   (NOT raw abstracts) and returns
   `{Keywords: list[str], Title: str, Description: str, Focus: …}`.
   Post-response guard: `set(Keywords).issubset(set(candidate_phrases))`
   — the LLM can re-rank/group but cannot invent terms. Cache key:
   `sha256(model_id || prompt_version || "\\n".join(sorted(candidate_phrases)))`.

When `--skip-llm-topics`: emit the top-N c-TF-IDF phrases directly as
`Keywords`; leave `Title`/`Description`/`Focus` empty.

NeuroScape cluster labels do NOT pass through this pipeline — they
come verbatim from the published `cluster_table.csv` via the rollup
writer.
"""

from __future__ import annotations

import json
import math
import re
from collections import Counter
from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path
from typing import Any, Callable, Iterable

from ohbm2026.exceptions import AnalysisError, TopicGroupingHallucination


__all__ = [
    "DEFAULT_PHRASE_TOP_N",
    "DEFAULT_KEYWORD_OUT_N",
    "DEFAULT_LLM_MODEL_ID",
    "DEFAULT_PROMPT_VERSION",
    "TopicArtifact",
    "extract_candidate_phrases",
    "compute_ctfidf",
    "group_phrases_via_llm",
    "build_topics_artifact",
]


DEFAULT_PHRASE_TOP_N = 60
DEFAULT_KEYWORD_OUT_N = 15
DEFAULT_LLM_MODEL_ID = "gpt-5.4-mini"
DEFAULT_PROMPT_VERSION = "v1"


# ---------------------------------------------------------------------------
# Result shape
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TopicArtifact:
    """One entry per cluster in the `topics.json` map."""

    cluster_id: int
    Keywords: list[str]
    Title: str = ""
    Description: str = ""
    Focus: str = ""
    candidate_phrases: list[str] = field(default_factory=list)

    def to_payload(self) -> dict[str, Any]:
        """Serialize to the schema the rollup + bundle consume."""
        return {
            "Keywords": list(self.Keywords),
            "Title": self.Title,
            "Description": self.Description,
            "Focus": self.Focus,
        }


# ---------------------------------------------------------------------------
# spaCy phrase extraction + canonicalization
# ---------------------------------------------------------------------------

_PHRASE_PUNCT_RE = re.compile(r"^[\W_]+|[\W_]+$", re.UNICODE)
_WHITESPACE_RE = re.compile(r"\s+")


def _canonicalize_phrase(text: str, *, lemmas: list[str] | None = None) -> str:
    """Lowercase + strip outer punct + collapse whitespace.

    When `lemmas` is provided, prefer the lemmatized form (used when
    spaCy is available).
    """
    base = " ".join(lemmas) if lemmas else text
    base = base.lower()
    base = _WHITESPACE_RE.sub(" ", base).strip()
    base = _PHRASE_PUNCT_RE.sub("", base)
    return base


def _load_spacy(model_name: str = "en_core_web_md") -> Any | None:
    """Try to load a spaCy model. Returns `None` if spaCy is unavailable.

    The fallback (None) triggers a simple regex-based phrase extractor
    in `extract_cluster_phrases_local` so tests + offline environments
    work without spaCy installed.
    """
    try:
        import spacy
    except ImportError:  # pragma: no cover
        return None
    try:
        # Load the full pipeline — `noun_chunks` requires the parser,
        # and the tagger informs the lemmatizer that's used downstream
        # in `_canonicalize_phrase`. Disabling them silently degrades
        # candidate-phrase quality, so keep them on.
        return spacy.load(model_name)
    except OSError:
        try:
            return spacy.load("en_core_web_sm")
        except OSError:
            return None


def _extract_phrases_with_spacy(text: str, nlp: Any) -> list[tuple[str, list[str]]]:
    """Run spaCy over `text` and return `[(raw_phrase, lemmas)]` for
    noun-chunks + named entities. Skip purely-numeric / single-stop-word phrases."""
    if not text:
        return []
    doc = nlp(text)
    out: list[tuple[str, list[str]]] = []
    seen_spans: set[tuple[int, int]] = set()
    for chunk in doc.noun_chunks:
        seen_spans.add((chunk.start_char, chunk.end_char))
        lemmas = [
            tok.lemma_.lower()
            for tok in chunk
            if not tok.is_stop and not tok.is_punct and not tok.is_space
        ]
        if not lemmas:
            continue
        out.append((chunk.text, lemmas))
    for ent in doc.ents:
        span_key = (ent.start_char, ent.end_char)
        if span_key in seen_spans:
            continue
        seen_spans.add(span_key)
        lemmas = [
            tok.lemma_.lower()
            for tok in ent
            if not tok.is_punct and not tok.is_space
        ]
        if not lemmas:
            continue
        out.append((ent.text, lemmas))
    return out


_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z\-]+")
_STOPWORDS = {
    "the", "a", "an", "of", "in", "on", "for", "to", "and", "or",
    "with", "by", "as", "is", "are", "was", "were", "be", "been",
    "being", "this", "that", "these", "those", "we", "our", "their",
    "its", "it", "they", "them", "from", "at", "but", "not", "no",
    "such", "than", "between", "into", "via", "using", "use", "used",
    "show", "shown", "showed", "shows", "found", "find", "finds",
    "study", "studies", "studied", "result", "results", "method",
    "methods", "analysis", "analyses", "data", "based", "however",
    "thus", "also", "may", "can", "could", "would", "should", "will",
    "have", "has", "had", "i", "ii", "iii", "iv", "v", "vi", "vii",
    "p", "n", "rs", "ms", "vs", "etc",
}


def _extract_phrases_fallback(text: str) -> list[tuple[str, list[str]]]:
    """Regex-based fallback when spaCy is unavailable.

    Extracts noun-phrase-ish bigrams + trigrams using a simple POS-free
    heuristic: tokenize on word boundaries, drop stopwords + single
    letters, emit 1-3 token windows. Deduplicated downstream.
    """
    tokens = [t.lower() for t in _TOKEN_RE.findall(text or "")]
    tokens = [t for t in tokens if len(t) > 1 and t not in _STOPWORDS]
    out: list[tuple[str, list[str]]] = []
    n = len(tokens)
    for i in range(n):
        out.append((tokens[i], [tokens[i]]))
        if i + 1 < n:
            out.append((f"{tokens[i]} {tokens[i+1]}", [tokens[i], tokens[i + 1]]))
        if i + 2 < n:
            out.append(
                (
                    f"{tokens[i]} {tokens[i+1]} {tokens[i+2]}",
                    [tokens[i], tokens[i + 1], tokens[i + 2]],
                )
            )
    return out


def extract_cluster_phrases_local(
    cluster_texts: list[str],
    *,
    spacy_model: str = "en_core_web_md",
    spacy_nlp: Any | None = None,
) -> Counter:
    """Per-cluster phrase frequency counter.

    Returns a `Counter` mapping `canonical_phrase` → count. Used by
    `compute_ctfidf` to build the cluster × phrase matrix.
    """
    nlp = spacy_nlp if spacy_nlp is not None else _load_spacy(spacy_model)
    counts: Counter = Counter()
    for text in cluster_texts:
        if not text:
            continue
        pairs = (
            _extract_phrases_with_spacy(text, nlp)
            if nlp is not None
            else _extract_phrases_fallback(text)
        )
        seen_in_doc: set[str] = set()
        for raw, lemmas in pairs:
            phrase = _canonicalize_phrase(raw, lemmas=lemmas)
            if not phrase or len(phrase) < 2:
                continue
            if all(t in _STOPWORDS for t in phrase.split()):
                continue
            # One occurrence per phrase per document (typical c-TF-IDF
            # variant — reduces dominance of repetition within a single
            # abstract).
            if phrase in seen_in_doc:
                continue
            seen_in_doc.add(phrase)
            counts[phrase] += 1
    return counts


def extract_candidate_phrases(
    cluster_texts: list[str],
    *,
    top_n: int = DEFAULT_PHRASE_TOP_N,
    spacy_model: str = "en_core_web_md",
    spacy_nlp: Any | None = None,
    other_cluster_counters: list[Counter] | None = None,
) -> list[str]:
    """Pull the top-N c-TF-IDF candidate phrases for ONE cluster.

    Requires `other_cluster_counters` for the IDF denominator — when
    omitted, falls back to plain TF (which is what the unit tests use
    for single-cluster smoke checks).
    """
    this_counter = extract_cluster_phrases_local(
        cluster_texts, spacy_model=spacy_model, spacy_nlp=spacy_nlp
    )
    if other_cluster_counters is None:
        # Plain TF fallback
        return [p for p, _ in this_counter.most_common(top_n)]
    scored = compute_ctfidf([this_counter] + list(other_cluster_counters))
    # First entry corresponds to this cluster
    this_scores = scored[0]
    return [p for p, _ in sorted(this_scores.items(), key=lambda kv: -kv[1])[:top_n]]


# ---------------------------------------------------------------------------
# Class-based TF-IDF
# ---------------------------------------------------------------------------


def compute_ctfidf(cluster_counters: list[Counter]) -> list[dict[str, float]]:
    """Class-based TF-IDF over a list of per-cluster phrase counters.

    Returns a list aligned with `cluster_counters`, each entry mapping
    `phrase` → `c-TF-IDF score`. Score formula (BERTopic style):

        TF(p in c) = count(p, c) / sum_{p'} count(p', c)
        IDF(p)     = log(1 + (total_clusters / num_clusters_containing_p))
        c-TF-IDF   = TF(p in c) × IDF(p)
    """
    n_clusters = len(cluster_counters)
    if n_clusters == 0:
        return []
    # Phrase → number of clusters containing it
    df: Counter = Counter()
    for counter in cluster_counters:
        for phrase in counter:
            df[phrase] += 1

    scored: list[dict[str, float]] = []
    for counter in cluster_counters:
        total = sum(counter.values())
        if total == 0:
            scored.append({})
            continue
        cluster_scores: dict[str, float] = {}
        for phrase, count in counter.items():
            tf = count / total
            idf = math.log(1.0 + (n_clusters / df[phrase]))
            cluster_scores[phrase] = tf * idf
        scored.append(cluster_scores)
    return scored


# ---------------------------------------------------------------------------
# LLM grouping pass
# ---------------------------------------------------------------------------


LLM_PROMPT_TEMPLATE = (
    "You are summarizing a research cluster from neuroscience abstracts. "
    "You will be given a candidate list of phrases extracted from the "
    "cluster's member abstracts. Pick the best {keyword_out_n} phrases "
    "from the list (do NOT invent new terms), then write a concise "
    "Title (<=10 words), a Description (1-2 sentences), and classify "
    "the cluster's Focus as either 'themes' (research topic) or "
    "'methodologies' (technique-focused).\n\n"
    "Candidate phrases (you MUST pick keywords from this list only):\n"
    "{candidate_phrases_block}\n\n"
    "Respond with strict JSON: "
    "{{\"Keywords\": [...], \"Title\": \"...\", \"Description\": \"...\", "
    "\"Focus\": \"themes\" | \"methodologies\"}}"
)


def _cache_key(
    model_id: str, prompt_version: str, candidate_phrases: list[str]
) -> str:
    blob = (
        model_id.encode("utf-8")
        + b"\x00"
        + prompt_version.encode("utf-8")
        + b"\x00"
        + "\n".join(sorted(candidate_phrases)).encode("utf-8")
    )
    return "sha256:" + sha256(blob).hexdigest()


def _cache_load(cache_dir: Path, key: str) -> dict[str, Any] | None:
    p = cache_dir / f"{key.split(':', 1)[1]}.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _cache_store(cache_dir: Path, key: str, payload: dict[str, Any]) -> None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    p = cache_dir / f"{key.split(':', 1)[1]}.json"
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(p)


def _enforce_subset_guard(
    keywords: list[str], candidate_phrases: list[str], *, cluster_id: int
) -> list[str]:
    """Raise `TopicGroupingHallucination` if the LLM emits an invented term.

    Strict variant — used for cache replays where the on-disk value MUST
    already obey the contract.
    """
    candidate_set = set(candidate_phrases)
    invented = [k for k in keywords if k not in candidate_set]
    if invented:
        raise TopicGroupingHallucination(
            f"cluster {cluster_id}: LLM emitted keywords not in the candidate "
            f"shortlist: {invented[:5]} (showing first 5). The LLM is allowed to "
            f"re-rank but cannot invent terms."
        )
    return keywords


def _filter_to_subset(
    keywords: list[str], candidate_phrases: list[str], *, cluster_id: int
) -> tuple[list[str], list[str]]:
    """Return `(kept, dropped)` after dropping non-candidate terms.

    Production callers preserve the `Keywords ⊆ candidate_phrases` contract
    by dropping invented terms rather than raising — the cached payload
    that lands on disk is still subset-clean. Raises
    `TopicGroupingHallucination` only when EVERY emitted keyword was
    invented (degenerate output — the LLM ignored the shortlist entirely).
    """
    candidate_set = set(candidate_phrases)
    kept: list[str] = []
    dropped: list[str] = []
    seen: set[str] = set()
    for k in keywords:
        if k in candidate_set and k not in seen:
            kept.append(k)
            seen.add(k)
        elif k not in candidate_set:
            dropped.append(k)
    if not kept and keywords:
        raise TopicGroupingHallucination(
            f"cluster {cluster_id}: all {len(keywords)} emitted keywords were "
            f"invented; first 5 dropped = {dropped[:5]}."
        )
    return kept, dropped


LLMCaller = Callable[[str, str], str]  # (prompt, model_id) -> JSON response string


def group_phrases_via_llm(
    candidate_phrases: list[str],
    *,
    cluster_id: int,
    model_id: str = DEFAULT_LLM_MODEL_ID,
    prompt_version: str = DEFAULT_PROMPT_VERSION,
    keyword_out_n: int = DEFAULT_KEYWORD_OUT_N,
    cache_dir: Path,
    llm_call: LLMCaller | None = None,
) -> dict[str, Any]:
    """Send the candidate-phrase list to the LLM for re-ranking + labeling.

    Returns `{"Keywords": [...], "Title": ..., "Description": ..., "Focus": ...}`.

    `llm_call` is injected so tests can mock the OpenAI client; production
    code passes a real adapter from `enrich.flex_tier`. Cache key is
    `sha256(model_id || prompt_version || sorted(candidate_phrases))`.
    """
    key = _cache_key(model_id, prompt_version, candidate_phrases)
    cached = _cache_load(cache_dir, key)
    if cached is not None:
        keywords = list(cached.get("Keywords", []))
        _enforce_subset_guard(keywords, candidate_phrases, cluster_id=cluster_id)
        return cached

    if llm_call is None:
        raise AnalysisError(
            "group_phrases_via_llm: no LLM adapter injected and no cache hit. "
            "Either pass --skip-llm-topics or wire enrich.flex_tier."
        )

    prompt = LLM_PROMPT_TEMPLATE.format(
        keyword_out_n=keyword_out_n,
        candidate_phrases_block="\n".join(f"- {p}" for p in candidate_phrases),
    )
    response = llm_call(prompt, model_id)
    try:
        data = json.loads(response)
    except json.JSONDecodeError as exc:
        raise AnalysisError(
            f"LLM returned non-JSON for cluster {cluster_id}: {exc}"
        ) from exc

    raw_keywords = list(data.get("Keywords", []))
    kept, dropped = _filter_to_subset(
        raw_keywords, candidate_phrases, cluster_id=cluster_id
    )
    payload: dict[str, Any] = {
        "Keywords": kept,
        "Title": str(data.get("Title", "") or ""),
        "Description": str(data.get("Description", "") or ""),
        "Focus": str(data.get("Focus", "") or ""),
    }
    if dropped:
        payload["DroppedKeywords"] = dropped
    _cache_store(cache_dir, key, payload)
    return payload


# ---------------------------------------------------------------------------
# build_topics_artifact: end-to-end per-cluster topic builder
# ---------------------------------------------------------------------------


def build_topics_artifact(
    cluster_assignments: Iterable[int],
    abstract_texts: list[str],
    *,
    cache_dir: Path,
    skip_llm: bool = False,
    spacy_model: str = "en_core_web_md",
    spacy_nlp: Any | None = None,
    phrase_top_n: int = DEFAULT_PHRASE_TOP_N,
    keyword_out_n: int = DEFAULT_KEYWORD_OUT_N,
    llm_model_id: str = DEFAULT_LLM_MODEL_ID,
    prompt_version: str = DEFAULT_PROMPT_VERSION,
    llm_call: LLMCaller | None = None,
) -> dict[int, dict[str, Any]]:
    """Build the per-cluster topics map for a clustering bundle.

    `cluster_assignments` is the per-row cluster id (same length as
    `abstract_texts`). `cache_dir` is the per-corpus LLM cache root.
    With `skip_llm=True`, returns the top-N c-TF-IDF phrases as
    Keywords with empty Title/Description/Focus.

    Returns `{cluster_id: {Keywords, Title, Description, Focus}}`.
    """
    cluster_assignments = list(cluster_assignments)
    if len(cluster_assignments) != len(abstract_texts):
        raise ValueError(
            f"cluster_assignments ({len(cluster_assignments)}) and abstract_texts "
            f"({len(abstract_texts)}) must align on the leading axis"
        )

    # Group texts by cluster id
    cluster_to_texts: dict[int, list[str]] = {}
    for cid, text in zip(cluster_assignments, abstract_texts):
        cluster_to_texts.setdefault(int(cid), []).append(text or "")

    cluster_ids_sorted = sorted(cluster_to_texts.keys())
    nlp = spacy_nlp if spacy_nlp is not None else _load_spacy(spacy_model)

    # 1) Per-cluster phrase counters
    counters: list[Counter] = []
    for cid in cluster_ids_sorted:
        counter = extract_cluster_phrases_local(
            cluster_to_texts[cid],
            spacy_model=spacy_model,
            spacy_nlp=nlp,
        )
        counters.append(counter)

    # 2) c-TF-IDF + top-N candidates
    scored = compute_ctfidf(counters)
    candidates_by_cluster: dict[int, list[str]] = {}
    for cid, scores in zip(cluster_ids_sorted, scored):
        ordered = sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))
        candidates_by_cluster[cid] = [p for p, _ in ordered[:phrase_top_n]]

    # 3) Optional LLM grouping pass
    out: dict[int, dict[str, Any]] = {}
    for cid in cluster_ids_sorted:
        candidates = candidates_by_cluster[cid]
        if skip_llm:
            keywords = candidates[:keyword_out_n]
            out[cid] = {
                "Keywords": list(keywords),
                "Title": "",
                "Description": "",
                "Focus": "",
            }
            continue
        out[cid] = group_phrases_via_llm(
            candidates,
            cluster_id=cid,
            model_id=llm_model_id,
            prompt_version=prompt_version,
            keyword_out_n=keyword_out_n,
            cache_dir=cache_dir,
            llm_call=llm_call,
        )
    return out
