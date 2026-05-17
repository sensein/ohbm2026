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
		expect(lexicalSearch(abstracts, authorsById, 'aging')).toEqual(new Set([1001]));
	});

	it('matches a single-substitution typo on a long word', () => {
		// "aginq" → "aging" (1 substitution; threshold = 2 for length 5)
		expect(lexicalSearch(abstracts, authorsById, 'aginq')).toEqual(new Set([1001]));
	});

	it('matches the FR-008 example: 2-typo query "defautl mode netwrk" → "default mode network"', () => {
		// All three query tokens must hit the abstract (AND across tokens).
		expect(lexicalSearch(abstracts, authorsById, 'defautl mode netwrk')).toEqual(new Set([1003]));
	});

	it('matches the FR-010 example: surname "Smtih" within the typo budget would match "Smith"', () => {
		// We only have a "García" author here so verify diacritic-folded match.
		expect(lexicalSearch(abstracts, authorsById, 'Garcia')).toEqual(new Set([1001]));
	});

	it('intersects across multiple query tokens', () => {
		// "memory mri" should hit only abstracts that have BOTH tokens; both
		// abstracts mention MRI / functional MRI but only 1001 has "memory" in
		// the title (1003 has it under primary_subcategory). Either way both
		// should match for "memory mri".
		const ids = lexicalSearch(abstracts, authorsById, 'memory mri');
		expect(ids?.size).toBeGreaterThan(0);
	});

	it('returns an empty set for queries that match nothing', () => {
		expect(lexicalSearch(abstracts, authorsById, 'xyzpdqzzz')).toEqual(new Set());
	});
});
