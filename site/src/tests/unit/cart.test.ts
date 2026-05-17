import { afterEach, describe, expect, it } from 'vitest';
import { get } from 'svelte/store';
import { cartStore, CART_STORAGE_KEY } from '$lib/stores/cart';

describe('cartStore', () => {
	afterEach(() => {
		cartStore.reset();
		window.localStorage.removeItem(CART_STORAGE_KEY);
	});

	it('starts empty', () => {
		expect(get(cartStore).size).toBe(0);
	});

	it('add → contains the poster id', () => {
		cartStore.add('M-AM-101');
		expect(get(cartStore).has('M-AM-101')).toBe(true);
	});

	it('add is idempotent (set semantics)', () => {
		cartStore.add('M-AM-101');
		cartStore.add('M-AM-101');
		expect(get(cartStore).size).toBe(1);
	});

	it('remove drops the poster id', () => {
		cartStore.add('M-AM-101');
		cartStore.add('M-AM-102');
		cartStore.remove('M-AM-101');
		expect(get(cartStore).has('M-AM-101')).toBe(false);
		expect(get(cartStore).has('M-AM-102')).toBe(true);
	});

	it('clear empties the cart', () => {
		cartStore.add('M-AM-101');
		cartStore.add('M-AM-102');
		cartStore.clear();
		expect(get(cartStore).size).toBe(0);
	});

	it('persists to localStorage', () => {
		cartStore.add('M-AM-101');
		cartStore.add('M-AM-102');
		const raw = window.localStorage.getItem(CART_STORAGE_KEY);
		expect(raw).not.toBeNull();
		const parsed = JSON.parse(raw!);
		expect(new Set(parsed)).toEqual(new Set(['M-AM-101', 'M-AM-102']));
	});

	it('clear wipes the persisted payload', () => {
		cartStore.add('M-AM-101');
		cartStore.clear();
		const raw = window.localStorage.getItem(CART_STORAGE_KEY);
		expect(JSON.parse(raw!)).toEqual([]);
	});

	it('addMany unions multiple poster ids in one update', () => {
		cartStore.add('M-AM-100');
		cartStore.addMany(['M-AM-101', 'M-AM-102', 'M-AM-100']); // 100 already present
		expect(get(cartStore)).toEqual(new Set(['M-AM-100', 'M-AM-101', 'M-AM-102']));
	});

	it('removeMany deletes only the listed poster ids', () => {
		cartStore.addMany(['a', 'b', 'c', 'd']);
		cartStore.removeMany(['b', 'd', 'zzz']); // unknown id is a no-op
		expect(get(cartStore)).toEqual(new Set(['a', 'c']));
	});
});
