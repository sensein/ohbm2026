/**
 * Vitest-specific config that overrides vite.config.ts for test mode.
 *
 * The shared vite.config.ts uses `sveltekit()` which pulls in the full
 * preprocess + dev-server pipeline; that pipeline's `preprocessCSS`
 * call fails under jsdom because vitest doesn't run a real vite dev
 * server. For unit tests that mount Svelte components via
 * @testing-library/svelte (spec 019 / T007), swap `sveltekit()` for
 * the standalone `svelte()` plugin with no preprocessors. The `$lib`
 * alias is re-added manually so existing tests keep resolving.
 */
import { svelte } from '@sveltejs/vite-plugin-svelte';
import { defineConfig } from 'vitest/config';
import { resolve } from 'node:path';

export default defineConfig({
	plugins: [svelte({ preprocess: [], compilerOptions: { hmr: false } })],
	resolve: {
		alias: [
			{ find: /^\$lib(.*)$/, replacement: resolve(__dirname, 'src/lib') + '$1' },
			{ find: /^\$app\/paths$/, replacement: resolve(__dirname, 'src/tests/_stubs/app/paths.ts') },
			{ find: /^\$app\/navigation$/, replacement: resolve(__dirname, 'src/tests/_stubs/app/navigation.ts') },
			{ find: /^\$app\/stores$/, replacement: resolve(__dirname, 'src/tests/_stubs/app/stores.ts') },
			{ find: /^\$env\/dynamic\/public$/, replacement: resolve(__dirname, 'src/tests/_stubs/env-public.ts') },
			{ find: /^\$env\/static\/public$/, replacement: resolve(__dirname, 'src/tests/_stubs/env-public.ts') }
		],
		conditions: ['browser', 'svelte']
	},
	test: {
		include: ['src/tests/unit/**/*.{test,spec}.{js,ts}'],
		environment: 'jsdom',
		environmentOptions: { jsdom: { url: 'http://localhost/' } },
		setupFiles: ['./src/tests/setup.ts'],
		globals: false,
		css: false
	}
});
