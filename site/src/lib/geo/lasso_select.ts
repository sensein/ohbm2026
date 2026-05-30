/**
 * Polygon / box lasso selection over the FULL coordinate set.
 *
 * Spec 019 follow-up. The progressive-LOD backdrop only RENDERS a
 * blue-noise sample, so Plotly's rendered-points selection
 * (`plotly_selected`'s `points` array) would miss un-displayed abstracts
 * inside the lassoed region. Instead the panel captures the lasso polygon
 * geometry (`lassoPoints` for freeform, `range` for box select) and these
 * pure helpers test it against the full in-memory coordinates — so the
 * lasso finds every abstract in the region, not just the sample drawn.
 */

export type LassoGeometry =
	| { kind: 'lasso'; x: number[]; y: number[] }
	| { kind: 'box'; x: [number, number]; y: [number, number] };

/**
 * Ray-casting point-in-polygon. `xs`/`ys` are the polygon vertices in
 * order (open or closed ring — the edge from last→first is implied).
 * Handles convex and concave polygons.
 */
export function pointInPolygon(px: number, py: number, xs: number[], ys: number[]): boolean {
	const n = xs.length;
	if (n < 3) return false;
	let inside = false;
	for (let i = 0, j = n - 1; i < n; j = i++) {
		const xi = xs[i];
		const yi = ys[i];
		const xj = xs[j];
		const yj = ys[j];
		const intersects =
			yi > py !== yj > py && px < ((xj - xi) * (py - yi)) / (yj - yi) + xi;
		if (intersects) inside = !inside;
	}
	return inside;
}

/** Axis-aligned bounding box `[minX, minY, maxX, maxY]` of a geometry —
 *  used as an O(1) reject pre-filter before the O(V) ray cast. */
export function geometryBounds(g: LassoGeometry): [number, number, number, number] {
	if (g.kind === 'box') {
		return [
			Math.min(g.x[0], g.x[1]),
			Math.min(g.y[0], g.y[1]),
			Math.max(g.x[0], g.x[1]),
			Math.max(g.y[0], g.y[1])
		];
	}
	let minX = Infinity;
	let minY = Infinity;
	let maxX = -Infinity;
	let maxY = -Infinity;
	for (let i = 0; i < g.x.length; i++) {
		const x = g.x[i];
		const y = g.y[i];
		if (x < minX) minX = x;
		if (x > maxX) maxX = x;
		if (y < minY) minY = y;
		if (y > maxY) maxY = y;
	}
	return [minX, minY, maxX, maxY];
}

/** Test a point against a lasso polygon or an axis-aligned box. */
export function isInGeometry(px: number, py: number, g: LassoGeometry): boolean {
	if (g.kind === 'box') {
		const x0 = Math.min(g.x[0], g.x[1]);
		const x1 = Math.max(g.x[0], g.x[1]);
		const y0 = Math.min(g.y[0], g.y[1]);
		const y1 = Math.max(g.y[0], g.y[1]);
		return px >= x0 && px <= x1 && py >= y0 && py <= y1;
	}
	return pointInPolygon(px, py, g.x, g.y);
}

/**
 * Return the ids of every point whose 2D coordinate falls inside the
 * geometry. Points whose `getXY` returns undefined (no coords) are
 * skipped. O(points × polygon-vertices) — a few ms even at 461k points
 * with a typical lasso, so it runs fine on the main thread.
 */
export function selectIdsInGeometry<T>(
	points: readonly T[],
	g: LassoGeometry,
	getId: (p: T) => number,
	getXY: (p: T) => [number, number] | undefined
): number[] {
	// O(1) bounding-box reject first: a lasso usually covers a small part
	// of the view, so the bbox test discards the vast majority of points
	// before the O(V) ray cast — keeps the 461k-point scan off the main
	// thread's critical path. For a box geometry the bbox test IS the
	// full test, so the ray cast below is skipped entirely.
	const [minX, minY, maxX, maxY] = geometryBounds(g);
	const isBox = g.kind === 'box';
	const out: number[] = [];
	for (const p of points) {
		const xy = getXY(p);
		if (!xy) continue;
		const x = xy[0];
		const y = xy[1];
		if (x < minX || x > maxX || y < minY || y > maxY) continue;
		if (isBox || isInGeometry(x, y, g)) out.push(getId(p));
	}
	return out;
}

/**
 * Normalise a Plotly `plotly_selected` event into a `LassoGeometry`.
 * Plotly reports a freeform lasso as `lassoPoints.{x,y}` and a box/rect
 * select as `range.{x,y}` (both in data coordinates). Returns `null` when
 * neither is present (e.g. the spurious empty event Plotly fires after a
 * relayout) so the caller can ignore it.
 */
export function geometryFromPlotlySelection(ev: unknown): LassoGeometry | null {
	const e = ev as
		| {
				lassoPoints?: { x?: number[]; y?: number[] };
				range?: { x?: [number, number]; y?: [number, number] };
		  }
		| null
		| undefined;
	if (!e) return null;
	const lp = e.lassoPoints;
	if (lp && Array.isArray(lp.x) && Array.isArray(lp.y) && lp.x.length >= 3) {
		return { kind: 'lasso', x: lp.x, y: lp.y };
	}
	const r = e.range;
	if (r && Array.isArray(r.x) && Array.isArray(r.y) && r.x.length === 2 && r.y.length === 2) {
		return { kind: 'box', x: r.x as [number, number], y: r.y as [number, number] };
	}
	return null;
}
