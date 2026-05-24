/**
 * Stage 15 (spec 015-neuroscape-context, FR-009 + T034) — the
 * `atlas_overlay` store powers the binary toggle on the bare-root
 * cross-conference atlas landing page. It MUST:
 *
 *   - default to `true` (overlay on);
 *   - persist writes to `localStorage` under `atlas_root.show_ohbm_overlay`;
 *   - hydrate from a `"0"` / `"1"` value on init;
 *   - default to `true` on missing or malformed localStorage values
 *     (Principle VI — never silently drift to a different state on a
 *     bad input).
 *
 * The contract matches `contracts/atlas-root-ui.md`.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';

const STORAGE_KEY = 'atlas_root.show_ohbm_overlay';

async function freshImport() {
	// The store's IIFE reads localStorage at module-load time, so we
	// need to reset vitest's module cache between tests to re-trigger
	// the hydration with the value the test just set.
	vi.resetModules();
	return await import('$lib/stores/atlas_overlay');
}

describe('atlas_overlay store', () => {
	beforeEach(() => {
		window.localStorage.clear();
	});

	afterEach(() => {
		window.localStorage.clear();
	});

	it('defaults to true (overlay on) when no localStorage value is set', async () => {
		const { atlasOverlay } = await freshImport();
		expect(get(atlasOverlay)).toBe(true);
	});

	it('hydrates from a `"1"` localStorage value', async () => {
		window.localStorage.setItem(STORAGE_KEY, '1');
		const { atlasOverlay } = await freshImport();
		expect(get(atlasOverlay)).toBe(true);
	});

	it('hydrates from a `"0"` localStorage value', async () => {
		window.localStorage.setItem(STORAGE_KEY, '0');
		const { atlasOverlay } = await freshImport();
		expect(get(atlasOverlay)).toBe(false);
	});

	it('defaults to true on a malformed localStorage value', async () => {
		window.localStorage.setItem(STORAGE_KEY, 'banana');
		const { atlasOverlay } = await freshImport();
		expect(get(atlasOverlay)).toBe(true);
	});

	it('persists writes to localStorage', async () => {
		const { atlasOverlay } = await freshImport();
		atlasOverlay.set(false);
		expect(window.localStorage.getItem(STORAGE_KEY)).toBe('0');
		atlasOverlay.set(true);
		expect(window.localStorage.getItem(STORAGE_KEY)).toBe('1');
	});

	it('toggle helper flips the current state and persists', async () => {
		const { atlasOverlay, toggleAtlasOverlay } = await freshImport();
		expect(get(atlasOverlay)).toBe(true);
		toggleAtlasOverlay();
		expect(get(atlasOverlay)).toBe(false);
		expect(window.localStorage.getItem(STORAGE_KEY)).toBe('0');
		toggleAtlasOverlay();
		expect(get(atlasOverlay)).toBe(true);
		expect(window.localStorage.getItem(STORAGE_KEY)).toBe('1');
	});
});
