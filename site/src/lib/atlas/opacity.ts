/**
 * Spec 019 follow-up — density- + zoom-aware backdrop opacity for the
 * atlas-root / neuroscape UMAP scatter.
 *
 * Why this exists: the backdrop trace used a fixed 0.05 marker opacity tuned
 * for the full ~461k-point corpus. But the scatter never renders 461k points —
 * it renders the quadtree-LOD sample (lod0..lod4 ≈ 56k once all tiers load,
 * and only a few hundred during the first tiers' progressive arrival), plus a
 * viewport-windowed "rest tier" detail trace when zoomed. At 0.05, a
 * few-hundred-to-56k-point sample is nearly invisible — the reported "faint at
 * every zoom level" regression.
 *
 * The fix: per-point opacity is a function of how many points are actually on
 * screen. Fewer points (sparse LOD sample, or a tight zoom window) → higher
 * opacity; the dense full sample → lower opacity so cluster cores don't
 * saturate. Then a gentle multiplicative zoom boost lifts opacity further as
 * the user zooms in (fewer points per pixel), so the cloud stays readable at
 * every zoom depth.
 *
 * Pure + side-effect-free so the curve is unit-tested independently of Plotly.
 * Constants are deliberately exported + grouped here as the single tuning
 * surface (visual review drives them, not magic numbers scattered in the
 * renderer).
 */

/** Numerator of the density term. Larger ⇒ brighter everywhere. */
export const BACKDROP_OPACITY_K = 40;
/** Density falloff exponent on the point count. ~0.42 gives a gentle 1/√n-ish
 *  curve: hundreds of points → cap, ~56k → ~0.4, ~461k → ~0.17. */
export const BACKDROP_OPACITY_EXP = 0.42;
/** Never dim below this — even the full corpus must read as a faint cloud. */
export const BACKDROP_OPACITY_FLOOR = 0.12;
/** Never exceed this — points must read as a cloud, not a solid fill. */
export const BACKDROP_OPACITY_CAP = 0.9;
/** Zoom-boost exponent. effective = density · zoomFactor^this. 0.5 (√zoom) is
 *  a gentle lift that reaches the cap around an 8× zoom. */
export const BACKDROP_ZOOM_EXP = 0.5;

function clampOpacity(x: number): number {
	// NaN can't be ordered by min/max — fall back to the floor. ±Infinity DO
	// order correctly (Infinity → CAP, -Infinity → FLOOR), so let them flow.
	if (Number.isNaN(x)) return BACKDROP_OPACITY_FLOOR;
	return Math.min(BACKDROP_OPACITY_CAP, Math.max(BACKDROP_OPACITY_FLOOR, x));
}

/**
 * Per-point opacity for `renderedCount` points shown at the full (unzoomed)
 * extent. Monotonically decreasing in the count, clamped to
 * [FLOOR, CAP].
 */
export function densityOpacity(renderedCount: number): number {
	const n = Math.max(1, Math.floor(renderedCount) || 1);
	return clampOpacity(BACKDROP_OPACITY_K / Math.pow(n, BACKDROP_OPACITY_EXP));
}

/**
 * Per-point backdrop opacity for `renderedCount` points at a given
 * `zoomFactor` (= fullExtentSpan / visibleSpan, so 1 when fully zoomed out and
 * larger as the user zooms in). Combines the density floor (so a sparse sample
 * is visible even fully zoomed out) with a gentle zoom boost (so a tight
 * window of few points approaches the cap). Clamped to [FLOOR, CAP].
 */
export function backdropOpacity(renderedCount: number, zoomFactor: number): number {
	const z = Math.max(1, Number.isFinite(zoomFactor) ? zoomFactor : 1);
	return clampOpacity(densityOpacity(renderedCount) * Math.pow(z, BACKDROP_ZOOM_EXP));
}

/**
 * Spec 021 (US3) — selection contrast.
 *
 * When a lasso/search selection is active, the SELECTED points render at
 * opacity 1.0 while UNSELECTED points must stay visibly dimmer so the
 * highlight survives zoom-in. The bug being fixed: `applyAtlasZoomOpacity`
 * tied `unselected.marker.opacity` to the base backdrop opacity, which
 * `backdropOpacity` raises toward the CAP (0.9) as you zoom in — so the
 * unselected cloud climbs to nearly match the selected points and the
 * selection washes out. Capping the unselected opacity below the selected
 * opacity preserves a contrast gap at every zoom level.
 *
 * With NO selection active, the unselected opacity stays equal to the base
 * (today's behaviour) so an un-lassoed cloud still reads at every zoom.
 */
/** Ceiling on unselected-point opacity while a selection is active. Selected
 *  points are 1.0, so this guarantees a strong contrast gap so the selection
 *  pops at every zoom level. Kept low (the surrounding cloud fades back to a
 *  faint context layer, like a focus/dim highlight) — 0.5 was too gentle to
 *  read against a dense, same-coloured cloud (spec 021 US3 feedback). */
export const SELECTION_UNSELECTED_MAX = 0.15;

/**
 * Unselected-point opacity given the current base (density+zoom) opacity and
 * whether a selection is active. Active ⇒ capped below the selected opacity
 * (1.0); inactive ⇒ the base unchanged. Monotonic + clamped by `base`.
 */
export function unselectedOpacity(base: number, selectionActive: boolean): number {
	if (!selectionActive) return base;
	return Math.min(base, SELECTION_UNSELECTED_MAX);
}

/** OHBM overlay marker size at full zoom-out (the size that reads clearly
 *  against the fully-zoomed-out backdrop). */
export const OVERLAY_SIZE_BASE = 5;
/** Upper bound so the overlay markers never balloon into blobs. */
export const OVERLAY_SIZE_CAP = 14;
/** Zoom-growth exponent for the overlay markers. */
export const OVERLAY_SIZE_ZOOM_EXP = 0.4;

/**
 * OHBM overlay marker size for a given zoom factor (≥1). The backdrop opacity
 * rises as you zoom in (the whole point of the density+zoom model), which
 * otherwise lets the dense NeuroScape cloud swallow the conference points. The
 * overlay markers grow with zoom to stay distinct — visible at full view AND
 * when zoomed in. Monotonic non-decreasing, clamped to [BASE, CAP].
 */
export function overlayMarkerSize(zoomFactor: number): number {
	const z = Math.max(1, Number.isFinite(zoomFactor) ? zoomFactor : 1);
	const s = OVERLAY_SIZE_BASE * Math.pow(z, OVERLAY_SIZE_ZOOM_EXP);
	return Math.min(OVERLAY_SIZE_CAP, Math.max(OVERLAY_SIZE_BASE, s));
}
