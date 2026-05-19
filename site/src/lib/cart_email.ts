/**
 * Cart → email helpers (US5 / FR-015).
 *
 * `buildMailtoLink(items, options)` returns a `mailto:` URL whose subject /
 * body are pre-populated with the user's saved abstract list. Bodies are
 * truncated to MAX_BODY_CHARS so the URL stays below the 2000-character
 * limit that some mail clients (Outlook, system handlers on Windows) impose
 * on `mailto:` strings. Truncated bodies carry a "(more items not shown)"
 * marker so the user knows to copy the full list from the cart drawer.
 */

import type { AbstractRecord } from '$lib/shards';

/** Conservative mailto-URL length budget. RFC has no hard ceiling but
 *  Outlook caps around 2083 characters and Mac Mail tolerates ~2000. */
export const MAX_MAILTO_LENGTH = 1900;

const TRUNCATION_NOTICE = '\n\n…(more items not shown — open the full list at ';

export interface CartEmailOptions {
	/** Public site origin + path, used to embed permalinks per item. Trailing slash optional. */
	siteUrl: string;
	/** Optional subject override. Defaults to "My OHBM 2026 abstract list". */
	subject?: string;
}

function trimSlash(s: string): string {
	return s.endsWith('/') ? s.slice(0, -1) : s;
}

function permalinkFor(siteUrl: string, posterId: string): string {
	return `${trimSlash(siteUrl)}/abstract/${encodeURIComponent(posterId)}/`;
}

/**
 * Render one cart item as a four-line block:
 *
 *   1. [M-AM-101] Title goes here, wrapped if it's long
 *      — Lead Author
 *      → Open: https://abstractatlas.brainkb.org/abstract/M-AM-101/
 *
 * The `→ Open: <url>` line uses an arrow prefix + label so the URL reads
 * unambiguously as "click here to view the abstract" inside any email
 * client. Most clients auto-linkify a bare URL on its own line, which is
 * why the URL ends the block.
 */
function renderItemLine(
	record: AbstractRecord,
	leadAuthor: string,
	siteUrl: string,
	index: number
): string {
	// poster_id is the sole identifier; format as zero-padded 4-digit for display
	const id = record.poster_id ? String(record.poster_id).padStart(4, '0') : '';
	const url = record.poster_id ? permalinkFor(siteUrl, id) : '';
	const lines: string[] = [`${index}. [${id}] ${record.title}`];
	if (leadAuthor) lines.push(`   — ${leadAuthor}`);
	if (url) lines.push(`   → Open: ${url}`);
	return lines.join('\n');
}

/**
 * Build the mailto: URL for a cart of abstracts.
 *
 * @param items   Records the user has saved (already filtered to those in cart).
 * @param leadAuthorByPosterId  Maps poster_id → first-author display string.
 *                                Empty string if unknown. Caller computes this.
 * @param options Site URL + optional subject override.
 */
export function buildMailtoLink(
	items: AbstractRecord[],
	leadAuthorByPosterId: Map<number, string>,
	options: CartEmailOptions
): string {
	const subject = options.subject ?? 'My OHBM 2026 abstract list';
	const subjectPart = 'mailto:?subject=' + encodeURIComponent(subject) + '&body=';
	const siteHome = trimSlash(options.siteUrl);
	const truncationSuffix =
		TRUNCATION_NOTICE + siteHome + ' )';
	const header =
		`Saved abstracts from the OHBM 2026 Atlas (${items.length} item${items.length === 1 ? '' : 's'}).\n` +
		`Each entry below has an "Open:" link that lands directly on its full-detail page.\n\n`;
	const footer = `\n\n— Browse the rest at ${siteHome}/`;
	const lines: string[] = [];
	let included = 0;
	let truncated = false;
	for (const rec of items) {
		const lead = leadAuthorByPosterId.get(rec.poster_id) ?? '';
		const line = renderItemLine(rec, lead, options.siteUrl, included + 1);
		const tentativeBody = header + [...lines, line].join('\n\n') + truncationSuffix + footer;
		const tentativeUrlLength = subjectPart.length + encodeURIComponent(tentativeBody).length;
		if (tentativeUrlLength > MAX_MAILTO_LENGTH && included > 0) {
			truncated = true;
			break;
		}
		lines.push(line);
		included += 1;
	}
	let body = header + lines.join('\n\n');
	if (truncated) body += truncationSuffix;
	body += footer;
	return subjectPart + encodeURIComponent(body);
}

/** Plain-text rendering (for the clipboard fallback). */
export function buildPlainTextList(
	items: AbstractRecord[],
	leadAuthorByPosterId: Map<number, string>,
	siteUrl: string
): string {
	const siteHome = trimSlash(siteUrl);
	const header =
		`Saved abstracts from the OHBM 2026 Atlas (${items.length} item${items.length === 1 ? '' : 's'}).\n` +
		`Each entry below has an "Open:" link that lands directly on its full-detail page.\n\n`;
	const body = items
		.map((rec, i) =>
			renderItemLine(rec, leadAuthorByPosterId.get(rec.poster_id) ?? '', siteUrl, i + 1)
		)
		.join('\n\n');
	return header + body + `\n\n— Browse the rest at ${siteHome}/`;
}
