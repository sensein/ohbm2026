import { writable, get } from 'svelte/store';

const STORAGE_KEY = 'ohbm2026.ui.cart.v1';

function _isBrowser(): boolean {
	return typeof window !== 'undefined' && typeof window.localStorage !== 'undefined';
}

function _toPosterId(v: unknown): number | null {
	// Accept the legacy stringified poster_id format ("0503") and the new
	// number form. Anything else (non-numeric, NaN) is dropped silently.
	if (typeof v === 'number') return Number.isFinite(v) ? v : null;
	if (typeof v === 'string') {
		const n = Number(v);
		return Number.isFinite(n) && /^[0-9]+$/.test(v) ? n : null;
	}
	return null;
}

function loadInitial(): Set<number> {
	if (!_isBrowser()) return new Set();
	try {
		const raw = window.localStorage.getItem(STORAGE_KEY);
		if (!raw) return new Set();
		const parsed = JSON.parse(raw);
		if (!Array.isArray(parsed)) return new Set();
		const out = new Set<number>();
		for (const v of parsed) {
			const id = _toPosterId(v);
			if (id !== null) out.add(id);
		}
		return out;
	} catch {
		return new Set();
	}
}

function persist(items: Set<number>): void {
	if (!_isBrowser()) return;
	try {
		window.localStorage.setItem(STORAGE_KEY, JSON.stringify([...items]));
	} catch {
		// localStorage may be unavailable (e.g. private-browsing quota) — silent
		// degrade. The store still works in-memory for the session.
	}
}

const _store = writable<Set<number>>(loadInitial());

function add(posterId: number): void {
	const next = new Set(get(_store));
	next.add(posterId);
	_store.set(next);
	persist(next);
}

function remove(posterId: number): void {
	const next = new Set(get(_store));
	next.delete(posterId);
	_store.set(next);
	persist(next);
}

function addMany(posterIds: Iterable<number>): void {
	const next = new Set(get(_store));
	for (const id of posterIds) if (id) next.add(id);
	_store.set(next);
	persist(next);
}

function removeMany(posterIds: Iterable<number>): void {
	const next = new Set(get(_store));
	for (const id of posterIds) next.delete(id);
	_store.set(next);
	persist(next);
}

function clear(): void {
	_store.set(new Set());
	persist(new Set());
}

function reset(items: Iterable<number> = []): void {
	const next = new Set(items);
	_store.set(next);
	persist(next);
}

export const cartStore = {
	subscribe: _store.subscribe,
	add,
	remove,
	addMany,
	removeMany,
	clear,
	reset
};

export const CART_STORAGE_KEY = STORAGE_KEY;
