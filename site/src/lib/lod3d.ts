/**
 * Bounded point budget for the 3D scatter backdrop.
 *
 * The 3D `scatter3d` (Plotly/gl3d) keeps the whole backdrop on the GPU and
 * does main-thread work per camera operation, so an unbounded point count
 * makes zoom/rotate hang the page. atlas-root stayed responsive only because
 * its backdrop is the ~50k decimated landing sample; `/neuroscape/` fed the
 * full representative-tier union, so its 3D scene was far heavier.
 *
 * `decimate3dBackdrop` caps BOTH modes to one shared budget so the 3D scene
 * is equivalent regardless of mode. It prefers coarse LOD tiers (lower
 * `lod_level` = a blue-noise cover) so the sample stays spatially
 * representative; with no `lod_level` it falls back to a uniform stride.
 * The 2D path is unaffected (it has its own viewport-windowed LOD detail).
 */

export const MAX_3D_BACKDROP_POINTS = 50_000;

// `lod_level` is attached to backdrop points at runtime (the loader folds the
// `coords` tier onto each article via a cast), so it isn't in the static
// BackdropPoint type. Read it structurally rather than constraining the
// generic on a weak (all-optional) type, which TS rejects at the call site.
function lodOf(p: unknown): number | undefined {
	const lvl = (p as { lod_level?: unknown }).lod_level;
	return typeof lvl === 'number' ? lvl : undefined;
}

export function decimate3dBackdrop<T>(points: T[]): T[] {
	const n = points.length;
	if (n <= MAX_3D_BACKDROP_POINTS) return points;

	// Count points per LOD tier; note whether any tier metadata exists.
	const counts = new Map<number, number>();
	let anyLod = false;
	for (const p of points) {
		const l = lodOf(p);
		if (l !== undefined) anyLod = true;
		const lvl = l ?? Number.POSITIVE_INFINITY;
		counts.set(lvl, (counts.get(lvl) ?? 0) + 1);
	}

	if (!anyLod) {
		// Uniform stride — bounded and spatially even.
		const stride = Math.ceil(n / MAX_3D_BACKDROP_POINTS);
		const out: T[] = [];
		for (let i = 0; i < n; i += stride) out.push(points[i]);
		return out;
	}

	// Include whole tiers from coarsest (lowest lod_level) up to the budget,
	// then partially fill the first tier that would overflow. Coarse tiers are
	// blue-noise covers, so this yields a representative bounded sample.
	const tiers = [...counts.keys()].sort((a, b) => a - b);
	let remaining = MAX_3D_BACKDROP_POINTS;
	const fullTiers = new Set<number>();
	let partialTier: number | null = null;
	let partialQuota = 0;
	for (const lvl of tiers) {
		const c = counts.get(lvl) as number;
		if (c <= remaining) {
			fullTiers.add(lvl);
			remaining -= c;
		} else {
			partialTier = lvl;
			partialQuota = remaining;
			break;
		}
	}

	const out: T[] = [];
	let takenPartial = 0;
	for (const p of points) {
		const lvl = lodOf(p) ?? Number.POSITIVE_INFINITY;
		if (fullTiers.has(lvl)) {
			out.push(p);
		} else if (lvl === partialTier && takenPartial < partialQuota) {
			out.push(p);
			takenPartial++;
		}
	}
	return out;
}
