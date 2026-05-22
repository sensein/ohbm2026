/**
 * Stage 12 US1b — permalink-page section-state helpers.
 *
 * Pure functions extracted out of `DetailPanel.svelte` so they're
 * unit-testable without mounting the full component (which would
 * require `@testing-library/svelte` — a new dep this stage avoids).
 *
 * The permalink page (`/abstract/<poster_id>/`) starts every
 * verbatim left-column section in a 3-line CSS `line-clamp` preview.
 * Sections whose full text is short enough to fit in 3 lines don't
 * render a "Show more" toggle (see `isClampable`). A column-scoped
 * master toggle expands every clampable section at once + relabels
 * to "Collapse all" once everything is open.
 */

/** Per-section keys for the verbatim left column in permalink mode. */
export const PERMALINK_SECTION_KEYS = [
	'introduction',
	'methods',
	'results',
	'conclusion',
	'acknowledgments'
] as const;

export type PermalinkSectionKey = (typeof PERMALINK_SECTION_KEYS)[number];

/**
 * Brief-preview cutoff. Section text whose length (after trim) is
 * less than this MUST NOT render a toggle button — it fits in 3
 * lines at the permalink page's column width without truncation.
 *
 * Heuristic per `research.md § R2`; empirically ~95% accurate vs a
 * `scrollHeight` measurement on the fixture corpus.
 */
export const CLAMP_TEXT_THRESHOLD = 280;

/** True when the section's full text would clamp (i.e. show a toggle). */
export function isClampable(text: string | undefined | null): boolean {
	return (text ?? '').trim().length >= CLAMP_TEXT_THRESHOLD;
}

/**
 * Aggregate master-toggle state across a set of sections.
 *
 * Returns the label the master button should show:
 * - `"Show all"` when at least one clampable section is still in
 *   its 3-line preview (i.e. NOT every clampable section is
 *   expanded).
 * - `"Collapse all"` when every clampable section is expanded.
 *
 * Sections that aren't clampable (text too short) don't count
 * toward the aggregate — the master toggle is only interested in
 * sections that have something to clamp.
 */
export function masterToggleLabel(
	clampableExpanded: ReadonlyMap<string, boolean>
): 'Show all' | 'Collapse all' {
	const states = Array.from(clampableExpanded.values());
	if (states.length === 0) return 'Show all';
	return states.every(Boolean) ? 'Collapse all' : 'Show all';
}

/**
 * Build the `expanded` map after the master toggle is clicked.
 *
 * - When currently `"Show all"` → flip all clampable sections to
 *   expanded (`true`).
 * - When currently `"Collapse all"` → flip all clampable sections
 *   back to clamped (`false`).
 */
export function nextStateAfterMasterToggle(
	clampableExpanded: ReadonlyMap<string, boolean>
): Map<string, boolean> {
	const label = masterToggleLabel(clampableExpanded);
	const target = label === 'Show all'; // currently shows "Show all" → expand
	const next = new Map<string, boolean>();
	for (const key of clampableExpanded.keys()) {
		next.set(key, target);
	}
	return next;
}
