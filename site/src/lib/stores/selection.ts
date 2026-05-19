import { writable } from 'svelte/store';

export interface CellSelection {
	model: string;
	input: string;
}

export const selectedCell = writable<CellSelection>({ model: 'neuroscape', input: 'abstract' });

export const searchQuery = writable<string>('');

export const activeFilters = writable<Map<string, Set<string>>>(new Map());

export const lassoSelection = writable<Set<number> | null>(null);

/** Currently-focused abstract's poster_id (int). Null when no abstract is
 *  focused. Stage 10: was `string | null` when poster_id was the string
 *  form; now matches AbstractRecord.poster_id's number type. */
export const focusedAbstract = writable<number | null>(null);

/** "Show only saved" — restricts the result list to items currently in the
 *  cart. Pairs with the bulk-add affordance: save a set, flip this on,
 *  refine. Default off. Not persisted; resets per session. */
export const cartOnly = writable<boolean>(false);

/** Active author-name chips. Clicking an author name in any detail view
 *  adds the name to this set; the result list intersects with abstracts
 *  whose `author_ids` include any of these names. Render as removable
 *  chips next to the search bar; clearing them all returns to the
 *  unfiltered (by author) state. Non-destructive — coexists with the
 *  search query / facets / lasso. */
export const authorChips = writable<Set<string>>(new Set());

/** Persisted "Show map" panel toggle. Restored from localStorage on
 *  startup so a browser reload keeps the user's chosen view (the
 *  Semantic toggle already had this; the map toggle was a plain
 *  component variable that reset to false on every reload). */
const SHOW_MAP_STORAGE_KEY = 'ohbm2026.ui.showMap.v1';

function loadShowMap(): boolean {
	// Default ON — new users land with the UMAP open so the corpus is
	// visible at a glance. Stored value wins once the user has toggled,
	// so a chosen-OFF state survives reloads.
	if (typeof window === 'undefined' || typeof window.localStorage === 'undefined') return true;
	try {
		const raw = window.localStorage.getItem(SHOW_MAP_STORAGE_KEY);
		if (raw === '0') return false;
		if (raw === '1') return true;
		return true; // no prior choice → default ON
	} catch {
		return true;
	}
}

const _showMap = writable<boolean>(loadShowMap());
_showMap.subscribe((v) => {
	if (typeof window === 'undefined' || typeof window.localStorage === 'undefined') return;
	try {
		window.localStorage.setItem(SHOW_MAP_STORAGE_KEY, v ? '1' : '0');
	} catch {
		/* private mode / quota — best effort */
	}
});

export const showMap = _showMap;
