/**
 * Spec 021 (US3 / FR-009a) — selection contrast survives zoom.
 *
 * The 2D lasso/search highlight washed out when zoomed in because the
 * unselected-point opacity was tied to the base backdrop opacity, which climbs
 * toward the CAP as you zoom. `unselectedOpacity()` caps the unselected value
 * below the selected opacity (1.0) when a selection is active, preserving a
 * contrast gap at every zoom level; with no selection it equals the base.
 */

import { describe, expect, it } from 'vitest';
import {
	backdropOpacity,
	unselectedOpacity,
	SELECTION_UNSELECTED_MAX,
	BACKDROP_OPACITY_CAP
} from '$lib/atlas/opacity';

const SELECTED_OPACITY = 1.0;

describe('unselectedOpacity() — selection contrast gap', () => {
	it('no selection active ⇒ unselected equals the base (unchanged behaviour)', () => {
		for (const base of [0.12, 0.3, 0.5, 0.7, 0.9]) {
			expect(unselectedOpacity(base, false)).toBe(base);
		}
	});

	it('selection active ⇒ unselected is capped below the selected opacity at every zoom', () => {
		// Sweep the full density × zoom range the renderer can produce.
		for (const count of [200, 5_000, 56_000, 461_000]) {
			for (const zoom of [1, 2, 4, 8, 16, 64]) {
				const base = backdropOpacity(count, zoom);
				const unsel = unselectedOpacity(base, true);
				expect(unsel).toBeLessThanOrEqual(SELECTION_UNSELECTED_MAX);
				expect(unsel).toBeLessThan(SELECTED_OPACITY);
				// gap is meaningful (selected pops clearly above unselected)
				expect(SELECTED_OPACITY - unsel).toBeGreaterThanOrEqual(
					SELECTED_OPACITY - SELECTION_UNSELECTED_MAX
				);
			}
		}
	});

	it('cap only lowers, never raises, the base opacity', () => {
		// A faint base (below the cap) is left untouched even when active.
		expect(unselectedOpacity(0.1, true)).toBe(0.1);
		// A base above the ceiling is pulled down to it.
		expect(unselectedOpacity(0.4, true)).toBe(SELECTION_UNSELECTED_MAX);
		expect(unselectedOpacity(BACKDROP_OPACITY_CAP, true)).toBe(SELECTION_UNSELECTED_MAX);
	});
});
