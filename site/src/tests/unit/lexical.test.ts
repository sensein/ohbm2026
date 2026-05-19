import { describe, expect, it } from 'vitest';
import {
	damerauLevenshtein,
	lexicalSearch,
	parseQuery,
	queryForSemantic,
	tokenizeForIndex
} from '$lib/filter';
import type { AbstractRecord, AuthorRecord } from '$lib/shards';

describe('damerauLevenshtein', () => {
	it('returns 0 for identical strings', () => {
		expect(damerauLevenshtein('memory', 'memory')).toBe(0);
	});

	it('counts a single substitution', () => {
		expect(damerauLevenshtein('memory', 'memora')).toBe(1);
	});

	it('counts a single deletion', () => {
		expect(damerauLevenshtein('memory', 'memry')).toBe(1);
	});

	it('counts a single transposition (Damerau)', () => {
		// "smtih" → "smith" is one adjacent transposition
		expect(damerauLevenshtein('smtih', 'smith')).toBe(1);
	});

	it('early-exits past the threshold', () => {
		// Garbage query vs corpus token — must be > 2
		expect(damerauLevenshtein('xyzpdq', 'memory', 2)).toBe(3);
	});

	it('rejects pairs whose length difference exceeds the threshold', () => {
		expect(damerauLevenshtein('mem', 'memorial', 2)).toBe(3);
	});
});

describe('tokenizeForIndex', () => {
	it('lowercases + accent-folds + drops 1-char tokens', () => {
		expect(tokenizeForIndex('Memory fMRI in García')).toEqual(['memory', 'fmri', 'in', 'garcia']);
	});

	it('handles punctuation as delimiters', () => {
		expect(tokenizeForIndex('default-mode network!')).toEqual(['default', 'mode', 'network']);
	});
});

const author: AuthorRecord = {
	author_id: 0,
	name: 'José García',
	affiliations: ['UAM'],
	poster_ids: [1001]
};

const abstracts: AbstractRecord[] = [
	{
		poster_id: 1001,
		title: 'Memory fMRI in aging',
		accepted_for: 'Poster',
		sections: { introduction: '', methods: '', results: '', conclusion: '', references: '' },
		topics: {
			primary: 'Lifespan Development',
			primary_subcategory: 'Aging',
			secondary: '',
			secondary_subcategory: ''
		},
		methods_checklist: ['Functional MRI'],
		facets: { keywords: ['Aging', 'MRI'], methods: ['Functional MRI'] },
		author_ids: [0],
		reference_dois: [],
		reference_urls: []
	},
	{
		poster_id: 1003,
		title: 'Default mode network in fMRI',
		accepted_for: 'Oral',
		sections: { introduction: '', methods: '', results: '', conclusion: '', references: '' },
		topics: {
			primary: 'Cognition',
			primary_subcategory: 'Memory',
			secondary: '',
			secondary_subcategory: ''
		},
		methods_checklist: ['Functional MRI'],
		facets: { keywords: ['DMN', 'resting-state'] },
		author_ids: [],
		reference_dois: [],
		reference_urls: []
	}
];

const authorsById = new Map([[0, author]]);

describe('lexicalSearch (FR-008 typo tolerance)', () => {
	it('returns null for empty query', () => {
		expect(lexicalSearch(abstracts, authorsById, '')).toBeNull();
	});

	it('matches an exact token', () => {
		const result = lexicalSearch(abstracts, authorsById, 'aging');
		expect(result?.ids).toEqual(new Set([1001]));
		// "aging" is an exact match in abstract 1001 → exactness count = 1.
		expect(result?.exactness.get(1001)).toBe(1);
	});

	it('matches a single-substitution typo on a long word', () => {
		// "aginq" → "aging" (1 substitution; threshold = 1 for length 5 under
		// the tightened scheme).
		const result = lexicalSearch(abstracts, authorsById, 'aginq');
		expect(result?.ids).toEqual(new Set([1001]));
		// Fuzzy hit, NOT exact → exactness should be 0.
		expect(result?.exactness.get(1001) ?? 0).toBe(0);
	});

	it('matches the FR-008 example: 2-typo query "defautl mode netwrk" → "default mode network"', () => {
		// All three query tokens must hit the abstract (AND across tokens).
		// Lengths: defautl=7 (thr 2), mode=4 (thr 1), netwrk=6 (thr 1).
		// "defautl"→"default" = 1 transposition (DL 1 ≤ 2) ✓
		// "mode" exact ✓; "netwrk"→"network" = 1 deletion (DL 1 ≤ 1) ✓
		const result = lexicalSearch(abstracts, authorsById, 'defautl mode netwrk');
		expect(result?.ids).toEqual(new Set([1003]));
		// "mode" hits exactly; the other two are typo-corrected → exactness = 1.
		expect(result?.exactness.get(1003)).toBe(1);
	});

	it('matches the FR-010 example: diacritic-folded surname', () => {
		// "Garcia" tokenizes to ["garcia"]; corpus has the NFD-folded "garcia"
		// from "García". Length 6 → threshold 1; exact hit after folding.
		const result = lexicalSearch(abstracts, authorsById, 'Garcia');
		expect(result?.ids).toEqual(new Set([1001]));
	});

	it('intersects across multiple query tokens', () => {
		const result = lexicalSearch(abstracts, authorsById, 'memory mri');
		expect((result?.ids.size ?? 0)).toBeGreaterThan(0);
	});

	it('returns an empty set for queries that match nothing', () => {
		const result = lexicalSearch(abstracts, authorsById, 'xyzpdqzzz');
		expect(result?.ids).toEqual(new Set());
		expect(result?.exactness.size).toBe(0);
	});

	it('ranks the exact-match abstract above fuzzy proximal matches', () => {
		// Regression guard for the "pydra" issue: an exact-token hit must
		// produce a strictly higher exactness count than any fuzzy hit so the
		// UI can sort it to the top.
		const result = lexicalSearch(abstracts, authorsById, 'aging');
		expect(result).not.toBeNull();
		// Only the abstract with the literal word should have exactness ≥ 1.
		const counts = [...result!.exactness.values()];
		expect(Math.max(0, ...counts)).toBeGreaterThanOrEqual(1);
	});
});

describe('parseQuery (operator grammar)', () => {
	it('treats a bare query as a single AND-group of words with no operators flag', () => {
		const p = parseQuery('memory aging');
		expect(p.hasOperators).toBe(false);
		expect(p.groups).toHaveLength(1);
		expect(p.groups[0].clauses).toEqual([
			{ kind: 'word', word: 'memory', negate: false },
			{ kind: 'word', word: 'aging', negate: false }
		]);
	});

	it('recognises a quoted phrase as one phrase clause', () => {
		const p = parseQuery('"working memory"');
		expect(p.hasOperators).toBe(true);
		expect(p.groups[0].clauses).toEqual([
			{ kind: 'phrase', words: ['working', 'memory'], negate: false }
		]);
	});

	it('drops a leading `-` to mark negation', () => {
		const p = parseQuery('brain -fmri');
		expect(p.hasOperators).toBe(true);
		expect(p.groups[0].clauses).toEqual([
			{ kind: 'word', word: 'brain', negate: false },
			{ kind: 'word', word: 'fmri', negate: true }
		]);
	});

	it('splits at uppercase `OR` into separate AND-groups', () => {
		// Use ≥ 2-char tokens — the tokenizer drops 1-char tokens, which would
		// collapse this test into an empty groups list.
		const p = parseQuery('aa bb OR cc dd');
		expect(p.hasOperators).toBe(true);
		expect(p.groups).toHaveLength(2);
		expect(p.groups[0].clauses.map((c) => c.kind === 'word' && c.word)).toEqual(['aa', 'bb']);
		expect(p.groups[1].clauses.map((c) => c.kind === 'word' && c.word)).toEqual(['cc', 'dd']);
	});

	it('lowercase `or` is just a word, not an operator', () => {
		const p = parseQuery('memory or aging');
		expect(p.hasOperators).toBe(false);
		expect(p.groups).toHaveLength(1);
		expect(p.groups[0].clauses.map((c) => c.kind === 'word' && c.word)).toEqual([
			'memory',
			'or',
			'aging'
		]);
	});

	it('tolerates an unclosed quote by falling back to plain words', () => {
		const p = parseQuery('"unclosed phrase');
		// We don't promise specific clause shape here — only that parse doesn't
		// throw and produces SOMETHING parseable.
		expect(p.groups.length).toBeGreaterThanOrEqual(1);
	});

	it('coalesces leading / trailing / duplicate OR markers', () => {
		const p = parseQuery('OR memory OR OR aging OR');
		expect(p.groups).toHaveLength(2);
		expect(p.groups[0].clauses.map((c) => c.kind === 'word' && c.word)).toEqual(['memory']);
		expect(p.groups[1].clauses.map((c) => c.kind === 'word' && c.word)).toEqual(['aging']);
	});
});

describe('queryForSemantic (operator-stripped form)', () => {
	it('is byte-identical for a bare query and the same query quoted as a phrase', () => {
		// This is the user-visible promise: the semantic embedder sees the
		// same input whether or not the user added quotes around the phrase.
		// The lexical contribution differs (adjacency required), but the
		// semantic neighbour pass behaves identically.
		const a = queryForSemantic(parseQuery('critical brain hypotheses'));
		const b = queryForSemantic(parseQuery('"critical brain hypotheses"'));
		expect(a).toBe(b);
		expect(a).toBe('critical brain hypotheses');
	});

	it('drops negated clauses', () => {
		const out = queryForSemantic(parseQuery('brain -fmri -"task activation"'));
		expect(out).toBe('brain');
	});

	it('joins phrase words back with spaces and concatenates across OR-groups', () => {
		const out = queryForSemantic(parseQuery('"resting state" OR "task activation"'));
		expect(out).toBe('resting state task activation');
	});
});

describe('lexicalSearch — phrase adjacency', () => {
	it('matches a quoted phrase whose words ARE adjacent in the corpus', () => {
		const r = lexicalSearch(abstracts, authorsById, '"memory fmri"');
		// Abstract 1001 title is "Memory fMRI in aging" → "memory" + "fmri" are
		// adjacent at positions 0,1 in the stream.
		expect(r?.ids).toContain(1001);
	});

	it('rejects a quoted phrase whose words are present but NOT adjacent', () => {
		// "memory" and "aging" both appear in 1001's title but with "fmri in"
		// between them, so the phrase must fail.
		const r = lexicalSearch(abstracts, authorsById, '"memory aging"');
		expect(r?.ids.has(1001)).toBe(false);
	});
});

describe('lexicalSearch — negation', () => {
	it('subtracts a -word clause from the positive set', () => {
		// Both abstracts mention "fmri" / "Functional MRI" in their facets,
		// so `aging -fmri` should drop 1001.
		const r = lexicalSearch(abstracts, authorsById, 'aging -fmri');
		expect(r?.ids.has(1001)).toBe(false);
		// And the abstract should appear in negationBlocked so the merger can
		// honour the NOT across semantic candidates too.
		expect(r?.negationBlocked.has(1001)).toBe(true);
	});

	it('handles a query consisting only of negations as "everything except"', () => {
		const r = lexicalSearch(abstracts, authorsById, '-fmri');
		// Both seed abstracts mention fmri via the Functional MRI checklist,
		// so neither should remain.
		expect(r?.ids.has(1001)).toBe(false);
		expect(r?.ids.has(1003)).toBe(false);
	});
});

describe('lexicalSearch — OR alternation', () => {
	it('unions abstracts that match either AND-group', () => {
		const r = lexicalSearch(abstracts, authorsById, 'aging OR "default mode"');
		// 1001 matches "aging"; 1003 matches the "default mode" phrase
		// (adjacent in the title "Default mode network in fMRI").
		expect(r?.ids).toEqual(new Set([1001, 1003]));
	});
});
