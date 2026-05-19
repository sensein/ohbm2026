import { defineConfig, devices } from '@playwright/test';

// `PLAYWRIGHT_BASE_URL` lets CI point the suite at a deployed URL
// (e.g. `https://abstractatlas.brainkb.org/pr-20/` or the production
// origin) so it tests the real bundle the user sees, not a local
// `pnpm preview`. When unset, the local harness runs as before.
const REMOTE_BASE_URL = process.env.PLAYWRIGHT_BASE_URL;

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
	...(REMOTE_BASE_URL
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
		// `page.goto('/')` hits the root-redirect island, which bounces to
		// `/ohbm2026/`. Specs that need a deeper route MUST spell out the
		// conference subpath (`/ohbm2026/about/`) — leading `/` is origin-
		// absolute and replaces any baseURL path.
		baseURL: REMOTE_BASE_URL ?? 'http://127.0.0.1:4173',
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
