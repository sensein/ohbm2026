/**
 * Unit tests for the shared N-corpus search-result assembly.
 * Uses real buildTitleIndex/searchTitleIndex over tiny corpora (single-word
 * titles → predictable lexical matches) so the helper's own contract is
 * exercised end-to-end: cross-corpus merge by sort-key, semantic-only append,
 * id: short-circuit, has()-gating, empty query.
 */
import { describe, it, expect } from 'vitest';
import { buildTitleIndex } from '$lib/filter';
import { assembleResults, type CorpusSource } from '$lib/search/assemble';

type Rec = { id: number; title: string };

function src(kind: string, recs: Rec[], opts: Partial<CorpusSource<Rec>> = {}): CorpusSource<Rec> {
	const byId = new Map(recs.map((r) => [r.id, r]));
	return {
		kind,
		index: buildTitleIndex(
			recs,
			(r) => r.id,
			(r) => r.title
		),
		has: (id: number) => byId.has(id),
		allIds: () => byId.keys(),
		toRow: (id: number) => byId.get(id) ?? null,
		lexicalSortKey: (_id: number, exact: number) => [-exact, _id],
		emptySortKey: (id: number) => [id],
		...opts
	};
}

describe('assembleResults — shared N-corpus assembly', () => {
	it('merges lexical hits across corpora, ordered by the sort-key tuple', () => {
		const a = src('a', [
			{ id: 1, title: 'memory' },
			{ id: 2, title: 'memory' }
		]);
		const b = src('b', [{ id: 9, title: 'memory' }]);
		const out = assembleResults([a, b], 'memory');
		// all exact=1 → key [-1, id] → id asc across both corpora
		expect(out.map((r) => r.id)).toEqual([1, 2, 9]);
	});

	it('appends semantic-only hits (not already lexical) by ascending distance', () => {
		const a = src('a', [
			{ id: 1, title: 'memory' },
			{ id: 2, title: 'other' },
			{ id: 3, title: 'unrelated' }
		]);
		a.semanticHits = new Map([
			[1, 0.05], // already lexical → must NOT duplicate
			[3, 0.2],
			[2, 0.3]
		]);
		const out = assembleResults([a], 'memory');
		// lexical [1], then semantic-only by distance: 3 (0.2) before 2 (0.3)
		expect(out.map((r) => r.id)).toEqual([1, 3, 2]);
	});

	it('id:N short-circuits across every source in source order', () => {
		const a = src('a', [{ id: 5, title: 'x' }]);
		const b = src('b', [{ id: 5, title: 'y' }]);
		const out = assembleResults([a, b], 'id:5');
		expect(out).toEqual([
			{ id: 5, title: 'x' },
			{ id: 5, title: 'y' }
		]);
	});

	it('id: with a non-numeric / empty payload yields no rows', () => {
		const a = src('a', [{ id: 1, title: 'memory' }]);
		expect(assembleResults([a], 'id:foo')).toEqual([]);
		expect(assembleResults([a], 'id:')).toEqual([]);
	});

	it('excludes semantic hits outside the facet-filtered set (has() gate)', () => {
		const a = src('a', [{ id: 1, title: 'memory' }], {
			has: (id: number) => id === 1,
			semanticHits: new Map([[99, 0.1]]) // 99 not in has() → excluded
		});
		expect(assembleResults([a], 'memory').map((r) => r.id)).toEqual([1]);
	});

	it('empty query returns every row ordered by emptySortKey', () => {
		const a = src('a', [
			{ id: 3, title: 'a' },
			{ id: 1, title: 'b' }
		]);
		expect(assembleResults([a], '').map((r) => r.id)).toEqual([1, 3]);
	});
});
