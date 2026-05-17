import { writable, get } from 'svelte/store';

const STORAGE_KEY = 'ohbm2026.ui.searchMode.v1';

function isBrowser(): boolean {
	return typeof window !== 'undefined' && typeof window.localStorage !== 'undefined';
}

function loadInitial(): boolean {
	if (!isBrowser()) return true;
	const raw = window.localStorage.getItem(STORAGE_KEY);
	if (raw === '0') return false;
	return true; // default on
}

const _enabled = writable<boolean>(loadInitial());

function setEnabled(value: boolean): void {
	_enabled.set(value);
	if (isBrowser()) {
		try {
			window.localStorage.setItem(STORAGE_KEY, value ? '1' : '0');
		} catch {
			// silent degrade
		}
	}
}

function toggle(): void {
	setEnabled(!get(_enabled));
}

export const semanticEnabled = {
	subscribe: _enabled.subscribe,
	set: setEnabled,
	toggle
};

export const SEMANTIC_STORAGE_KEY = STORAGE_KEY;
