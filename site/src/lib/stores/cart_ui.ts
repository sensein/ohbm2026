import { writable } from 'svelte/store';

/**
 * Shared open/closed flag for the unifying cart drawer.
 *
 * The drawer itself is mounted once by `+layout.svelte` so every
 * subsite (atlas-root, ohbm2026, neuroscape) has it available. The
 * 🛒 button in `SiteHeader` toggles this store on click; the OHBM
 * home page's legacy cart-toggle in its top-row controls also writes
 * to it (replacing the per-page `cartOpen` local-state pattern).
 */
export const cartDrawerOpen = writable(false);

/**
 * Per-corpus title lookups that pages publish into so the cart
 * drawer can render rich rows for items whose source corpus is
 * loaded into the current page. Empty maps are the fallback —
 * rows render with id + a "OHBM 2026 poster ####" / "PubMed
 * <pmid>" placeholder title and the sibling permalink still
 * works.
 *
 * +page.svelte's data-load success branch writes the relevant
 * map. Cross-site coverage grows naturally as the visitor moves
 * between subsites: after a /neuroscape/ visit, the neuroscape
 * map populates; after an /ohbm2026/ visit, the OHBM map
 * populates; atlas-root visits populate both (its parquet
 * carries overlay + backdrop rows with titles, just not bodies).
 */
export const ohbmTitleLookup = writable<
	Map<number, { title: string; lead_author?: string }>
>(new Map());

export const neuroscapeTitleLookup = writable<
	Map<number, { title: string; year?: number; cluster_title?: string }>
>(new Map());
