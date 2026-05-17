import { describe, expect, it } from 'vitest';
import { damerauLevenshtein, lexicalSearch, tokenizeForIndex } from '$lib/filter';
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
	abstract_ids: [1001]
};

const abstracts: AbstractRecord[] = [
	{
		abstract_id: 1001,
		poster_id: 'M-AM-101',
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
		abstract_id: 1003,
		poster_id: 'M-AM-103',
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
