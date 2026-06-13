/**
 * Stage 24 (specs/024-fix-ios-safari-load) — runtime device-capability gate.
 *
 * Contract: contracts/mobile-rendering.md (AC-4) + data-model.md `DeviceCapability`.
 * The gate must be RUNTIME-discovered (Constitution VII / CA-007), conservative
 * on mobile, and must NOT regress desktop (incl. desktop Safari, which — like
 * iOS — does not expose `navigator.deviceMemory`).
 */

import { describe, expect, it } from 'vitest';
import { computeCapability } from '$lib/device/capability';

const DESKTOP = {
	webglAvailable: true,
	deviceMemoryGb: 8,
	viewportWidth: 1440,
	prefersReducedMotion: false
};

const IPHONE = {
	webglAvailable: true,
	deviceMemoryGb: null, // iOS Safari never exposes this
	viewportWidth: 390,
	prefersReducedMotion: false
};

describe('computeCapability', () => {
	it('gives a desktop the full experience: 3D + auto-rotate + eager warm', () => {
		const cap = computeCapability(DESKTOP);
		expect(cap.webglContextBudget).toBe('normal');
		expect(cap.isSmallViewport).toBe(false);
		expect(cap.allow3dByDefault).toBe(true);
		expect(cap.allowAutoRotate).toBe(true);
		expect(cap.eagerSemanticWarm).toBe(true);
	});

	it('gates a small-viewport iPhone (deviceMemory absent) to the conservative branch', () => {
		const cap = computeCapability(IPHONE);
		expect(cap.webglContextBudget).toBe('low');
		expect(cap.isSmallViewport).toBe(true);
		expect(cap.allow3dByDefault).toBe(false); // 2D-only by default
		expect(cap.allowAutoRotate).toBe(false); // no auto-rotate on mobile
		expect(cap.eagerSemanticWarm).toBe(false); // lazy warm on mobile
	});

	it('does NOT downgrade a large viewport just because deviceMemory is absent (desktop Safari)', () => {
		const cap = computeCapability({ ...DESKTOP, deviceMemoryGb: null });
		expect(cap.webglContextBudget).toBe('normal');
		expect(cap.allow3dByDefault).toBe(true);
		expect(cap.eagerSemanticWarm).toBe(true);
	});

	it('downgrades a large viewport when memory is reported AND low', () => {
		const cap = computeCapability({ ...DESKTOP, deviceMemoryGb: 2 });
		expect(cap.webglContextBudget).toBe('low');
		expect(cap.allow3dByDefault).toBe(false);
	});

	it('suppresses auto-rotate when the user prefers reduced motion, even on desktop', () => {
		const cap = computeCapability({ ...DESKTOP, prefersReducedMotion: true });
		expect(cap.allow3dByDefault).toBe(true); // 3D still mounts
		expect(cap.allowAutoRotate).toBe(false); // but does not spin
	});

	it('never marks 3D allowed when WebGL is unavailable', () => {
		const cap = computeCapability({ ...DESKTOP, webglAvailable: false });
		expect(cap.webglAvailable).toBe(false);
		expect(cap.allow3dByDefault).toBe(false);
		expect(cap.allowAutoRotate).toBe(false);
	});
});
