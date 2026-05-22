import { describe, expect, it } from 'vitest';
import { renderMath, splitMath } from '$lib/render_math';

describe('splitMath', () => {
	it('passes plain text through unchanged', () => {
		expect(splitMath('hello world')).toEqual([{ text: 'hello world', math: false }]);
	});

	it('splits $...$ inline math', () => {
		const out = splitMath('value $\\alpha=0.05$ holds');
		expect(out).toEqual([
			{ text: 'value ', math: false },
			{ text: '\\alpha=0.05', math: true, display: false },
			{ text: ' holds', math: false }
		]);
	});

	it('splits $$...$$ display math', () => {
		const out = splitMath('eqn: $$a=b$$ done');
		expect(out).toEqual([
			{ text: 'eqn: ', math: false },
			{ text: 'a=b', math: true, display: true },
			{ text: ' done', math: false }
		]);
	});

	it('splits \\(...\\) inline math', () => {
		const out = splitMath('x \\(\\pi\\) y');
		expect(out).toEqual([
			{ text: 'x ', math: false },
			{ text: '\\pi', math: true, display: false },
			{ text: ' y', math: false }
		]);
	});

	it('leaves escaped \\$ intact', () => {
		const out = splitMath('price is \\$5');
		expect(out).toEqual([{ text: 'price is \\$5', math: false }]);
	});

	it('bails on cross-line $...$', () => {
		const out = splitMath('open $ alpha\n no close');
		// The opening `$` doesn't match across newline → treated as text.
		expect(out).toEqual([{ text: 'open $ alpha\n no close', math: false }]);
	});
});

describe('renderMath', () => {
	it('returns empty for nullish input', () => {
		expect(renderMath('')).toBe('');
		expect(renderMath(null)).toBe('');
		expect(renderMath(undefined)).toBe('');
	});

	it('HTML-escapes plain text', () => {
		const out = renderMath('5 < x & y > 3');
		expect(out).toContain('&lt;');
		expect(out).toContain('&amp;');
		expect(out).toContain('&gt;');
	});

	it('renders $...$ via KaTeX', () => {
		const out = renderMath('value $\\alpha$ here');
		expect(out).toContain('katex');
		expect(out).toContain('value ');
		expect(out).toContain(' here');
	});

	it('renders \\(...\\) via KaTeX', () => {
		const out = renderMath('beta \\(\\beta\\) end');
		expect(out).toContain('katex');
	});

	it('renders bad math without crashing', () => {
		// `\foo` is undefined; throwOnError: false → red literal.
		const out = renderMath('$\\foo{x}$');
		expect(typeof out).toBe('string');
		expect(out.length).toBeGreaterThan(0);
	});

	it('preserves Unicode super/subscript from data layer', () => {
		// ¹ ² ³ pass through unchanged (already converted server-side
		// from `<sup>`).
		const out = renderMath('reference¹,² shows');
		expect(out).toContain('¹,²');
	});
});
