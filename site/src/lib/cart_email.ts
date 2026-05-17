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

/** Render one cart line: "M-AM-101  Title — Lead Author  <permalink>". */
function renderItemLine(record: AbstractRecord, leadAuthor: string, siteUrl: string): string {
	const id = record.poster_id || `id ${record.abstract_id}`;
	const url = record.poster_id ? permalinkFor(siteUrl, record.poster_id) : '';
	const author = leadAuthor ? ` — ${leadAuthor}` : '';
	return `• ${id}  ${record.title}${author}\n  ${url}`;
}

/**
 * Build the mailto: URL for a cart of abstracts.
 *
 * @param items   Records the user has saved (already filtered to those in cart).
 * @param leadAuthorByAbstractId  Maps abstract_id → first-author display string.
 *                                Empty string if unknown. Caller computes this.
 * @param options Site URL + optional subject override.
 */
export function buildMailtoLink(
	items: AbstractRecord[],
	leadAuthorByAbstractId: Map<number, string>,
	options: CartEmailOptions
): string {
	const subject = options.subject ?? 'My OHBM 2026 abstract list';
	const subjectPart = 'mailto:?subject=' + encodeURIComponent(subject) + '&body=';
	const truncationSuffix = TRUNCATION_NOTICE + trimSlash(options.siteUrl) + ' )';
	const header = `Saved abstracts from the OHBM 2026 Atlas (${items.length} item${items.length === 1 ? '' : 's'}):\n\n`;
	const lines: string[] = [];
	let included = 0;
	let truncated = false;
	for (const rec of items) {
		const lead = leadAuthorByAbstractId.get(rec.abstract_id) ?? '';
		const line = renderItemLine(rec, lead, options.siteUrl);
		const tentativeBody = header + [...lines, line].join('\n\n') + truncationSuffix;
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
	return subjectPart + encodeURIComponent(body);
}

/** Plain-text rendering (for the clipboard fallback). */
export function buildPlainTextList(
	items: AbstractRecord[],
	leadAuthorByAbstractId: Map<number, string>,
	siteUrl: string
): string {
	const header = `Saved abstracts from the OHBM 2026 Atlas (${items.length} item${items.length === 1 ? '' : 's'}):\n\n`;
	return (
		header +
		items
			.map((rec) =>
				renderItemLine(rec, leadAuthorByAbstractId.get(rec.abstract_id) ?? '', siteUrl)
			)
			.join('\n\n')
	);
}
