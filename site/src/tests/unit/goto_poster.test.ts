import { describe, expect, it } from 'vitest';
import {
	parseIdOperator,
	normaliseQuery,
	filterSuggestions,
	type SuggestionResult
} from '$lib/goto_poster';
import type { AbstractRecord } from '$lib/shards';

/**
 * Stage 14 — pure-function tests for the `id:` operator navigator.
 * Spec: `specs/014-poster-id-nav/data-model.md` §"Activation rule"
 * + §"Matching rule" + §"Worked examples".
 */

// Build a tiny fixture map. Only the fields the filter touches need
// to be populated; the rest of AbstractRecord is filled with stubs.
function rec(posterId: number, title = `Title ${posterId}`): AbstractRecord {
	return {
		poster_id: posterId,
		title,
		accepted_for: 'Poster',
		authors: [],
		external_urls: [],
		figure_urls: [],
		program_sessions: [],
		local_assets: [],
		responses: []
	} as unknown as AbstractRecord;
}

function fixtureMap(ids: number[]): Map<number, AbstractRecord> {
	return new Map(ids.map((id) => [id, rec(id)]));
}

describe('parseIdOperator', () => {
	it('returns the payload for `id:<digits>`', () => {
		expect(parseIdOperator('id:1234')).toBe('1234');
	});

	it('is case-insensitive on the prefix', () => {
		expect(parseIdOperator('ID:34')).toBe('34');
		expect(parseIdOperator('Id:34')).toBe('34');
	});

	it('returns "" for the bare prefix `id:`', () => {
		expect(parseIdOperator('id:')).toBe('');
	});

	it('returns null when no colon is present', () => {
		expect(parseIdOperator('id')).toBeNull();
	});

	it('returns null when `id:` is embedded mid-query', () => {
		expect(parseIdOperator('something id:34')).toBeNull();
		expect(parseIdOperator(' id:34')).toBeNull(); // leading whitespace counts as not-at-start
	});

	it('returns null for other operators', () => {
		expect(parseIdOperator('topic:Memory')).toBeNull();
		expect(parseIdOperator('methods:fMRI')).toBeNull();
	});

	it('returns null on empty input', () => {
		expect(parseIdOperator('')).toBeNull();
	});

	it('preserves the rest of the payload verbatim (incl. spaces)', () => {
		// normaliseQuery strips spaces / non-digits later; parser is dumb.
		expect(parseIdOperator('id:12 3')).toBe('12 3');
		expect(parseIdOperator('id:  012  ')).toBe('  012  ');
	});
});

describe('normaliseQuery', () => {
	it('returns "" for empty / whitespace-only / pure-zero', () => {
		expect(normaliseQuery('')).toBe('');
		expect(normaliseQuery('   ')).toBe('');
		expect(normaliseQuery('0')).toBe('');
		expect(normaliseQuery('00')).toBe('');
		expect(normaliseQuery('0000')).toBe('');
	});

	it('strips leading zeros from numeric payloads', () => {
		expect(normaliseQuery('0345')).toBe('345');
		expect(normaliseQuery('00345')).toBe('345');
	});

	it('strips non-digit characters', () => {
		expect(normaliseQuery('12 3')).toBe('123');
		expect(normaliseQuery('abc12def3')).toBe('123');
	});

	it('preserves a digit-only payload that has no leading zeros', () => {
		expect(normaliseQuery('2094')).toBe('2094');
	});
});

describe('filterSuggestions', () => {
	const fixture = fixtureMap([12, 121, 129, 212, 1012, 1200, 1299, 2094]);

	function visibleIds(r: SuggestionResult): number[] {
		return r.visible.map((s) => s.posterId);
	}

	it('returns empty result for empty / pure-zero queries', () => {
		expect(visibleIds(filterSuggestions('', fixture))).toEqual([]);
		expect(filterSuggestions('', fixture).total).toBe(0);
		expect(filterSuggestions('0', fixture).total).toBe(0);
		expect(filterSuggestions('0000', fixture).total).toBe(0);
	});

	it('prefix `12` matches 12 / 121 / 129 / 1200 / 1299 and excludes 212 / 1012', () => {
		const r = filterSuggestions('12', fixture);
		// Per the user's clarification 2026-05-22: `12` MUST NOT surface
		// `1012` or `0212`. This is the canonical test for that rule.
		expect(visibleIds(r)).toEqual([12, 121, 129, 1200, 1299]);
		expect(r.total).toBe(5);
		expect(r.exactMatch).toBeNull();
	});

	it('treats leading-zero payloads as equivalent to the trimmed integer', () => {
		const a = filterSuggestions('12', fixture);
		const b = filterSuggestions('0012', fixture);
		expect(visibleIds(b)).toEqual(visibleIds(a));
		expect(b.total).toBe(a.total);
	});

	it('returns total: 1 + exactMatch for an exact in-corpus hit', () => {
		const r = filterSuggestions('2094', fixture);
		expect(visibleIds(r)).toEqual([2094]);
		expect(r.total).toBe(1);
		expect(r.exactMatch?.posterId).toBe(2094);
		expect(r.exactMatch?.display).toBe('2094');
		expect(r.exactMatch?.title).toBe('Title 2094');
	});

	it('returns total: 0 + exactMatch: null for no-match queries', () => {
		const r = filterSuggestions('9999', fixture);
		expect(visibleIds(r)).toEqual([]);
		expect(r.total).toBe(0);
		expect(r.exactMatch).toBeNull();
	});

	it('honors the visible cap (default 10) while reporting full total', () => {
		// Build a fixture with 15 ids whose string starts with "1": 1, 10..19, 100..103
		const many = fixtureMap([1, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 100, 101, 102, 103]);
		const r = filterSuggestions('1', many);
		expect(r.visible.length).toBe(10);
		expect(r.total).toBe(15);
		expect(r.exactMatch).toBeNull(); // not an exact match — total > 1
	});

	it('respects an explicit `limit` argument', () => {
		const r = filterSuggestions('1', fixtureMap([1, 10, 11, 100, 1000]), 3);
		expect(r.visible.length).toBe(3);
		expect(r.total).toBe(5);
	});

	it('sorts visible suggestions ascending by posterId', () => {
		const r = filterSuggestions('12', fixture);
		const ids = visibleIds(r);
		expect(ids).toEqual([...ids].sort((a, b) => a - b));
	});

	it('emits the 4-digit zero-padded display string', () => {
		const r = filterSuggestions('2094', fixture);
		expect(r.visible[0].display).toBe('2094');

		const r2 = filterSuggestions('12', fixtureMap([12]));
		expect(r2.visible[0].display).toBe('0012');
	});
});
