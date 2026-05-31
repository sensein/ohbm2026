/**
 * Bugfix (neuroscape 3D hang): the 3D scatter must render a BOUNDED,
 * mode-independent point budget. atlas-root feeds its ~50k decimated
 * landing backdrop and stays responsive; /neuroscape/ fed the full
 * representative-tier union (`scatterBackdropForMap`, tiers 0..N-1),
 * so its scatter3d got far more points → main-thread hang on
 * zoom/rotate. `decimate3dBackdrop` makes both modes pass through the
 * same cap so the 3D scene is equivalent.
 */

import { describe, expect, it } from 'vitest';
import { decimate3dBackdrop, MAX_3D_BACKDROP_POINTS } from '$lib/lod3d';

type P = { lod_level?: number; tag: number };

function withLod(n: number): P[] {
	// Spread points across more LOD tiers than fit in the budget so the
	// coarse-tier preference is exercised.
	const tiers = 8;
	return Array.from({ length: n }, (_, i) => ({ lod_level: i % tiers, tag: i }));
}

describe('decimate3dBackdrop', () => {
	it('returns the input unchanged when within budget', () => {
		const pts = withLod(1000);
		expect(decimate3dBackdrop(pts)).toBe(pts);
	});

	it('caps to the budget when over it', () => {
		const pts = withLod(MAX_3D_BACKDROP_POINTS + 200_000);
		const out = decimate3dBackdrop(pts);
		expect(out.length).toBeLessThanOrEqual(MAX_3D_BACKDROP_POINTS);
		expect(out.length).toBeGreaterThan(0);
	});

	it('prefers coarse (lower) lod_level tiers and drops the finest', () => {
		// Tier 0 = 10 points (coarsest), tiers 1..: many. Budget tiny here
		// is simulated by using a big over-budget input where the finest
		// tier must be dropped.
		const pts: P[] = [];
		for (let t = 0; t < 8; t++)
			for (let i = 0; i < (MAX_3D_BACKDROP_POINTS); i++) pts.push({ lod_level: t, tag: t });
		const out = decimate3dBackdrop(pts);
		expect(out.length).toBeLessThanOrEqual(MAX_3D_BACKDROP_POINTS);
		const maxKept = Math.max(...out.map((p) => p.lod_level ?? 0));
		const maxAvail = 7;
		// The finest tier (7) must not survive a budget << total.
		expect(maxKept).toBeLessThan(maxAvail);
	});

	it('falls back to a bounded uniform stride when no lod_level present', () => {
		const pts = Array.from({ length: MAX_3D_BACKDROP_POINTS * 3 }, (_, i) => ({ tag: i }));
		const out = decimate3dBackdrop(pts as { lod_level?: number; tag: number }[]);
		expect(out.length).toBeLessThanOrEqual(MAX_3D_BACKDROP_POINTS);
		expect(out.length).toBeGreaterThan(0);
	});
});
