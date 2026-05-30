import { describe, it, expect } from 'vitest';
import {
	densityOpacity,
	backdropOpacity,
	overlayMarkerSize,
	BACKDROP_OPACITY_FLOOR,
	BACKDROP_OPACITY_CAP,
	OVERLAY_SIZE_BASE,
	OVERLAY_SIZE_CAP
} from '$lib/atlas/opacity';

describe('densityOpacity — fewer points ⇒ higher opacity', () => {
	it('is monotonically non-increasing as the point count grows', () => {
		const counts = [100, 327, 1000, 3135, 11670, 40291, 56268, 100000, 461316];
		const ops = counts.map(densityOpacity);
		for (let i = 1; i < ops.length; i++) {
			expect(ops[i]).toBeLessThanOrEqual(ops[i - 1] + 1e-9);
		}
	});

	it('lifts a sparse early-tier sample (hundreds of pts) to the cap', () => {
		// lod0 (327) + lod1 (845) arrive first during progressive load — these
		// MUST be clearly visible, not the old 0.05 speck.
		expect(densityOpacity(327)).toBe(BACKDROP_OPACITY_CAP);
		expect(densityOpacity(845)).toBeGreaterThan(0.7);
	});

	it('keeps the full ~56k LOD sample clearly visible (well above the old 0.05)', () => {
		const op = densityOpacity(56268);
		expect(op).toBeGreaterThan(0.3);
		expect(op).toBeLessThan(0.6);
	});

	it('keeps the whole 461k corpus a faint—but visible—cloud', () => {
		const op = densityOpacity(461316);
		expect(op).toBeGreaterThanOrEqual(BACKDROP_OPACITY_FLOOR);
		expect(op).toBeLessThan(0.3);
	});

	it('never returns below the floor or above the cap', () => {
		expect(densityOpacity(10_000_000)).toBeGreaterThanOrEqual(BACKDROP_OPACITY_FLOOR);
		expect(densityOpacity(1)).toBeLessThanOrEqual(BACKDROP_OPACITY_CAP);
		expect(densityOpacity(0)).toBeLessThanOrEqual(BACKDROP_OPACITY_CAP);
		expect(densityOpacity(-5)).toBeLessThanOrEqual(BACKDROP_OPACITY_CAP);
	});
});

describe('backdropOpacity — deeper zoom ⇒ higher opacity', () => {
	it('equals the density opacity when fully zoomed out (zoomFactor ≤ 1)', () => {
		expect(backdropOpacity(56268, 1)).toBeCloseTo(densityOpacity(56268), 10);
		// zoomFactor below 1 (e.g. scaleanchor padding makes the view wider
		// than the data) is clamped to 1 — never dims below the density base.
		expect(backdropOpacity(56268, 0.5)).toBeCloseTo(densityOpacity(56268), 10);
	});

	it('is monotonically non-decreasing as the zoom factor grows', () => {
		const zooms = [1, 1.5, 2, 4, 6, 9, 16];
		const ops = zooms.map((z) => backdropOpacity(56268, z));
		for (let i = 1; i < ops.length; i++) {
			expect(ops[i]).toBeGreaterThanOrEqual(ops[i - 1] - 1e-9);
		}
	});

	it('drives the dense 56k sample up to the cap under a deep zoom', () => {
		// "the zoomed state is also faint" — a moderate/deep zoom must push the
		// cloud to (near) full opacity.
		expect(backdropOpacity(56268, 4)).toBeGreaterThan(0.6);
		expect(backdropOpacity(56268, 9)).toBe(BACKDROP_OPACITY_CAP);
	});

	it('treats a non-finite zoom factor as "no zoom" (density base), never NaN', () => {
		// Bogus zoom input (∞ / NaN — e.g. a 0-width viewport mid-gesture) must
		// degrade to the unzoomed density opacity, not blow up the marker style.
		const base = densityOpacity(56268);
		expect(backdropOpacity(56268, Number.POSITIVE_INFINITY)).toBeCloseTo(base, 10);
		expect(backdropOpacity(56268, NaN)).toBeCloseTo(base, 10);
		expect(Number.isFinite(backdropOpacity(56268, NaN))).toBe(true);
	});
});

describe('overlayMarkerSize — OHBM points grow with zoom to stay distinct', () => {
	it('is the base size when fully zoomed out', () => {
		expect(overlayMarkerSize(1)).toBe(OVERLAY_SIZE_BASE);
		expect(overlayMarkerSize(0.5)).toBe(OVERLAY_SIZE_BASE);
	});

	it('grows monotonically with zoom, clamped to the cap', () => {
		const zooms = [1, 2, 4, 9, 16, 64];
		const sizes = zooms.map(overlayMarkerSize);
		for (let i = 1; i < sizes.length; i++) {
			expect(sizes[i]).toBeGreaterThanOrEqual(sizes[i - 1] - 1e-9);
		}
		expect(sizes[0]).toBe(OVERLAY_SIZE_BASE);
		expect(sizes.at(-1)).toBe(OVERLAY_SIZE_CAP);
		expect(overlayMarkerSize(4)).toBeGreaterThan(OVERLAY_SIZE_BASE);
	});

	it('degrades a non-finite zoom factor to the base size, never NaN', () => {
		expect(overlayMarkerSize(Number.POSITIVE_INFINITY)).toBeLessThanOrEqual(OVERLAY_SIZE_CAP);
		expect(overlayMarkerSize(NaN)).toBe(OVERLAY_SIZE_BASE);
	});
});
