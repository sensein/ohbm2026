/**
 * Stage 15 (spec 015-neuroscape-context, FR-009): the binary toggle
 * that controls whether the OHBM 2026 overlay is rendered on top of
 * the NeuroScape backdrop on the bare-root cross-conference atlas
 * landing page.
 *
 * Mirrors the pattern of {@link import("./selection").showMap} —
 * localStorage-backed writable boolean, default ON, malformed
 * inputs fall back to ON (Principle VI: never silently drift to a
 * different state).
 *
 * Contract pinned by {@link "specs/015-neuroscape-context/contracts/atlas-root-ui.md"}.
 */

import { writable } from 'svelte/store';

const STORAGE_KEY = 'atlas_root.show_ohbm_overlay';

function loadAtlasOverlay(): boolean {
	if (typeof window === 'undefined' || typeof window.localStorage === 'undefined') return true;
	try {
		const raw = window.localStorage.getItem(STORAGE_KEY);
		if (raw === '0') return false;
		if (raw === '1') return true;
		return true; // missing or malformed → default ON
	} catch {
		return true;
	}
}

const _atlasOverlay = writable<boolean>(loadAtlasOverlay());
_atlasOverlay.subscribe((v) => {
	if (typeof window === 'undefined' || typeof window.localStorage === 'undefined') return;
	try {
		window.localStorage.setItem(STORAGE_KEY, v ? '1' : '0');
	} catch {
		/* private mode / quota — best effort */
	}
});

export const atlasOverlay = _atlasOverlay;

/** Flip the current overlay state. Convenience wrapper for the
 *  `<AtlasOverlayToggle>` component's `on:change` handler. */
export function toggleAtlasOverlay(): void {
	_atlasOverlay.update((v) => !v);
}
