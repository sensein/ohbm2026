/**
 * Stage 15 (spec 015-neuroscape-context, FR-008 + R-006): build-time
 * site-mode discriminator.
 *
 * The same SvelteKit project is built three times by the deploy
 * workflow (`.github/workflows/deploy-ui.yml`), once per deployment
 * subpath:
 *
 *   | SITE_MODE      | publish dir                  | base path     |
 *   |----------------|------------------------------|---------------|
 *   | 'ohbm2026'     | site/publish/ohbm2026/       | /ohbm2026     |
 *   | 'neuroscape'   | site/publish/neuroscape/     | /neuroscape   |
 *   | 'atlas-root'   | site/publish/                | '' (bare root)|
 *
 * Vite injects `VITE_SITE_MODE` into the bundle at build time. The
 * value is a compile-time constant — `{#if SITE_MODE === '…'}`
 * branches in `+page.svelte` / `+layout.svelte` are tree-shaken so
 * each per-mode bundle only ships its mode's code. `'ohbm2026'` is
 * the historical default so any caller / preview / local dev that
 * does NOT set `VITE_SITE_MODE` continues to build the existing
 * site byte-identical (FR-022, SC-008).
 */

export type SiteMode = 'ohbm2026' | 'neuroscape' | 'atlas-root';

const RAW = import.meta.env.VITE_SITE_MODE as string | undefined;

function resolve(raw: string | undefined): SiteMode {
	if (raw === 'neuroscape' || raw === 'atlas-root' || raw === 'ohbm2026') return raw;
	return 'ohbm2026';
}

export const SITE_MODE: SiteMode = resolve(RAW);
