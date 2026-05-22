/**
 * Render `$...$` inline math and `\(...\)` math spans in body text
 * via KaTeX. Stage 12.2 adds this so authors' equations render
 * properly in the SvelteKit UI instead of showing the literal
 * dollar-bracketed LaTeX.
 *
 * Returns sanitised HTML safe to drop into `{@html ...}`. Non-math
 * text is HTML-escaped before concatenation; math spans go through
 * KaTeX's `renderToString` with `throwOnError: false` so a malformed
 * span renders as red literal source instead of crashing the page.
 */

import katex from 'katex';

const KATEX_OPTIONS: katex.KatexOptions = {
	throwOnError: false,
	errorColor: 'var(--color-danger, #b94a48)',
	strict: 'ignore',
	output: 'html',
};

/** HTML-escape a non-math chunk so it lands safely inside `{@html}`. */
function escapeHtml(s: string): string {
	return s
		.replace(/&/g, '&amp;')
		.replace(/</g, '&lt;')
		.replace(/>/g, '&gt;')
		.replace(/"/g, '&quot;')
		.replace(/'/g, '&#39;');
}

/**
 * Split `text` into alternating (text, math) chunks. Recognises
 * `$$...$$` display math, `$...$` inline math, and `\(...\)` /
 * `\[...\]` math. Backslash-escaped `\$` is treated as a literal
 * dollar sign and does NOT toggle math mode.
 *
 * Implemented as a single forward scan so we don't double-process
 * a `$` inside `\(...\)` (or vice versa).
 */
type Chunk = { text: string; math: false } | { text: string; math: true; display: boolean };

export function splitMath(text: string): Chunk[] {
	const chunks: Chunk[] = [];
	let cursor = 0;
	let i = 0;
	while (i < text.length) {
		const ch = text[i];
		// Skip escaped `\$`
		if (ch === '\\' && text[i + 1] === '$') {
			i += 2;
			continue;
		}
		// `$$...$$` display math (only if NOT preceded by another `$`)
		if (ch === '$' && text[i + 1] === '$') {
			const end = text.indexOf('$$', i + 2);
			if (end !== -1) {
				if (i > cursor) chunks.push({ text: text.slice(cursor, i), math: false });
				chunks.push({ text: text.slice(i + 2, end), math: true, display: true });
				i = end + 2;
				cursor = i;
				continue;
			}
		}
		// `$...$` inline math — match to the next unescaped `$` on the
		// same line. Single-line scope keeps us from running away when
		// authors mismatch dollars across paragraphs.
		if (ch === '$') {
			let j = i + 1;
			while (j < text.length) {
				if (text[j] === '\n') {
					j = -1;
					break;
				}
				if (text[j] === '\\' && text[j + 1] === '$') {
					j += 2;
					continue;
				}
				if (text[j] === '$') break;
				j++;
			}
			if (j !== -1 && j < text.length && text[j] === '$') {
				if (i > cursor) chunks.push({ text: text.slice(cursor, i), math: false });
				chunks.push({ text: text.slice(i + 1, j), math: true, display: false });
				i = j + 1;
				cursor = i;
				continue;
			}
		}
		// `\(...\)` inline math
		if (ch === '\\' && text[i + 1] === '(') {
			const end = text.indexOf('\\)', i + 2);
			if (end !== -1) {
				if (i > cursor) chunks.push({ text: text.slice(cursor, i), math: false });
				chunks.push({ text: text.slice(i + 2, end), math: true, display: false });
				i = end + 2;
				cursor = i;
				continue;
			}
		}
		// `\[...\]` display math
		if (ch === '\\' && text[i + 1] === '[') {
			const end = text.indexOf('\\]', i + 2);
			if (end !== -1) {
				if (i > cursor) chunks.push({ text: text.slice(cursor, i), math: false });
				chunks.push({ text: text.slice(i + 2, end), math: true, display: true });
				i = end + 2;
				cursor = i;
				continue;
			}
		}
		i++;
	}
	if (cursor < text.length) {
		chunks.push({ text: text.slice(cursor), math: false });
	}
	return chunks;
}

/**
 * Convert a string with possibly-embedded math into rendered HTML.
 * Non-math content is HTML-escaped + newlines preserved as `<br>`.
 * Returns an empty string for null/undefined/empty input.
 */
export function renderMath(text: string | null | undefined): string {
	if (!text) return '';
	const out: string[] = [];
	for (const chunk of splitMath(text)) {
		if (!chunk.math) {
			out.push(escapeHtml(chunk.text));
			continue;
		}
		try {
			out.push(
				katex.renderToString(chunk.text, {
					...KATEX_OPTIONS,
					displayMode: chunk.display,
				})
			);
		} catch {
			// KaTeX shouldn't throw with `throwOnError: false` but
			// belt-and-braces: fall back to the literal source.
			out.push(escapeHtml(chunk.math && chunk.display ? `$$${chunk.text}$$` : `$${chunk.text}$`));
		}
	}
	return out.join('');
}
