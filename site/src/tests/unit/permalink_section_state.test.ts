/**
 * T008 — Stage 12 US1b unit test for the brief-preview helpers.
 *
 * We deliberately test the pure helpers in `$lib/permalink_section_state`
 * rather than mounting the full `DetailPanel.svelte` component
 * (mounting would need `@testing-library/svelte`, a new dep this
 * stage is explicitly avoiding). The full DOM behaviour is covered
 * by the Playwright e2e in `e2e/permalink_show_more.spec.ts`.
 */
import { describe, expect, it } from 'vitest';
import {
	CLAMP_TEXT_THRESHOLD,
	PERMALINK_SECTION_KEYS,
	isClampable,
	masterToggleLabel,
	nextStateAfterMasterToggle
} from '$lib/permalink_section_state';

describe('isClampable', () => {
	it('returns false for null / undefined / empty', () => {
		expect(isClampable(undefined)).toBe(false);
		expect(isClampable(null)).toBe(false);
		expect(isClampable('')).toBe(false);
	});

	it('returns false for whitespace-only text', () => {
		expect(isClampable('   \n  \t  ')).toBe(false);
	});

	it('returns false when trimmed length is below the threshold', () => {
		expect(isClampable('x'.repeat(CLAMP_TEXT_THRESHOLD - 1))).toBe(false);
	});

	it('returns true exactly at the threshold', () => {
		expect(isClampable('x'.repeat(CLAMP_TEXT_THRESHOLD))).toBe(true);
	});

	it('returns true for long text', () => {
		expect(isClampable('x'.repeat(CLAMP_TEXT_THRESHOLD * 4))).toBe(true);
	});

	it('uses trimmed length, not raw length', () => {
		const text = '   ' + 'x'.repeat(CLAMP_TEXT_THRESHOLD - 1) + '   ';
		// Raw length is CLAMP_TEXT_THRESHOLD + 5; trimmed is < threshold.
		expect(isClampable(text)).toBe(false);
	});
});

describe('PERMALINK_SECTION_KEYS', () => {
	it('lists the 5 left-column verbatim sections in display order', () => {
		expect(Array.from(PERMALINK_SECTION_KEYS)).toEqual([
			'introduction',
			'methods',
			'results',
			'conclusion',
			'acknowledgments'
		]);
	});
});

describe('masterToggleLabel', () => {
	it('returns "Show all" for an empty map', () => {
		expect(masterToggleLabel(new Map())).toBe('Show all');
	});

	it('returns "Show all" when every section is clamped', () => {
		const map = new Map([
			['introduction', false],
			['methods', false],
			['results', false]
		]);
		expect(masterToggleLabel(map)).toBe('Show all');
	});

	it('returns "Show all" when some sections are clamped + some expanded', () => {
		const map = new Map([
			['introduction', true],
			['methods', false],
			['results', true]
		]);
		expect(masterToggleLabel(map)).toBe('Show all');
	});

	it('returns "Collapse all" when EVERY section is expanded', () => {
		const map = new Map([
			['introduction', true],
			['methods', true],
			['results', true]
		]);
		expect(masterToggleLabel(map)).toBe('Collapse all');
	});
});

describe('nextStateAfterMasterToggle', () => {
	it('expands every clampable key when label is "Show all"', () => {
		const start = new Map([
			['introduction', false],
			['methods', false],
			['results', false]
		]);
		const next = nextStateAfterMasterToggle(start);
		expect(Array.from(next.values()).every((v) => v === true)).toBe(true);
	});

	it('collapses every clampable key when label is "Collapse all"', () => {
		const start = new Map([
			['introduction', true],
			['methods', true],
			['results', true]
		]);
		const next = nextStateAfterMasterToggle(start);
		expect(Array.from(next.values()).every((v) => v === false)).toBe(true);
	});

	it('expands the remaining clamped sections when mixed', () => {
		// Mixed → label is "Show all" → next state expands everything.
		const start = new Map([
			['introduction', true],
			['methods', false]
		]);
		const next = nextStateAfterMasterToggle(start);
		expect(next.get('introduction')).toBe(true);
		expect(next.get('methods')).toBe(true);
	});

	it('preserves the set of keys', () => {
		const start = new Map([
			['introduction', false],
			['results', false]
		]);
		const next = nextStateAfterMasterToggle(start);
		expect(Array.from(next.keys()).sort()).toEqual(['introduction', 'results']);
	});
});
