import { writable, get } from 'svelte/store';

export type ThemeChoice = 'light' | 'dark' | 'auto';

const STORAGE_KEY = 'ohbm2026.ui.theme.v1';

function isBrowser(): boolean {
	return typeof window !== 'undefined' && typeof document !== 'undefined';
}

function loadInitial(): ThemeChoice {
	if (!isBrowser()) return 'auto';
	const raw = window.localStorage?.getItem(STORAGE_KEY);
	if (raw === 'light' || raw === 'dark' || raw === 'auto') return raw;
	return 'auto';
}

function systemPref(): 'light' | 'dark' {
	if (!isBrowser()) return 'light';
	return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
}

/**
 * Compute the effective theme — what `data-theme` should be set to on
 * `<html>`. `auto` resolves to the system preference at this moment.
 */
function resolve(choice: ThemeChoice): 'light' | 'dark' {
	return choice === 'auto' ? systemPref() : choice;
}

function applyToDocument(effective: 'light' | 'dark') {
	if (!isBrowser()) return;
	document.documentElement.setAttribute('data-theme', effective);
	document.documentElement.style.colorScheme = effective;
}

const choiceStore = writable<ThemeChoice>(loadInitial());
const effectiveStore = writable<'light' | 'dark'>(resolve(get(choiceStore)));

if (isBrowser()) {
	// Apply on first import so SSR-hydration matches.
	applyToDocument(get(effectiveStore));

	// Watch the system preference; only re-render when current choice is auto.
	const mq = window.matchMedia('(prefers-color-scheme: dark)');
	const onSystemChange = () => {
		if (get(choiceStore) !== 'auto') return;
		const eff = resolve('auto');
		effectiveStore.set(eff);
		applyToDocument(eff);
	};
	// Modern + legacy listener support.
	if (typeof mq.addEventListener === 'function') mq.addEventListener('change', onSystemChange);
	else if (typeof mq.addListener === 'function') mq.addListener(onSystemChange);
}

function setChoice(choice: ThemeChoice): void {
	choiceStore.set(choice);
	const eff = resolve(choice);
	effectiveStore.set(eff);
	applyToDocument(eff);
	if (isBrowser()) {
		try {
			window.localStorage.setItem(STORAGE_KEY, choice);
		} catch {
			// localStorage may be unavailable; silently degrade.
		}
	}
}

function cycle(): void {
	const order: ThemeChoice[] = ['light', 'dark', 'auto'];
	const current = get(choiceStore);
	const next = order[(order.indexOf(current) + 1) % order.length];
	setChoice(next);
}

export const themeChoice = {
	subscribe: choiceStore.subscribe,
	set: setChoice,
	cycle
};

export const effectiveTheme = {
	subscribe: effectiveStore.subscribe
};

export const THEME_STORAGE_KEY = STORAGE_KEY;
