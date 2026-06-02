/**
 * Spec 021 — cross-site cart scope for the "Cart only" filter
 * (specs/021-atlas-cart-lasso/contracts/cart-only-filter.md, F2/W4/W5).
 *
 * The cart spans sites (kind: 'ohbm2026' | 'neuroscape' | …). On a given site,
 * only saved items present in THAT site's loaded corpus index are displayable;
 * the rest drive the cross-site warning. "Present" is decided by runtime
 * membership (`indexHas`), never by a hardcoded kind→site table (Constitution
 * VII), so an unknown kind is counted + named, never silently dropped.
 */

import { describe, expect, it } from 'vitest';
import { savedInCorpus, shownIds } from '$lib/selection/cart_scope';
import type { CartItem } from '$lib/stores/cart';

const cart: CartItem[] = [
	{ kind: 'ohbm2026', id: 101 },
	{ kind: 'ohbm2026', id: 102 },
	{ kind: 'neuroscape', id: 9001 },
	{ kind: 'neuroscape', id: 9002 },
	{ kind: 'neuroscape', id: 9003 }
];

describe('savedInCorpus()', () => {
	it('neuroscape mode: only neuroscape ids present in the corpus are shown; ohbm items hidden', () => {
		// neuroscape corpus has 9001, 9002 (not 9003); no ohbm ids.
		const neuroIndex = new Set([9001, 9002]);
		const scope = savedInCorpus(cart, (kind, id) => kind === 'neuroscape' && neuroIndex.has(id));
		expect([...shownIds(scope, 'neuroscape')].sort()).toEqual([9001, 9002]);
		// 9003 (not in corpus) + 101,102 (ohbm) are hidden = 3
		expect(scope.hiddenCount).toBe(3);
		expect(scope.hiddenKinds.sort()).toEqual(['neuroscape', 'ohbm2026']);
	});

	it('ohbm mode: only ohbm ids present are shown; neuroscape items hidden', () => {
		const ohbmIndex = new Set([101, 102]);
		const scope = savedInCorpus(cart, (kind, id) => kind === 'ohbm2026' && ohbmIndex.has(id));
		expect([...shownIds(scope, 'ohbm2026')].sort()).toEqual([101, 102]);
		expect(scope.hiddenCount).toBe(3); // the 3 neuroscape items
		expect(scope.hiddenKinds).toEqual(['neuroscape']);
	});

	it('W4 atlas-root: both kinds displayable ⇒ nothing hidden, per-kind sets populated', () => {
		const ohbmIndex = new Set([101, 102]);
		const neuroIndex = new Set([9001, 9002, 9003]);
		const scope = savedInCorpus(
			cart,
			(kind, id) =>
				(kind === 'ohbm2026' && ohbmIndex.has(id)) || (kind === 'neuroscape' && neuroIndex.has(id))
		);
		expect(scope.hiddenCount).toBe(0);
		expect([...shownIds(scope, 'ohbm2026')].sort()).toEqual([101, 102]);
		expect([...shownIds(scope, 'neuroscape')].sort()).toEqual([9001, 9002, 9003]);
	});

	it('W5: an unknown kind is counted + named, never silently dropped', () => {
		const withUnknown: CartItem[] = [...cart, { kind: 'future' as CartItem['kind'], id: 5 }];
		const neuroIndex = new Set([9001, 9002, 9003]);
		const scope = savedInCorpus(
			withUnknown,
			(kind, id) => kind === 'neuroscape' && neuroIndex.has(id)
		);
		// hidden = 101,102 (ohbm) + 5 (future) = 3
		expect(scope.hiddenCount).toBe(3);
		expect(scope.hiddenKinds).toContain('future');
		expect(scope.hiddenKinds).toContain('ohbm2026');
	});

	it('empty cart ⇒ nothing shown, nothing hidden', () => {
		const scope = savedInCorpus([], () => true);
		expect(scope.hiddenCount).toBe(0);
		expect(shownIds(scope, 'neuroscape').size).toBe(0);
	});

	it('shownIds() returns an empty set for a kind with no shown items', () => {
		const scope = savedInCorpus(cart, () => false);
		expect(shownIds(scope, 'ohbm2026').size).toBe(0);
		expect(scope.hiddenCount).toBe(cart.length);
	});
});
