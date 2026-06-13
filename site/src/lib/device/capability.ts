/**
 * Stage 24 (specs/024-fix-ios-safari-load) — runtime device-capability gate.
 *
 * The `/ohbm2026/` atlas failed to load on iPhone Safari because OHBM mode
 * mounted ~3 simultaneous, auto-rotating WebGL contexts (2D scattergl + 3D
 * scatter3d + HUD) on first paint, which mobile WebKit's tight GL-context cap
 * kills, and the eager ONNX/WASM semantic warm added memory pressure on top.
 *
 * This module decides — AT RUNTIME, from measured signals, never from a
 * UA/iOS-version allow-list (constitution Principle VII / CA-007) — whether a
 * device should get the full desktop experience or a lighter mobile one.
 *
 * `computeCapability` is a pure function over injected inputs so it is fully
 * unit-testable; `detectCapability` reads the real browser globals and
 * delegates to it.
 */

/** Signals the gate is computed from. All discovered at runtime. */
export interface DeviceCapabilityInputs {
	/** A working WebGL context could be created (probe result). */
	webglAvailable: boolean;
	/** `navigator.deviceMemory` in GB, or `null` when the browser does not
	 *  expose it (iOS Safari NEVER does; desktop Safari also does not). */
	deviceMemoryGb: number | null;
	/** `window.innerWidth` (CSS px). */
	viewportWidth: number;
	/** `prefers-reduced-motion: reduce` matches. */
	prefersReducedMotion: boolean;
}

export interface DeviceCapability {
	webglAvailable: boolean;
	/** `'low'` budget → do not mount multiple simultaneous WebGL contexts. */
	webglContextBudget: 'low' | 'normal';
	isSmallViewport: boolean;
	deviceMemoryGb: number | null;
	prefersReducedMotion: boolean;
	/** Mount the 3D scatter pane on first paint (vs. behind an explicit toggle). */
	allow3dByDefault: boolean;
	/** Auto-rotate the 3D scene by default. */
	allowAutoRotate: boolean;
	/** Warm the ONNX/WASM semantic worker eagerly on load (vs. on-demand). */
	eagerSemanticWarm: boolean;
}

/**
 * Phone-class breakpoint. Kept equal to `UmapPanel`'s `mobileBreakpoint`
 * (1024) so the capability gate and the panel's existing stacking breakpoint
 * agree about what "mobile" means.
 */
export const SMALL_VIEWPORT_MAX_PX = 1024;

/** Below this many GB of reported RAM we treat the device as low-budget. */
export const LOW_MEMORY_GB = 4;

/**
 * Pure capability computation.
 *
 * Design note on the "fail safe when deviceMemory is absent" rule: iOS Safari
 * never exposes `navigator.deviceMemory`, but neither does desktop Safari, so a
 * blanket "absent ⇒ low budget" would wrongly strip 3D from desktop Safari and
 * regress FR-005. The viewport is therefore the PRIMARY mobile signal: a small
 * viewport is always low-budget regardless of memory, and a large viewport with
 * unknown memory stays normal. Memory only ever DOWNGRADES a large-viewport
 * device when it is reported AND low. This keeps mobile conservative (the iOS
 * fix) without regressing desktop Safari.
 */
export function computeCapability(inp: DeviceCapabilityInputs): DeviceCapability {
	const isSmallViewport = inp.viewportWidth < SMALL_VIEWPORT_MAX_PX;
	const knownLowMemory = inp.deviceMemoryGb !== null && inp.deviceMemoryGb < LOW_MEMORY_GB;

	const webglContextBudget: 'low' | 'normal' = isSmallViewport || knownLowMemory ? 'low' : 'normal';

	const normalBudget = webglContextBudget === 'normal';

	const allow3dByDefault = inp.webglAvailable && normalBudget && !isSmallViewport;
	const allowAutoRotate = allow3dByDefault && !inp.prefersReducedMotion;
	const eagerSemanticWarm = normalBudget && !isSmallViewport;

	return {
		webglAvailable: inp.webglAvailable,
		webglContextBudget,
		isSmallViewport,
		deviceMemoryGb: inp.deviceMemoryGb,
		prefersReducedMotion: inp.prefersReducedMotion,
		allow3dByDefault,
		allowAutoRotate,
		eagerSemanticWarm
	};
}

/** Probe for a usable WebGL context, releasing it immediately so we don't
 *  consume one of the browser's scarce origin-wide context slots. Mirrors the
 *  `detectWebGL` helper already in `UmapPanel.svelte`. */
function probeWebGL(): boolean {
	if (typeof document === 'undefined') return true;
	try {
		const c = document.createElement('canvas');
		const gl =
			c.getContext('webgl2') || c.getContext('webgl') || c.getContext('experimental-webgl');
		if (!gl) return false;
		const lose = (gl as WebGLRenderingContext).getExtension?.('WEBGL_lose_context');
		lose?.loseContext?.();
		return true;
	} catch {
		return false;
	}
}

/**
 * Read the real browser globals and compute the capability. On the server /
 * during prerender (no `window`) we assume a capable desktop so SSR output is
 * unchanged; the real gate runs again on the client at mount.
 */
export function detectCapability(): DeviceCapability {
	if (typeof window === 'undefined') {
		return computeCapability({
			webglAvailable: true,
			deviceMemoryGb: null,
			viewportWidth: 1280,
			prefersReducedMotion: false
		});
	}
	// Guard `navigator` independently of `window`: some test/SSR setups define
	// `window` but not `navigator` (partial global mocks). Absent → treat as
	// unknown memory, which the conservative gate handles safely.
	const dm =
		typeof navigator !== 'undefined'
			? (navigator as unknown as { deviceMemory?: unknown }).deviceMemory
			: undefined;
	const deviceMemoryGb = typeof dm === 'number' ? dm : null;
	const prefersReducedMotion =
		typeof window.matchMedia === 'function'
			? window.matchMedia('(prefers-reduced-motion: reduce)').matches
			: false;
	return computeCapability({
		webglAvailable: probeWebGL(),
		deviceMemoryGb,
		viewportWidth: window.innerWidth || 1280,
		prefersReducedMotion
	});
}
