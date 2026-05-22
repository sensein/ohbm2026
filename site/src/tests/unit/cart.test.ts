import { afterEach, describe, expect, it } from 'vitest';
import { get } from 'svelte/store';
import { cartStore, CART_STORAGE_KEY } from '$lib/stores/cart';

// Stage 10 migrated poster_id to int16; cartStore now stores numbers,
// not the legacy `M-AM-101` string ids.
describe('cartStore', () => {
	afterEach(() => {
		cartStore.reset();
		window.localStorage.removeItem(CART_STORAGE_KEY);
	});

	it('starts empty', () => {
		expect(get(cartStore).size).toBe(0);
	});

	it('add → contains the poster id', () => {
		cartStore.add(101);
		expect(get(cartStore).has(101)).toBe(true);
	});

	it('add is idempotent (set semantics)', () => {
		cartStore.add(101);
		cartStore.add(101);
		expect(get(cartStore).size).toBe(1);
	});

	it('remove drops the poster id', () => {
		cartStore.add(101);
		cartStore.add(102);
		cartStore.remove(101);
		expect(get(cartStore).has(101)).toBe(false);
		expect(get(cartStore).has(102)).toBe(true);
	});

	it('clear empties the cart', () => {
		cartStore.add(101);
		cartStore.add(102);
		cartStore.clear();
		expect(get(cartStore).size).toBe(0);
	});

	it('persists to localStorage', () => {
		cartStore.add(101);
		cartStore.add(102);
		const raw = window.localStorage.getItem(CART_STORAGE_KEY);
		expect(raw).not.toBeNull();
		const parsed = JSON.parse(raw!);
		expect(new Set(parsed)).toEqual(new Set([101, 102]));
	});

	it('clear wipes the persisted payload', () => {
		cartStore.add(101);
		cartStore.clear();
		const raw = window.localStorage.getItem(CART_STORAGE_KEY);
		expect(JSON.parse(raw!)).toEqual([]);
	});

	it('addMany unions multiple poster ids in one update', () => {
		cartStore.add(100);
		cartStore.addMany([101, 102, 100]); // 100 already present
		expect(get(cartStore)).toEqual(new Set([100, 101, 102]));
	});

	it('removeMany deletes only the listed poster ids', () => {
		cartStore.addMany([1, 2, 3, 4]);
		cartStore.removeMany([2, 4, 999]); // unknown id is a no-op
		expect(get(cartStore)).toEqual(new Set([1, 3]));
	});
});
