/**
 * Spec 019 follow-up — polygon/box lasso selection over the FULL corpus.
 *
 * With the progressive-LOD backdrop the scatter only RENDERS a sample, so
 * Plotly's rendered-points selection would miss un-displayed abstracts in
 * the lassoed region. Instead we capture the lasso polygon geometry and
 * test it against the full coordinate set — these are the pure helpers
 * that do that.
 */

import { describe, expect, it } from 'vitest';
import {
	pointInPolygon,
	isInGeometry,
	selectIdsInGeometry,
	type LassoGeometry
} from '$lib/geo/lasso_select';

describe('pointInPolygon (ray casting)', () => {
	// Unit square (0,0)-(1,1).
	const sx = [0, 1, 1, 0];
	const sy = [0, 0, 1, 1];

	it('returns true for a point clearly inside', () => {
		expect(pointInPolygon(0.5, 0.5, sx, sy)).toBe(true);
	});

	it('returns false for a point clearly outside', () => {
		expect(pointInPolygon(1.5, 0.5, sx, sy)).toBe(false);
		expect(pointInPolygon(-0.2, 0.5, sx, sy)).toBe(false);
		expect(pointInPolygon(0.5, 2, sx, sy)).toBe(false);
	});

	it('handles a concave polygon (point in the notch is outside)', () => {
		// Right-pointing chevron ">": vertices (0,0)→(2,1)→(0,2)→(1,1).
		// The inner vertex (1,1) carves a notch on the LEFT.
		const px = [0, 2, 0, 1];
		const py = [0, 1, 2, 1];
		// (1.5, 1) sits inside the right body; (0.2, 1) sits in the notch.
		expect(pointInPolygon(1.5, 1, px, py)).toBe(true);
		expect(pointInPolygon(0.2, 1, px, py)).toBe(false);
	});
});

describe('isInGeometry', () => {
	it('box geometry is an inclusive axis-aligned test, order-independent', () => {
		const g: LassoGeometry = { kind: 'box', x: [1, -1], y: [2, 0] };
		expect(isInGeometry(0, 1, g)).toBe(true);
		expect(isInGeometry(-1, 0, g)).toBe(true); // corner
		expect(isInGeometry(2, 1, g)).toBe(false); // x out of range
	});

	it('lasso geometry delegates to pointInPolygon', () => {
		const g: LassoGeometry = { kind: 'lasso', x: [0, 1, 1, 0], y: [0, 0, 1, 1] };
		expect(isInGeometry(0.5, 0.5, g)).toBe(true);
		expect(isInGeometry(5, 5, g)).toBe(false);
	});
});

describe('selectIdsInGeometry', () => {
	type P = { id: number; umap_2d?: [number, number] };
	const pts: P[] = [
		{ id: 10, umap_2d: [0.5, 0.5] }, // inside
		{ id: 11, umap_2d: [5, 5] }, // outside
		{ id: 12, umap_2d: [0.1, 0.9] }, // inside
		{ id: 13 } // no coords → skipped
	];
	const square: LassoGeometry = { kind: 'lasso', x: [0, 1, 1, 0], y: [0, 0, 1, 1] };

	it('returns ids of points whose coords fall inside, skipping coordless points', () => {
		const ids = selectIdsInGeometry(
			pts,
			square,
			(p) => p.id,
			(p) => p.umap_2d
		);
		expect(ids.sort()).toEqual([10, 12]);
	});

	it('finds ALL matching points, not a sampled subset (the LOD fix)', () => {
		// 1000 points densely inside the square; a downsample-based lasso
		// would miss most — the polygon test must return every one.
		const dense: P[] = Array.from({ length: 1000 }, (_, i) => ({
			id: i,
			umap_2d: [0.2 + (i % 50) * 0.01, 0.2 + Math.floor(i / 50) * 0.01] as [number, number]
		}));
		const ids = selectIdsInGeometry(
			dense,
			square,
			(p) => p.id,
			(p) => p.umap_2d
		);
		expect(ids.length).toBe(1000);
	});
});
