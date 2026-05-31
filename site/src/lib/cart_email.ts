/**
 * Cart → email helpers (US5 / FR-015).
 *
 * `buildMailtoLink(items, options)` returns a `mailto:` URL whose subject /
 * body are pre-populated with the user's saved abstract list. Bodies are
 * truncated to MAX_MAILTO_LENGTH so the URL stays below the 2000-character
 * limit that some mail clients (Outlook, system handlers on Windows) impose
 * on `mailto:` strings.
 *
 * Every body — truncated or not — leads with a "Restore the full cart"
 * URL of the form `<siteUrl>/?cart=0001,0042,...`. The home route reads
 * the `?cart=` query parameter on load and merges those poster_ids into
 * the cart store via `cartStore.addMany()`. That means even when a long
 * cart is truncated in the visible list, the recipient (or sender on a
 * different machine) can click the restore URL and get every saved
 * abstract back.
 */

import type { AbstractRecord } from '$lib/shards';

/**
 * Stage 15 unifying cart row — kind-tagged so the email + clipboard
 * formatter can produce the right permalink per source. `siteRoot`
 * is the cross-conference deploy root (e.g.
 * `https://abstractatlas.brainkb.org`); `kind` selects the subsite
 * subpath. OHBM rows keep their `lead_author`; PubMed rows surface
 * a year + cluster label instead (authors live behind the runtime
 * NCBI EFetch and aren't cached locally).
 */
export interface UnifiedCartRow {
	kind: 'ohbm2026' | 'neuroscape';
	id: number;
	title: string;
	subline: string; // e.g. "Jane Doe" (OHBM) or "2021 · Memory & aging" (neuroscape)
}

function siblingPermalink(siteRoot: string, kind: 'ohbm2026' | 'neuroscape', id: number): string {
	const root = trimSlash(siteRoot);
	if (kind === 'ohbm2026') {
		return `${root}/ohbm2026/abstract/${String(id).padStart(4, '0')}/`;
	}
	return `${root}/neuroscape/abstract/${id}/`;
}

/**
 * Build the cart-restore deep-link for a mixed-kind cart, GROUPED by kind so
 * the URL stays compact AND extends to any future conference/year. Format:
 *
 *   <root>/?cart=ohbm2026:42,101+neuroscape:123,456
 *
 * — each kind appears ONCE, followed by its comma-separated ids; groups are
 * joined with `+`. This mirrors the cart store's own `kind:id` key space, so
 * adding a new corpus (e.g. `ohbm2027`) needs no URL-scheme change. The home
 * route's `?cart=` handler parses this back into `cartStore.addManyItems`
 * (and still accepts the legacy bare-number `?cart=0042,0101` = ohbm2026).
 */
export function buildUnifiedCartRestoreUrl(items: UnifiedCartRow[], siteRoot: string): string {
	// A Set per kind so duplicate ids never bloat the URL. The cart store
	// already dedups by `kind:id`, so this is defensive — but it keeps the
	// restore link minimal regardless of the input. Set preserves insertion
	// order, so group + id ordering stays stable.
	const byKind = new Map<string, Set<number>>();
	for (const r of items) {
		if (!Number.isFinite(r.id) || r.id <= 0) continue;
		let ids = byKind.get(r.kind);
		if (!ids) byKind.set(r.kind, (ids = new Set<number>()));
		ids.add(r.id);
	}
	const groups = [...byKind.entries()].map(([kind, ids]) => `${kind}:${[...ids].join(',')}`);
	const base = trimSlash(siteRoot);
	return groups.length ? `${base}/?cart=${groups.join('+')}` : `${base}/`;
}

/** One numbered four-line block for a unified cart row, with a
 *  `[OHBM 2026]` / `[NeuroScape]` kind tag (shared by the email + clipboard
 *  formatters). */
function unifiedBlock(r: UnifiedCartRow, root: string, index: number): string {
	const tag = r.kind === 'ohbm2026' ? 'OHBM 2026' : 'NeuroScape';
	const id = r.kind === 'ohbm2026' ? String(r.id).padStart(4, '0') : `PMID ${r.id}`;
	const url = siblingPermalink(root, r.kind, r.id);
	const lines: string[] = [`${index + 1}. [${tag} · ${id}] ${r.title}`];
	if (r.subline) lines.push(`   — ${r.subline}`);
	lines.push(`   → Open: ${url}`);
	return lines.join('\n');
}

/**
 * Greedy-fit a mailto body: keep as many per-item blocks as fit under
 * `MAX_MAILTO_LENGTH`, trimming from the TAIL with a "+N more" marker rather
 * than dropping the whole list. The header carries the ★ restore link, so even
 * a fully-trimmed body (shown === 0) recovers the entire cart in one click.
 * Returns the chosen body string (caller wraps it in the subject part).
 */
function fitMailtoBody(opts: {
	subjectPart: string;
	header: string;
	intro: string;
	footer: string;
	blocks: string[];
	totalItems: number;
}): string {
	const moreMarker = (n: number) =>
		`\n\n…(${n} more item${n === 1 ? '' : 's'} not shown — open the ★ link above to restore the full cart, or use the "Copy" button for the complete list)`;
	for (let shown = opts.blocks.length; shown >= 0; shown--) {
		const more = opts.totalItems - shown;
		const listPart = shown > 0 ? opts.intro + opts.blocks.slice(0, shown).join('\n\n') : '';
		const body = opts.header + listPart + (more > 0 ? moreMarker(more) : '') + opts.footer;
		if (shown === 0 || (opts.subjectPart + encodeURIComponent(body)).length <= MAX_MAILTO_LENGTH) {
			return body;
		}
	}
	return opts.header + opts.footer; // unreachable — the shown===0 case always returns
}

/**
 * Plain-text rendering for a mixed-kind cart (clipboard). No length budget, so
 * it includes EVERY item; leads with the ★ restore link for one-click rebuild.
 */
export function buildUnifiedPlainTextList(items: UnifiedCartRow[], siteRoot: string): string {
	const root = trimSlash(siteRoot);
	const restoreUrl = buildUnifiedCartRestoreUrl(items, root);
	const n = items.length;
	const header =
		`Saved abstracts from Abstract Atlas (${n} item${n === 1 ? '' : 's'}).\n\n` +
		`★ Open all ${n} item${n === 1 ? '' : 's'} in the Atlas (restores the cart): ${restoreUrl}\n\n` +
		`Each entry below has an "Open:" link that lands directly on its full-detail page.\n\n`;
	const blocks = items.map((r, i) => unifiedBlock(r, root, i));
	return header + blocks.join('\n\n') + `\n\n— Browse the atlas at ${root}/`;
}

/**
 * Mailto: URL for a mixed-kind cart. Leads with the ★ restore link (so the cart
 * is recoverable even when the body is trimmed), then fits as many per-item
 * blocks as the URL budget allows (tail-trimmed with a "+N more" marker).
 */
export function buildUnifiedMailtoLink(items: UnifiedCartRow[], siteRoot: string): string {
	const subject = 'My Abstract Atlas saved list';
	const subjectPart = 'mailto:?subject=' + encodeURIComponent(subject) + '&body=';
	const root = trimSlash(siteRoot);
	const restoreUrl = buildUnifiedCartRestoreUrl(items, root);
	const n = items.length;
	const header =
		`Saved abstracts from Abstract Atlas (${n} item${n === 1 ? '' : 's'}).\n\n` +
		`★ Open all ${n} item${n === 1 ? '' : 's'} in the Atlas (restores the cart): ${restoreUrl}\n\n`;
	const intro = `Each entry below has an "Open:" link that lands directly on its full-detail page.\n\n`;
	const footer = `\n\n— Browse the atlas at ${root}/`;
	const blocks = items.slice(0, MAX_EMAIL_ITEMS).map((r, i) => unifiedBlock(r, root, i));
	const body = fitMailtoBody({ subjectPart, header, intro, footer, blocks, totalItems: n });
	return subjectPart + encodeURIComponent(body);
}

/** Item-based cap for the email body. Beyond this many items the
 * body switches to "first N items + truncation marker"; the
 * restore-URL at the top still lets the recipient open all of them
 * via the Atlas.
 */
export const MAX_EMAIL_ITEMS = 100;

/** Safe mailto-URL length budget — Gmail web refuses to open
 * mailto: hrefs much over 8 KB, Outlook caps at 2 KB. We aim well
 * below the Gmail cap so the affordance works for both. When the
 * full body would exceed this, the builder falls through to a
 * compact form (no per-item list — just the restore URL + a copy
 * hint).
 */
export const MAX_MAILTO_LENGTH = 6000;

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
 * Build a deep-link URL that hydrates the home page's cart with the
 * supplied poster_ids. Format: `<siteUrl>/?cart=0001,0042,0123`.
 * Poster ids are zero-padded for human readability; the home route's
 * cart-hydrate handler accepts both padded and bare numeric forms.
 *
 * The URL fits the comma-separated list inline; for 3,333 posters the
 * worst case is ~5 chars × 3333 ≈ 16,650 chars which exceeds typical
 * mailto budgets, but for human-sized carts (tens to low hundreds) it
 * fits comfortably. Callers SHOULD include this URL above the
 * per-item list so the user can recover even when the visible list
 * gets truncated.
 */
export function buildCartRestoreUrl(siteUrl: string, posterIds: number[]): string {
	const padded = posterIds
		.filter((id) => Number.isFinite(id) && id > 0)
		.map((id) => String(id).padStart(4, '0'))
		.join(',');
	const base = trimSlash(siteUrl);
	return padded ? `${base}/?cart=${padded}` : `${base}/`;
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
	const restoreUrl = buildCartRestoreUrl(
		options.siteUrl,
		items.map((r) => r.poster_id)
	);
	const header =
		`Saved abstracts from the OHBM 2026 Atlas (${items.length} item${items.length === 1 ? '' : 's'}).\n\n` +
		`★ Open all ${items.length} item${items.length === 1 ? '' : 's'} in the Atlas (restores the cart): ${restoreUrl}\n\n`;
	const footer = `\n\n— Browse the rest at ${siteHome}/`;

	// Try full body first (up to MAX_EMAIL_ITEMS items). If the
	// resulting URL would exceed Gmail's tolerance, drop the per-item
	// list and emit a COMPACT body — restore URL + a "use Copy" hint.
	// For VERY large carts where even the restore URL pushes the
	// URL past the budget, the restore URL goes in the body anyway
	// but the user is warned it may not open in some mail clients.
	const visibleCount = Math.min(items.length, MAX_EMAIL_ITEMS);
	const allItemsFit = items.length <= MAX_EMAIL_ITEMS;
	const lines = items
		.slice(0, visibleCount)
		.map((rec, i) =>
			renderItemLine(
				rec,
				leadAuthorByPosterId.get(rec.poster_id) ?? '',
				options.siteUrl,
				i + 1
			)
		);
	const truncationSuffix = !allItemsFit
		? `\n\n…(${items.length - visibleCount} more items not shown above; click the ★ link at the top to load the FULL list back into your cart.)`
		: '';
	const fullBody =
		header +
		`Each entry below has an "Open:" link that lands directly on its full-detail page.\n\n` +
		lines.join('\n\n') +
		truncationSuffix +
		footer;
	const fullUrl = subjectPart + encodeURIComponent(fullBody);
	if (fullUrl.length <= MAX_MAILTO_LENGTH) {
		return fullUrl;
	}

	// Compact: header (with restore URL) + Copy hint, no per-item list.
	const compactBody =
		header +
		`(This cart is too large to fit the full list in an email. The ` +
		`★ link above will open every saved abstract in the Atlas. ` +
		`Alternatively, use the "Copy" button on the cart drawer to copy ` +
		`every item as plain text — the clipboard has no length limit.)\n\n` +
		footer;
	return subjectPart + encodeURIComponent(compactBody);
}

/** Plain-text rendering (for the clipboard fallback). Includes
 * EVERY saved item — the clipboard path has no length budget so the
 * email truncation doesn't apply here.
 */
export function buildPlainTextList(
	items: AbstractRecord[],
	leadAuthorByPosterId: Map<number, string>,
	siteUrl: string
): string {
	const siteHome = trimSlash(siteUrl);
	const restoreUrl = buildCartRestoreUrl(
		siteUrl,
		items.map((r) => r.poster_id)
	);
	const header =
		`Saved abstracts from the OHBM 2026 Atlas (${items.length} item${items.length === 1 ? '' : 's'}).\n\n` +
		`★ Open all ${items.length} item${items.length === 1 ? '' : 's'} in the Atlas (restores the cart): ${restoreUrl}\n\n` +
		`Each entry below has an "Open:" link that lands directly on its full-detail page.\n\n`;
	const body = items
		.map((rec, i) =>
			renderItemLine(rec, leadAuthorByPosterId.get(rec.poster_id) ?? '', siteUrl, i + 1)
		)
		.join('\n\n');
	return header + body + `\n\n— Browse the rest at ${siteHome}/`;
}
