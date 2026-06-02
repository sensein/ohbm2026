/**
 * Spec 021 — intersection composition contract
 * (specs/021-atlas-cart-lasso/contracts/selection-composition.md, C1–C6).
 *
 * `compose()` is the single shared primitive that all three sibling sites use
 * to combine the active filters (search ∩ lasso ∩ facets ∩ cart-only) into one
 * visible/highlighted id-set. An inactive filter is `null` (identity); an
 * active-but-empty filter forces an empty result.
 */

import { describe, expect, it } from 'vitest';
import { compose } from '$lib/selection/compose';

const S = (...xs: number[]) => new Set<number>(xs);

describe('compose() — intersection of active filters', () => {
	it('C1: all-null → null (no filter active)', () => {
		expect(compose([null, null, null])).toBeNull();
		expect(compose([])).toBeNull();
	});

	it('C2: a single active filter is the identity (same membership)', () => {
		const r = compose([S(1, 2, 3), null, null]);
		expect(r).not.toBeNull();
		expect([...(r as Set<number>)].sort()).toEqual([1, 2, 3]);
	});

	it('C3: intersection of two active filters; order-independent', () => {
		const a = compose([S(1, 2, 3), S(2, 3, 4)]);
		const b = compose([S(2, 3, 4), S(1, 2, 3)]);
		expect([...(a as Set<number>)].sort()).toEqual([2, 3]);
		expect([...(b as Set<number>)].sort()).toEqual([2, 3]);
	});

	it('C4: an inactive (null) filter never narrows the result', () => {
		const withNull = compose([S(1, 2, 3), null, S(2, 3, 4)]);
		const without = compose([S(1, 2, 3), S(2, 3, 4)]);
		expect([...(withNull as Set<number>)].sort()).toEqual([...(without as Set<number>)].sort());
	});

	it('C5: an active EMPTY filter forces an empty result (not identity)', () => {
		const r = compose([S(1, 2, 3), S()]);
		expect(r).not.toBeNull();
		expect((r as Set<number>).size).toBe(0);
	});

	it('C6: result ⊆ every active part (no stray ids introduced)', () => {
		const r = compose([S(1, 2, 3, 4), S(2, 4, 6), S(2, 4, 8)]) as Set<number>;
		expect([...r].sort()).toEqual([2, 4]);
		for (const id of r) {
			expect(S(1, 2, 3, 4).has(id) && S(2, 4, 6).has(id) && S(2, 4, 8).has(id)).toBe(true);
		}
	});

	it('does not mutate the input sets', () => {
		const a = S(1, 2, 3);
		const b = S(2, 3, 4);
		compose([a, b]);
		expect([...a].sort()).toEqual([1, 2, 3]);
		expect([...b].sort()).toEqual([2, 3, 4]);
	});

	it('cart-as-intersecting-term: cart off (null) is identity; cart on narrows', () => {
		const search = S(1, 2, 3, 4);
		const cartOff = compose([search, null]);
		const cartOn = compose([search, S(2, 4, 9)]);
		expect([...(cartOff as Set<number>)].sort()).toEqual([1, 2, 3, 4]);
		expect([...(cartOn as Set<number>)].sort()).toEqual([2, 4]);
	});
});
