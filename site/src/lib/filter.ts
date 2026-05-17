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
		const corpus = [
			a.title,
			a.poster_id,
			a.topics.primary,
			a.topics.primary_subcategory,
			a.topics.secondary,
			a.topics.secondary_subcategory,
			a.methods_checklist.join(' '),
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

/** Distance threshold per token length, per FR-008. */
function thresholdFor(token: string): number {
	return token.length < 4 ? 1 : 2;
}

/**
 * Typo-tolerant lexical search across the per-abstract inverted index.
 * For multi-word queries every query token must match at least one corpus
 * token within its Damerau-Levenshtein threshold; the abstract sets are
 * intersected so all words contribute.
 *
 * Returns `null` for an empty query (= "show everything", same convention
 * as the substring search) or a Set of matching `abstract_id`s.
 */
export function lexicalSearch(
	abstracts: AbstractRecord[],
	authorsById: Map<number, AuthorRecord>,
	query: string
): Set<number> | null {
	const q = normalize(query).trim();
	if (!q) return null;
	const queryTokens = tokenizeForIndex(q);
	if (queryTokens.length === 0) return new Set();
	const index = buildInvertedIndex(abstracts, authorsById);
	const perTokenMatches: Set<number>[] = [];
	for (const qt of queryTokens) {
		const threshold = thresholdFor(qt);
		const matchedAbstractIds = new Set<number>();
		for (const corpusToken of index.tokens) {
			if (Math.abs(corpusToken.length - qt.length) > threshold) continue;
			// Exact substring match (either direction) counts as 0-distance.
			if (corpusToken === qt || corpusToken.includes(qt) || qt.includes(corpusToken)) {
				const posting = index.postings.get(corpusToken);
				if (posting) for (const id of posting) matchedAbstractIds.add(id);
				continue;
			}
			if (damerauLevenshtein(qt, corpusToken, threshold) <= threshold) {
				const posting = index.postings.get(corpusToken);
				if (posting) for (const id of posting) matchedAbstractIds.add(id);
			}
		}
		perTokenMatches.push(matchedAbstractIds);
	}
	if (perTokenMatches.length === 0) return new Set();
	// Intersect all per-token sets (AND semantics).
	let final = perTokenMatches[0];
	for (let i = 1; i < perTokenMatches.length; i++) {
		const next = new Set<number>();
		const probe = perTokenMatches[i];
		for (const id of final) if (probe.has(id)) next.add(id);
		final = next;
		if (final.size === 0) break;
	}
	return final;
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
