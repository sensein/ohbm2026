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
	/** Per-abstract ordered token stream — needed for phrase adjacency. */
	tokenStreams: Map<number, string[]>;
	/**
	 * Set of every poster_id in the corpus. Cached on the index so a query
	 * consisting only of negations (`-fmri`) can copy a starting set without
	 * walking the abstracts list on every keystroke.
	 */
	allIds: Set<number>;
}

const invertedIndexCache = new WeakMap<AbstractRecord[], InvertedIndex>();

function buildInvertedIndex(
	abstracts: AbstractRecord[],
	authorsById: Map<number, AuthorRecord>
): InvertedIndex {
	const cached = invertedIndexCache.get(abstracts);
	if (cached) return cached;
	const postings = new Map<string, Set<number>>();
	const tokenStreams = new Map<number, string[]>();
	for (const a of abstracts) {
		const authorNames = a.author_ids
			.map((id) => authorsById.get(id)?.name ?? '')
			.filter(Boolean)
			.join(' ');
		const facetBlob = Object.values(a.facets)
			.map((v) => (Array.isArray(v) ? v.join(' ') : (v as string)))
			.filter(Boolean)
			.join(' ');
		// Section bodies are part of the haystack: a query like "pydra"
		// would otherwise miss the one abstract that mentions the tool
		// only in its Methods section.
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
		const stream = tokenizeForIndex(corpus);
		tokenStreams.set(a.poster_id, stream);
		const seen = new Set<string>();
		for (const tok of stream) {
			if (seen.has(tok)) continue;
			seen.add(tok);
			let postingList = postings.get(tok);
			if (!postingList) {
				postingList = new Set();
				postings.set(tok, postingList);
			}
			postingList.add(a.poster_id);
		}
	}
	const index: InvertedIndex = {
		tokens: [...postings.keys()],
		postings,
		tokenStreams,
		allIds: new Set(tokenStreams.keys())
	};
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

// ─── Query syntax ──────────────────────────────────────────────────────────
//
// The lexical query language supports four operator forms, modelled on the
// conventions of the major web search engines:
//
//     foo bar                              # AND (default) — typo-tolerant
//     "critical brain hypothesis"          # phrase: words must appear
//                                          # adjacent (per-word typo
//                                          # tolerance still applies)
//     brain -fmri                          # has brain, NOT fmri
//     brain OR mind                        # alternation (case-sensitive OR)
//     "working memory" -aging              # phrases compose with -word
//     "resting state" OR "task activation" # OR of phrases
//
// Precedence: OR is the lowest-priority operator. `A B OR C D` parses to
// `(A AND B) OR (C AND D)`. Negation binds tightest (`-` attaches to the
// next word or phrase). Unbalanced quotes degrade to plain words.

export type ParsedClause =
	| { kind: 'word'; word: string; negate: boolean }
	| { kind: 'phrase'; words: string[]; negate: boolean };

export interface ParsedGroup {
	clauses: ParsedClause[];
}

export interface ParsedQuery {
	groups: ParsedGroup[];
	/** True iff at least one operator (quote, leading `-`, or `OR`) is present. */
	hasOperators: boolean;
}

/**
 * Parse a raw search-bar string into AND-groups separated by `OR`.
 *
 * The lexer walks the string once; it splits on whitespace except inside
 * quoted phrases. Inside a phrase, words go through the same
 * `tokenizeForIndex` pipeline so they share the corpus's normalization
 * (lower-case, NFD-fold, alnum-only).
 *
 * Edge cases intentionally tolerated rather than errored on:
 *   - Unclosed quote → treat content as plain words.
 *   - `-` alone or `--` → ignored.
 *   - Empty phrase `""` → ignored.
 *   - Leading/trailing/duplicate `OR` → coalesced into a single separator.
 */
export function parseQuery(input: string): ParsedQuery {
	const s = input ?? '';
	const items: Array<ParsedClause | 'OR'> = [];
	let i = 0;
	let sawOperator = false;
	while (i < s.length) {
		const ch = s[i];
		if (ch === ' ' || ch === '\t' || ch === '\n') {
			i++;
			continue;
		}
		// Detect `OR` as a standalone uppercase token surrounded by whitespace
		// (or string ends). Lowercase `or` is just a word.
		if (
			ch === 'O' &&
			s[i + 1] === 'R' &&
			(i + 2 === s.length || s[i + 2] === ' ' || s[i + 2] === '\t')
		) {
			items.push('OR');
			sawOperator = true;
			i += 2;
			continue;
		}
		let negate = false;
		if (ch === '-' && i + 1 < s.length && s[i + 1] !== ' ' && s[i + 1] !== '-') {
			negate = true;
			sawOperator = true;
			i++;
		}
		if (s[i] === '"') {
			// Phrase. Consume until the next `"` or end-of-string.
			sawOperator = true;
			const end = s.indexOf('"', i + 1);
			if (end === -1) {
				// Unclosed quote — fall through and treat as a word starting at `"`.
				const word = tokenizeForIndex(s.slice(i));
				if (word.length === 1) {
					items.push({ kind: 'word', word: word[0], negate });
				} else if (word.length > 1) {
					// Multi-word fallback acts like an unquoted phrase under AND.
					for (const w of word) {
						items.push({ kind: 'word', word: w, negate });
					}
				}
				i = s.length;
				continue;
			}
			const inner = s.slice(i + 1, end);
			const words = tokenizeForIndex(inner);
			if (words.length === 1) {
				items.push({ kind: 'word', word: words[0], negate });
			} else if (words.length >= 2) {
				items.push({ kind: 'phrase', words, negate });
			}
			i = end + 1;
			continue;
		}
		// Plain word: consume until whitespace.
		let j = i;
		while (j < s.length && s[j] !== ' ' && s[j] !== '\t' && s[j] !== '\n' && s[j] !== '"') j++;
		const raw = s.slice(i, j);
		const toks = tokenizeForIndex(raw);
		for (const tok of toks) items.push({ kind: 'word', word: tok, negate });
		i = j;
	}
	// Coalesce duplicate / leading / trailing OR markers.
	const cleaned: Array<ParsedClause | 'OR'> = [];
	for (const it of items) {
		if (it === 'OR') {
			if (cleaned.length === 0) continue; // leading OR — drop
			if (cleaned[cleaned.length - 1] === 'OR') continue; // duplicate — drop
			cleaned.push(it);
		} else {
			cleaned.push(it);
		}
	}
	while (cleaned.length && cleaned[cleaned.length - 1] === 'OR') cleaned.pop();
	// Split into AND-groups by the OR marker.
	const groups: ParsedGroup[] = [];
	let current: ParsedClause[] = [];
	for (const it of cleaned) {
		if (it === 'OR') {
			if (current.length) groups.push({ clauses: current });
			current = [];
		} else {
			current.push(it);
		}
	}
	if (current.length) groups.push({ clauses: current });
	return { groups, hasOperators: sawOperator };
}

/**
 * Build a query string suitable for handing to the semantic embedder when
 * lexical operators are present. Operators (`-`, `"`, `OR`) are removed,
 * and only the positive content words / phrase tokens are kept. Negated
 * clauses are excluded because semantic embedding has no native notion of
 * negation.
 */
export function queryForSemantic(parsed: ParsedQuery): string {
	const parts: string[] = [];
	for (const g of parsed.groups) {
		for (const c of g.clauses) {
			if (c.negate) continue;
			if (c.kind === 'word') parts.push(c.word);
			else parts.push(...c.words);
		}
	}
	return parts.join(' ');
}

// ─── Evaluation ────────────────────────────────────────────────────────────

/** Set of poster_ids whose corpus contains a token within DL threshold of `qword`. */
function lookupWord(
	qword: string,
	index: InvertedIndex
): { all: Set<number>; exact: Set<number> } {
	const threshold = thresholdFor(qword);
	const all = new Set<number>();
	const exact = new Set<number>();
	for (const ctok of index.tokens) {
		if (Math.abs(ctok.length - qword.length) > threshold) continue;
		const isExact = ctok === qword;
		if (isExact || damerauLevenshtein(qword, ctok, threshold) <= threshold) {
			const posting = index.postings.get(ctok);
			if (!posting) continue;
			for (const id of posting) {
				all.add(id);
				if (isExact) exact.add(id);
			}
		}
	}
	return { all, exact };
}

/**
 * Find a typo-tolerant phrase match inside an abstract's ordered token
 * stream. Returns the count of exactly-matching positions across the
 * matched window (`null` when no window matches).
 *
 * Approach: narrow the search by length first; for each starting position
 * where the stream's length permits a full window, compare each phrase word
 * against the corresponding stream word within its per-word threshold.
 */
function phraseMatchExactCount(
	stream: string[],
	phrase: string[],
	thresholds: number[]
): number | null {
	const n = stream.length;
	const m = phrase.length;
	if (m === 0 || n < m) return null;
	for (let i = 0; i <= n - m; i++) {
		let exact = 0;
		let ok = true;
		for (let k = 0; k < m; k++) {
			const w = stream[i + k];
			const pw = phrase[k];
			if (w === pw) {
				exact++;
				continue;
			}
			const t = thresholds[k];
			if (Math.abs(w.length - pw.length) > t) {
				ok = false;
				break;
			}
			if (damerauLevenshtein(pw, w, t) > t) {
				ok = false;
				break;
			}
		}
		if (ok) return exact;
	}
	return null;
}

interface ClauseResult {
	/** abstracts that matched (positive) or were blocked (negative). */
	matched: Set<number>;
	/** sum of exact-token hits this clause contributed per abstract. */
	exact: Map<number, number>;
}

function evaluateClause(clause: ParsedClause, index: InvertedIndex): ClauseResult {
	if (clause.kind === 'word') {
		const { all, exact } = lookupWord(clause.word, index);
		const exactMap = new Map<number, number>();
		for (const id of exact) exactMap.set(id, 1);
		return { matched: all, exact: exactMap };
	}
	// Phrase. Candidates first: abstracts that contain every phrase word
	// individually (typo-tolerant). Then run the adjacency check on each.
	const perWord = clause.words.map((w) => lookupWord(w, index));
	let candidates = perWord[0].all;
	for (let i = 1; i < perWord.length; i++) {
		const next = new Set<number>();
		for (const id of candidates) if (perWord[i].all.has(id)) next.add(id);
		candidates = next;
		if (candidates.size === 0) break;
	}
	const thresholds = clause.words.map(thresholdFor);
	const matched = new Set<number>();
	const exactMap = new Map<number, number>();
	for (const id of candidates) {
		const stream = index.tokenStreams.get(id);
		if (!stream) continue;
		const exactHits = phraseMatchExactCount(stream, clause.words, thresholds);
		if (exactHits !== null) {
			matched.add(id);
			exactMap.set(id, exactHits);
		}
	}
	return { matched, exact: exactMap };
}

export interface LexicalResult {
	/** Abstracts that satisfy the query (membership, not just ranking). */
	ids: Set<number>;
	/** Per-abstract count of exact-token hits, used to rank exact matches first. */
	exactness: Map<number, number>;
	/**
	 * Abstracts that hit any `-clause` in the query. Surfaced separately so
	 * the search merger can subtract them from any semantic-only candidates
	 * — preserves the negation contract even when the user types
	 * `-fmri` alongside a semantic-enabled query.
	 */
	negationBlocked: Set<number>;
	/** Did the parsed query use any operators (`"…"` / `-` / `OR`)? */
	hasOperators: boolean;
}

/**
 * Typo-tolerant lexical search with operator support.
 *
 * Returns `null` for an empty query. For a non-empty query, returns the
 * matched set plus an `exactness` ranking signal and a `negationBlocked`
 * set the merger uses to subtract semantic-only hits.
 */
export function lexicalSearch(
	abstracts: AbstractRecord[],
	authorsById: Map<number, AuthorRecord>,
	query: string
): LexicalResult | null {
	const trimmed = (query ?? '').trim();
	if (!trimmed) return null;
	const parsed = parseQuery(trimmed);
	if (parsed.groups.length === 0) {
		return {
			ids: new Set(),
			exactness: new Map(),
			negationBlocked: new Set(),
			hasOperators: parsed.hasOperators
		};
	}
	const index = buildInvertedIndex(abstracts, authorsById);

	const unionIds = new Set<number>();
	const unionExact = new Map<number, number>();
	const negationBlocked = new Set<number>();

	for (const group of parsed.groups) {
		// Start from "everything" — narrow by positive clauses, subtract negatives.
		let positives: Set<number> | null = null;
		const groupExact = new Map<number, number>();
		const groupBlocked = new Set<number>();
		for (const clause of group.clauses) {
			const r = evaluateClause(clause, index);
			if (clause.negate) {
				for (const id of r.matched) groupBlocked.add(id);
				continue;
			}
			// Track exactness contribution.
			for (const [id, n] of r.exact) groupExact.set(id, (groupExact.get(id) ?? 0) + n);
			if (positives === null) {
				positives = new Set(r.matched);
			} else {
				const next = new Set<number>();
				for (const id of positives) if (r.matched.has(id)) next.add(id);
				positives = next;
			}
			if (positives.size === 0) break;
		}
		if (positives === null) {
			// Group consisted entirely of negations. Semantics: subtract from the
			// universe of all abstracts. The fresh `Set` lets us `.delete` below
			// without mutating the cached `index.allIds`.
			positives = new Set(index.allIds);
		}
		for (const id of groupBlocked) {
			positives.delete(id);
			negationBlocked.add(id);
		}
		for (const id of positives) {
			unionIds.add(id);
			const prev = unionExact.get(id) ?? 0;
			const here = groupExact.get(id) ?? 0;
			if (here > prev) unionExact.set(id, here);
		}
	}
	return { ids: unionIds, exactness: unionExact, negationBlocked, hasOperators: parsed.hasOperators };
}

interface SearchHaystack {
	poster_id: number;
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
		return { poster_id: a.poster_id, haystack };
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
	for (const { poster_id, haystack } of haystacks) {
		if (haystack.includes(q)) out.add(poster_id);
	}
	return out;
}
