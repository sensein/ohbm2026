/**
 * Spec 021 — cross-site cart scope for the "Cart only" filter.
 *
 * The cart is shared across the sibling sites (`CartItem.kind`). On any one
 * site only the saved items whose `(kind, id)` is present in THAT site's
 * loaded corpus index are displayable; the rest feed the facet-style
 * cross-site warning. Membership is decided at runtime by the caller's
 * `indexHas` (Constitution VII — no hardcoded kind→site table), so a saved
 * item with an unrecognized kind is COUNTED + NAMED in the warning rather than
 * silently dropped.
 *
 * `shownByKind` keys the displayable ids per kind because id spaces differ
 * across kinds (ohbm poster_id vs neuroscape pubmed_id) and atlas-root shows
 * both at once. Single-corpus sites read one kind via `shownIds()`.
 *
 * Contract: specs/021-atlas-cart-lasso/contracts/cart-only-filter.md.
 */

import type { CartItem } from '$lib/stores/cart';

export interface SavedScope {
	/** Displayable saved ids in the current corpus, grouped by kind. */
	shownByKind: Map<string, Set<number>>;
	/** Count of saved items NOT present in the current site's corpus. */
	hiddenCount: number;
	/** Distinct kinds among the hidden items (for the warning text). */
	hiddenKinds: string[];
}

export function savedInCorpus(
	cartItems: readonly CartItem[],
	indexHas: (kind: string, id: number) => boolean
): SavedScope {
	const shownByKind = new Map<string, Set<number>>();
	let hiddenCount = 0;
	const hiddenKinds = new Set<string>();
	for (const it of cartItems) {
		if (indexHas(it.kind, it.id)) {
			let s = shownByKind.get(it.kind);
			if (!s) {
				s = new Set<number>();
				shownByKind.set(it.kind, s);
			}
			s.add(it.id);
		} else {
			hiddenCount++;
			hiddenKinds.add(it.kind);
		}
	}
	return { shownByKind, hiddenCount, hiddenKinds: [...hiddenKinds] };
}

/** The displayable saved ids for one kind (empty set when none). */
export function shownIds(scope: SavedScope, kind: string): Set<number> {
	return scope.shownByKind.get(kind) ?? new Set<number>();
}
