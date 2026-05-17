import { writable, get } from 'svelte/store';

const STORAGE_KEY = 'ohbm2026.ui.cart.v1';

function _isBrowser(): boolean {
	return typeof window !== 'undefined' && typeof window.localStorage !== 'undefined';
}

function loadInitial(): Set<string> {
	if (!_isBrowser()) return new Set();
	try {
		const raw = window.localStorage.getItem(STORAGE_KEY);
		if (!raw) return new Set();
		const parsed = JSON.parse(raw);
		if (!Array.isArray(parsed)) return new Set();
		return new Set(parsed.filter((v) => typeof v === 'string'));
	} catch {
		return new Set();
	}
}

function persist(items: Set<string>): void {
	if (!_isBrowser()) return;
	try {
		window.localStorage.setItem(STORAGE_KEY, JSON.stringify([...items]));
	} catch {
		// localStorage may be unavailable (e.g. private-browsing quota) — silent
		// degrade. The store still works in-memory for the session.
	}
}

const _store = writable<Set<string>>(loadInitial());

function add(posterId: string): void {
	const next = new Set(get(_store));
	next.add(posterId);
	_store.set(next);
	persist(next);
}

function remove(posterId: string): void {
	const next = new Set(get(_store));
	next.delete(posterId);
	_store.set(next);
	persist(next);
}

function addMany(posterIds: Iterable<string>): void {
	const next = new Set(get(_store));
	for (const id of posterIds) if (id) next.add(id);
	_store.set(next);
	persist(next);
}

function removeMany(posterIds: Iterable<string>): void {
	const next = new Set(get(_store));
	for (const id of posterIds) next.delete(id);
	_store.set(next);
	persist(next);
}

function clear(): void {
	_store.set(new Set());
	persist(new Set());
}

function reset(items: Iterable<string> = []): void {
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
