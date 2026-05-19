import { defineConfig, devices } from '@playwright/test';

// `PLAYWRIGHT_BASE_URL` is the full URL of the SvelteKit app's home
// (where the conference subpath terminates) — origin + optional
// per-deploy prefix + `/ohbm2026/`. Examples:
//   • local:   `http://127.0.0.1:4173/ohbm2026/`
//   • prod:    `https://abstractatlas.brainkb.org/ohbm2026/`
//   • sandbox: `https://abstractatlas.brainkb.org/sandbox/ohbm2026/`
//   • PR-N:    `https://abstractatlas.brainkb.org/pr-<N>/ohbm2026/`
//
// Specs use relative paths (`./`, `./about/`, `./abstract/<id>/`) so
// the SAME suite resolves to the right deploy without `/ohbm2026/`
// or `/pr-<N>/` hardcoded into the assertions — that was the bug
// that made the PR-preview e2e job silently test production.
const RAW_BASE_URL = process.env.PLAYWRIGHT_BASE_URL ?? 'http://127.0.0.1:4173/ohbm2026/';
const APP_BASE_URL = RAW_BASE_URL.endsWith('/') ? RAW_BASE_URL : `${RAW_BASE_URL}/`;
const IS_REMOTE = !!process.env.PLAYWRIGHT_BASE_URL;

export default defineConfig({
	testDir: 'src/tests/e2e',
	fullyParallel: true,
	forbidOnly: !!process.env.CI,
	retries: process.env.CI ? 2 : 0,
	workers: process.env.CI ? 2 : undefined,
	reporter: 'list',
	// Only spin up the local preview server when we're targeting it.
	// When PLAYWRIGHT_BASE_URL is set (CI against a deployed URL), no
	// local server is needed.
	...(IS_REMOTE
		? {}
		: {
				webServer: {
					// Stage 9 (spec 009-conference-subpath): use the gh-pages-shaped
					// preview harness so the e2e specs see the SAME tree the deploy
					// workflow uploads — root redirect island at `/`, SvelteKit build
					// under `/ohbm2026/`. Callers must run `pnpm build` before this;
					// the harness skips rebuilding to preserve baked VITE_BUILD_SHA
					// env vars.
					command: 'pnpm preview:gh-pages',
					port: 4173,
					reuseExistingServer: !process.env.CI
				}
			}),
	use: {
		// baseURL ends at the conference home — `page.goto('./')` lands
		// on the SvelteKit app's home and `page.goto('./about/')` lands
		// on the About route. Anything that needs to address the origin
		// root (the redirect island) MUST construct its own context with
		// an explicit `baseURL`, since a leading-slash path is origin-
		// absolute and replaces baseURL's path component.
		baseURL: APP_BASE_URL,
		trace: 'on-first-retry'
	},
	projects: [
		{
			name: 'chromium',
			use: { ...devices['Desktop Chrome'] }
		},
		{
			name: 'mobile',
			use: {
				...devices['Pixel 5'],
				viewport: { width: 360, height: 640 }
			}
		}
	]
});
