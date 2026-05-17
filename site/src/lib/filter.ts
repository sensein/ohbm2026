import type { AbstractRecord, AuthorRecord } from '$lib/shards';

/** Lower-case + accent-fold for case/diacritic-insensitive substring search. */
export function normalize(value: string): string {
	return value
		.normalize('NFD')
		.replace(/\p{Diacritic}/gu, '')
		.toLowerCase();
}

/**
 * Damerau-Levenshtein distance with early-exit when the running minimum
 * exceeds `maxDist`. Returns `maxDist + 1` instead of the full distance in
 * that case (cheap signal that's > threshold).
 */
export function damerauLevenshtein(a: string, b: string, maxDist = 2): number {
	if (a === b) return 0;
	const la = a.length;
	const lb = b.length;
	if (Math.abs(la - lb) > maxDist) return maxDist + 1;
	if (la === 0) return lb;
	if (lb === 0) return la;
	let prev2: number[] = [];
	let prev: number[] = new Array(lb + 1);
	let curr: number[] = new Array(lb + 1);
	for (let j = 0; j <= lb; j++) prev[j] = j;
	for (let i = 1; i <= la; i++) {
		curr[0] = i;
		let rowMin = i;
		for (let j = 1; j <= lb; j++) {
			const cost = a.charCodeAt(i - 1) === b.charCodeAt(j - 1) ? 0 : 1;
			curr[j] = Math.min(
				curr[j - 1] + 1, // insert
				prev[j] + 1, // delete
				prev[j - 1] + cost // substitute
			);
			// transposition
			if (
				i > 1 &&
				j > 1 &&
				a.charCodeAt(i - 1) === b.charCodeAt(j - 2) &&
				a.charCodeAt(i - 2) === b.charCodeAt(j - 1)
			) {
				curr[j] = Math.min(curr[j], prev2[j - 2] + 1);
			}
			if (curr[j] < rowMin) rowMin = curr[j];
		}
		if (rowMin > maxDist) return maxDist + 1;
		prev2 = prev;
		prev = curr;
		curr = new Array(lb + 1);
	}
	return prev[lb];
}

/** Tokenize for the inverted index: keep alnum runs ≥ 2 chars after normalization. */
export function tokenizeForIndex(text: string): string[] {
	return normalize(text)
		.split(/[^a-z0-9]+/)
		.filter((t) => t.length >= 2);
}

interface InvertedIndex {
	tokens: string[];
	postings: Map<string, Set<number>>;
}

const invertedIndexCache = new WeakMap<AbstractRecord[], InvertedIndex>();

function buildInvertedIndex(
	abstracts: AbstractRecord[],
	authorsById: Map<number, AuthorRecord>
): InvertedIndex {
	const cached = invertedIndexCache.get(abstracts);
	if (cached) return cached;
	const postings = new Map<string, Set<number>>();
	for (const a of abstracts) {
		const authorNames = a.author_ids
			.map((id) => authorsById.get(id)?.name ?? '')
			.filter(Boolean)
			.join(' ');
		const facetBlob = Object.values(a.facets)
			.map((v) => (Array.isArray(v) ? v.join(' ') : (v as string)))
			.filter(Boolean)
			.join(' ');
		// IMPORTANT: section bodies are part of the haystack now. The earlier
		// build only indexed metadata (title, topics, methods checklist,
		// authors, facets), which meant a query like "pydra" missed the one
		// abstract that mentions the tool in its Methods section.
		const corpus = [
			a.title,
			a.poster_id,
			a.topics.primary,
			a.topics.primary_subcategory,
			a.topics.secondary,
			a.topics.secondary_subcategory,
			a.methods_checklist.join(' '),
			a.sections.introduction,
			a.sections.methods,
			a.sections.results,
			a.sections.conclusion,
			authorNames,
			facetBlob
		].join(' ');
		const seen = new Set<string>();
		for (const tok of tokenizeForIndex(corpus)) {
			if (seen.has(tok)) continue;
			seen.add(tok);
			let postingList = postings.get(tok);
			if (!postingList) {
				postingList = new Set();
				postings.set(tok, postingList);
			}
			postingList.add(a.abstract_id);
		}
	}
	const index = { tokens: [...postings.keys()], postings };
	invertedIndexCache.set(abstracts, index);
	return index;
}

/**
 * Distance threshold per token length. Tighter than FR-008's "≤2 for ≥4"
 * because at 3K abstracts × ~50K unique corpus tokens, a 5-char query like
 * "pydra" admits dozens of proximal matches (hydra, pyra, pydry, …) most
 * of which aren't what the user wants. Stricter scheme:
 *   < 4 chars  → exact only (DL = 0); too noisy otherwise
 *   4–6 chars  → DL ≤ 1     ; catches single-typo / transposition (Smtih→Smith)
 *   ≥ 7 chars  → DL ≤ 2     ; matches the FR-008 spec for longer words
 */
function thresholdFor(token: string): number {
	const n = token.length;
	if (n < 4) return 0;
	if (n < 7) return 1;
	return 2;
}

/**
 * Typo-tolerant lexical search across the per-abstract inverted index.
 * For multi-word queries every query token must match at least one corpus
 * token within its Damerau-Levenshtein threshold; the abstract sets are
 * intersected so all words contribute.
 *
 * Returns `null` for an empty query, or a `{ ids, exactness }` pair where
 * `exactness` is a per-abstract count of how many query tokens matched
 * EXACTLY (not just within DL distance). The UI uses `exactness` to rank
 * exact-match abstracts first.
 */
export interface LexicalResult {
	ids: Set<number>;
	exactness: Map<number, number>; // abstract_id → number of EXACT query-token matches
}

export function lexicalSearch(
	abstracts: AbstractRecord[],
	authorsById: Map<number, AuthorRecord>,
	query: string
): LexicalResult | null {
	const q = normalize(query).trim();
	if (!q) return null;
	const queryTokens = tokenizeForIndex(q);
	if (queryTokens.length === 0) return { ids: new Set(), exactness: new Map() };
	const index = buildInvertedIndex(abstracts, authorsById);

	// Per-token match sets, paired with per-abstract exact-hit flags.
	type PerTokenMatch = { all: Set<number>; exact: Set<number> };
	const perTokenMatches: PerTokenMatch[] = [];
	for (const qt of queryTokens) {
		const threshold = thresholdFor(qt);
		const all = new Set<number>();
		const exact = new Set<number>();
		for (const corpusToken of index.tokens) {
			if (Math.abs(corpusToken.length - qt.length) > threshold) continue;
			const isExact = corpusToken === qt;
			if (isExact || damerauLevenshtein(qt, corpusToken, threshold) <= threshold) {
				const posting = index.postings.get(corpusToken);
				if (!posting) continue;
				for (const id of posting) {
					all.add(id);
					if (isExact) exact.add(id);
				}
			}
		}
		perTokenMatches.push({ all, exact });
	}
	if (perTokenMatches.length === 0) return { ids: new Set(), exactness: new Map() };

	// AND-intersect across per-token sets.
	let finalIds = perTokenMatches[0].all;
	for (let i = 1; i < perTokenMatches.length; i++) {
		const next = new Set<number>();
		const probe = perTokenMatches[i].all;
		for (const id of finalIds) if (probe.has(id)) next.add(id);
		finalIds = next;
		if (finalIds.size === 0) break;
	}

	// For each surviving abstract, count how many query tokens matched EXACTLY.
	const exactness = new Map<number, number>();
	for (const id of finalIds) {
		let n = 0;
		for (const m of perTokenMatches) if (m.exact.has(id)) n++;
		exactness.set(id, n);
	}
	return { ids: finalIds, exactness };
}

interface SearchHaystack {
	abstract_id: number;
	haystack: string;
}

const haystackCache = new WeakMap<AbstractRecord[], SearchHaystack[]>();

export function buildHaystacks(
	abstracts: AbstractRecord[],
	authorsById: Map<number, AuthorRecord>
): SearchHaystack[] {
	const cached = haystackCache.get(abstracts);
	if (cached) return cached;
	const out: SearchHaystack[] = abstracts.map((a) => {
		const authorNames = a.author_ids
			.map((id) => authorsById.get(id)?.name ?? '')
			.filter(Boolean)
			.join(' ');
		const facetBlob = Object.values(a.facets)
			.map((v) => (Array.isArray(v) ? v.join(' ') : (v as string)))
			.join(' ');
		const haystack = normalize(
			[
				a.title,
				a.poster_id,
				a.topics.primary,
				a.topics.primary_subcategory,
				a.topics.secondary,
				a.topics.secondary_subcategory,
				a.methods_checklist.join(' '),
				authorNames,
				facetBlob
			].join('\n')
		);
		return { abstract_id: a.abstract_id, haystack };
	});
	haystackCache.set(abstracts, out);
	return out;
}

/** Substring search across title/poster_id/topics/methods/authors/facets. */
export function searchAbstracts(
	abstracts: AbstractRecord[],
	authorsById: Map<number, AuthorRecord>,
	query: string
): Set<number> | null {
	const q = normalize(query).trim();
	if (!q) return null;
	const haystacks = buildHaystacks(abstracts, authorsById);
	const out = new Set<number>();
	for (const { abstract_id, haystack } of haystacks) {
		if (haystack.includes(q)) out.add(abstract_id);
	}
	return out;
}
