import { describe, expect, it } from 'vitest';
import { searchAbstracts, normalize } from '$lib/filter';
import type { AbstractRecord, AuthorRecord } from '$lib/shards';

const author: AuthorRecord = {
	author_id: 0,
	name: 'José García',
	affiliations: ['UAM Madrid'],
	poster_ids: [101]
};

const abstracts: AbstractRecord[] = [
	{
		poster_id: 101,
		title: 'Memory fMRI in aging',
		accepted_for: 'Poster',
		sections: {
			introduction: '',
			methods: '',
			results: '',
			conclusion: '',
			references: ''
		},
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
		poster_id: 103,
		title: 'Default mode network in fMRI',
		accepted_for: 'Oral',
		sections: {
			introduction: '',
			methods: '',
			results: '',
			conclusion: '',
			references: ''
		},
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

describe('searchAbstracts', () => {
	it('returns null for empty query', () => {
		expect(searchAbstracts(abstracts, authorsById, '')).toBeNull();
		expect(searchAbstracts(abstracts, authorsById, '   ')).toBeNull();
	});

	it('matches title substring', () => {
		const ids = searchAbstracts(abstracts, authorsById, 'memory fmri');
		expect(ids).toEqual(new Set([101]));
	});

	it('matches poster_id', () => {
		// poster_id is a number now; the haystack stringifies it.
		const ids = searchAbstracts(abstracts, authorsById, '103');
		expect(ids).toEqual(new Set([103]));
	});

	it('matches author name', () => {
		const ids = searchAbstracts(abstracts, authorsById, 'García');
		expect(ids).toEqual(new Set([101]));
	});

	it('is diacritic-insensitive (FR-010)', () => {
		const ids = searchAbstracts(abstracts, authorsById, 'Garcia');
		expect(ids).toEqual(new Set([101]));
	});

	it('matches facet values', () => {
		const ids = searchAbstracts(abstracts, authorsById, 'DMN');
		expect(ids).toEqual(new Set([103]));
	});

	it('empty result set when no match', () => {
		const ids = searchAbstracts(abstracts, authorsById, 'xyzpdq');
		expect(ids).toEqual(new Set());
	});
});

describe('normalize', () => {
	it('lowercases + strips diacritics', () => {
		expect(normalize('García')).toBe('garcia');
		expect(normalize('JOSÉ')).toBe('jose');
	});
});
