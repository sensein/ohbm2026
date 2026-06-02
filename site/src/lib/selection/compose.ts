/**
 * Spec 021 — intersection composition for the unified selection workflow.
 *
 * The visible/highlighted set on every sibling site is the intersection of all
 * ACTIVE filters: `search ∩ lasso ∩ facets ∩ cart-only`. Each filter supplies
 * an id-set, or `null` when it is inactive (no constraint). This is the single
 * shared primitive so the OHBM home, atlas-root, and neuroscape all compose
 * filters identically (replacing the old OHBM cart-dominant override).
 *
 * Contract: specs/021-atlas-cart-lasso/contracts/selection-composition.md.
 * Pure + side-effect-free so it is unit-tested without mounting Plotly.
 */

/**
 * Intersect every non-null part. Returns:
 *  - `null` when EVERY part is null (no filter active → "show the full corpus").
 *  - the intersection Set otherwise. An active part of size 0 is honored and
 *    yields an empty Set (an explicit empty state downstream), NOT "inactive".
 *
 * The input sets are never mutated.
 */
export function compose(parts: Array<Set<number> | null>): Set<number> | null {
	const active = parts.filter((p): p is Set<number> => p !== null);
	if (active.length === 0) return null;

	// Start from the smallest active set so the membership scan is cheapest.
	let smallest = active[0];
	for (const s of active) if (s.size < smallest.size) smallest = s;

	const result = new Set<number>(smallest);
	for (const part of active) {
		if (part === smallest) continue;
		for (const id of result) {
			if (!part.has(id)) result.delete(id);
		}
	}
	return result;
}
