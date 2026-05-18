import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
	testDir: 'src/tests/e2e',
	fullyParallel: true,
	forbidOnly: !!process.env.CI,
	retries: process.env.CI ? 2 : 0,
	workers: process.env.CI ? 1 : undefined,
	reporter: 'list',
	webServer: {
		// Stage 9 (spec 009-conference-subpath): use the gh-pages-shaped
		// preview harness so the e2e specs see the SAME tree the deploy
		// workflow uploads — root redirect island at `/`, SvelteKit build
		// under `/ohbm2026/`. `pnpm preview` (vite preview) on its own
		// serves only the SvelteKit build under `/ohbm2026/` and would
		// 404 the root-redirect e2e tests. Callers must run `pnpm build`
		// before this; the harness skips rebuilding to preserve baked
		// VITE_BUILD_SHA env vars.
		command: 'pnpm preview:gh-pages',
		port: 4173,
		reuseExistingServer: !process.env.CI
	},
	use: {
		// baseURL stays root-bound. `page.goto('/')` resolves to
		// `http://127.0.0.1:4173/` and hits the static root-redirect
		// island, which bounces to `/ohbm2026/` (Stage 9 / FR-105). Specs
		// that need to land on a specific deeper route (`/about/`,
		// `/abstract/<id>/`) MUST spell it out with the conference
		// subpath: `page.goto('/ohbm2026/about/')`. The URL() constructor
		// treats a leading `/` as origin-absolute (replacing any baseURL
		// path), so widening baseURL to include `/ohbm2026` doesn't help
		// here and silently breaks legacy `goto('/about/')` calls.
		baseURL: 'http://127.0.0.1:4173',
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
