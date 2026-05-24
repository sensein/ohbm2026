import adapter from '@sveltejs/adapter-static';
import { vitePreprocess } from '@sveltejs/vite-plugin-svelte';

// Stage 9 (spec 009-conference-subpath FR-101): every OHBM 2026 surface
// lives under `/ohbm2026/`. PR previews override via the env var to
// `/pr-<N>/ohbm2026`; local dev inherits the production default unless
// the caller explicitly sets `BASE_PATH=''` for a no-base smoke test.
//
// Stage 15 (spec 015-neuroscape-context, FR-008 + T048): the same
// SvelteKit project is now built three times by the deploy workflow,
// one per deployment. `VITE_SITE_MODE` selects the bundle's per-
// mode behaviour (Vite substitutes the constant at compile time;
// read at runtime via `$lib/site_mode`); `BASE_PATH` controls the
// `kit.paths.base` setting. Both env vars share the SAME canonical
// name so operators set one variable per mode:
//
//   | VITE_SITE_MODE | BASE_PATH default | publish dir              |
//   |----------------|-------------------|--------------------------|
//   | 'ohbm2026'     | '/ohbm2026'       | site/publish/ohbm2026/   |
//   | 'neuroscape'   | '/neuroscape'     | site/publish/neuroscape/ |
//   | 'atlas-root'   | ''                | site/publish/            |
//
// Operators / CI workflows can override BASE_PATH explicitly (e.g.
// PR previews use `/pr-<N>/<subpath>`). When BASE_PATH is set
// explicitly, it wins over the VITE_SITE_MODE-derived default.
const SITE_MODE = process.env.VITE_SITE_MODE ?? process.env.SITE_MODE ?? 'ohbm2026';

function defaultBasePathForMode(mode) {
	if (mode === 'atlas-root') return '';
	if (mode === 'neuroscape') return '/neuroscape';
	return '/ohbm2026';
}

const basePath = process.env.BASE_PATH ?? defaultBasePathForMode(SITE_MODE);

const config = {
	preprocess: vitePreprocess(),
	kit: {
		adapter: adapter({
			pages: 'build',
			assets: 'build',
			fallback: '404.html',
			precompress: false,
			strict: true
		}),
		paths: {
			base: basePath
		}
	}
};

export default config;
