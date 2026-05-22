import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig } from 'vite';

export default defineConfig({
	plugins: [sveltekit()],
	// vitest reads the same config; the `test` key is a vitest extension.
	// @ts-expect-error vite's defineConfig type doesn't know about vitest.
	test: {
		include: ['src/tests/unit/**/*.{test,spec}.{js,ts}'],
		environment: 'jsdom',
		environmentOptions: {
			jsdom: {
				url: 'http://localhost/'
			}
		},
		setupFiles: ['./src/tests/setup.ts'],
		globals: false
	}
});
