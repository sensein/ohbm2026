import adapter from '@sveltejs/adapter-static';
import { vitePreprocess } from '@sveltejs/vite-plugin-svelte';

// Stage 9 (spec 009-conference-subpath FR-101): every OHBM 2026 surface
// now lives under `/ohbm2026/`. PR previews override via the env var to
// `/pr-<N>/ohbm2026`; local dev inherits the production default unless
// the caller explicitly sets `BASE_PATH=''` for a no-base smoke test.
const basePath = process.env.BASE_PATH ?? '/ohbm2026';

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
