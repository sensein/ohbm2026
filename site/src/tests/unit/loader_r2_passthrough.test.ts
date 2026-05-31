/**
 * Stage 20 (spec 020-cloudflare-r2-migration, FR-005 / T010) — the
 * runtime loader must treat an R2 (non-Dropbox) data-package URL as
 * opaque: `normaliseDropboxUrl` only rewrites Dropbox hosts, so a
 * Cloudflare R2 URL must pass through `getDataPackageUrl()` byte-for-byte.
 *
 * This locks the "no site code change needed for R2" guarantee — a
 * future edit that starts mangling non-Dropbox URLs would fail here.
 *
 * `getDataPackageUrl` is the exported entry; it calls the module-private
 * `normaliseDropboxUrl`. The default SITE_MODE ('ohbm2026', resolved
 * when VITE_SITE_MODE is unset) routes to VITE_DATA_PACKAGE_URL_OHBM2026.
 */

import { afterEach, describe, expect, it, vi } from 'vitest';

// loader.ts imports hyparquet at module scope; stub it so the import
// resolves without exercising any parquet code (this test only touches
// URL resolution).
vi.mock('hyparquet', () => ({
	parquetReadObjects: vi.fn(),
	asyncBufferFromUrl: vi.fn(),
	parquetMetadataAsync: vi.fn()
}));
vi.mock('hyparquet-compressors', () => ({ compressors: {} }));

describe('loader R2 URL passthrough (FR-005)', () => {
	afterEach(() => {
		vi.resetModules();
		vi.unstubAllEnvs();
	});

	it('returns an R2 https URL unchanged (no Dropbox rewrite)', async () => {
		const r2 =
			'https://aadata.cirrusscience.org/' +
			'9f2b7c1d4e5a6b8c9d0e1f2a3b4c5d6e7f8091a2b3c4d5e6f7081920a1b2c3d4/ohbm2026.parquet';
		vi.stubEnv('VITE_DATA_PACKAGE_URL_OHBM2026', r2);
		const { getDataPackageUrl } = await import('$lib/data_package/loader');
		expect(getDataPackageUrl()).toBe(r2);
	});

	it('still rewrites a Dropbox www URL (control — proves the rewrite is Dropbox-only)', async () => {
		vi.stubEnv(
			'VITE_DATA_PACKAGE_URL_OHBM2026',
			'https://www.dropbox.com/scl/fi/x/ohbm2026.parquet?rlkey=abc&dl=0'
		);
		const { getDataPackageUrl } = await import('$lib/data_package/loader');
		const url = getDataPackageUrl();
		expect(url).toContain('dl.dropboxusercontent.com');
		expect(url).not.toContain('www.dropbox.com');
		expect(url).not.toContain('dl=0');
	});
});
