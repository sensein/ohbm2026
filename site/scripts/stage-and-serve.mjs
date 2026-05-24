// Local gh-pages preview harness for the Stage-9 conference subpath rework.
//
// `pnpm preview` (vite preview) serves the SvelteKit build at the
// `paths.base` URL — i.e. `<host>/ohbm2026/` — and treats `<host>/` as a
// 404. That's fine for in-conference work, but it doesn't let us test the
// root-redirect island that the deploy workflows place at the gh-pages
// publish-source root.
//
// This script reproduces what the deploy workflows do at the file-tree
// level (`site/publish/{index.html, 404.html, ohbm2026/<build>}`), then
// boots a plain static-file server on the same port the Playwright config
// expects. Used by `pnpm preview:gh-pages` and by `playwright.config.ts`'s
// `webServer.command` so the e2e specs see the production-shaped tree.
//
// Zero runtime deps: standard `node:http` + `node:fs/promises`. The
// `http-server` npm package would work too but `npx` slows down spin-up.

import { spawnSync } from 'node:child_process';
import { createServer } from 'node:http';
import { readFile, stat, cp, mkdir, rm } from 'node:fs/promises';
import { existsSync } from 'node:fs';
import { extname, join, normalize, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = fileURLToPath(new URL('.', import.meta.url));
const SITE_ROOT = resolve(HERE, '..');
const BUILD_DIR = join(SITE_ROOT, 'build');
const REDIRECT_DIR = join(SITE_ROOT, 'conference-root-redirect');
const PUBLISH_DIR = join(SITE_ROOT, 'publish');
const PORT = Number(process.env.PORT ?? 4173);
const HOST = process.env.HOST ?? '127.0.0.1';

const MIME = {
	'.html': 'text/html; charset=utf-8',
	'.css': 'text/css; charset=utf-8',
	'.js': 'application/javascript; charset=utf-8',
	'.mjs': 'application/javascript; charset=utf-8',
	'.json': 'application/json; charset=utf-8',
	'.svg': 'image/svg+xml',
	'.png': 'image/png',
	'.jpg': 'image/jpeg',
	'.webp': 'image/webp',
	'.ico': 'image/x-icon',
	'.onnx': 'application/octet-stream',
	'.parquet': 'application/octet-stream',
	'.wasm': 'application/wasm',
	'.woff': 'font/woff',
	'.woff2': 'font/woff2',
	'.ttf': 'font/ttf',
	'.otf': 'font/otf',
	'.txt': 'text/plain; charset=utf-8',
	'.map': 'application/json'
};

async function stage() {
	await rm(PUBLISH_DIR, { recursive: true, force: true });
	await mkdir(join(PUBLISH_DIR, 'ohbm2026'), { recursive: true });
	await cp(BUILD_DIR, join(PUBLISH_DIR, 'ohbm2026'), { recursive: true });
	await cp(join(REDIRECT_DIR, 'index.html'), join(PUBLISH_DIR, 'index.html'));
	await cp(join(REDIRECT_DIR, '404.html'), join(PUBLISH_DIR, '404.html'));
	// Stage a data package so the e2e tests can run against real data
	// without hitting the production Dropbox URL. Stage 10 shipped a
	// single parquet; Stage 15 (spec 015-neuroscape-context FR-022)
	// renamed it `data.parquet → ohbm2026.parquet` so the three
	// sibling deployments at `/`, `/ohbm2026/`, `/neuroscape/` each
	// read a uniquely-named parquet.
	//
	// Three sources, in preference order:
	//   1. `OHBM2026_LOCAL_PARQUET` env var — an absolute path to an
	//      `ohbm2026.parquet` (e.g. the maintainer's local Dropbox sync
	//      at `~/MIT Dropbox/.../ohbm2026/ohbm2026.parquet`). Copied
	//      verbatim to the new canonical filename.
	//   2. `OHBM2026_LOCAL_TARBALL` env var — legacy fallback for the
	//      Stage-6 tarball shape. Kept around so an older bundle still
	//      works for ad-hoc dev. (Will be removed once Stage 11 lands.)
	//   3. `site/static/data/` — re-tarred on the fly (Stage-6 shape).
	//
	// The build must have been done with the per-mode URL env var
	// pointing at the file served here. For Stage 15 the variables
	// split per `SITE_MODE`:
	//   - SITE_MODE=ohbm2026   → VITE_DATA_PACKAGE_URL_OHBM2026   → ohbm2026.parquet
	//   - SITE_MODE=neuroscape → VITE_DATA_PACKAGE_URL_NEUROSCAPE → neuroscape.parquet
	//   - SITE_MODE=atlas-root → VITE_DATA_PACKAGE_URL_ATLAS      → atlas.parquet
	// The legacy `VITE_DATA_PACKAGE_URL` is still honoured by the
	// loader as a one-cycle fallback so a stale build keeps working.
	const localParquet = process.env.OHBM2026_LOCAL_PARQUET;
	if (localParquet && existsSync(localParquet)) {
		await cp(localParquet, join(PUBLISH_DIR, 'ohbm2026.parquet'));
		console.log(`stage-and-serve: data-package = ${localParquet} → ohbm2026.parquet (parquet)`);
		return;
	}
	const tarOut = join(PUBLISH_DIR, 'data-package.tar.gz');
	const localTarball = process.env.OHBM2026_LOCAL_TARBALL;
	if (localTarball && existsSync(localTarball)) {
		await cp(localTarball, tarOut);
		console.log(`stage-and-serve: data-package = ${localTarball} (legacy tarball)`);
		return;
	}
	const dataDir = join(SITE_ROOT, 'static', 'data');
	if (existsSync(dataDir)) {
		const result = spawnSync(
			'tar',
			['-czf', tarOut, '-C', join(SITE_ROOT, 'static'), 'data'],
			{ stdio: 'inherit' }
		);
		if (result.status !== 0) {
			throw new Error('Failed to package site/static/data into tarball');
		}
		console.log(`stage-and-serve: data-package = (built from site/static/data/)`);
	}
}

async function serveFile(res, abs) {
	const data = await readFile(abs);
	const ext = extname(abs);
	res.writeHead(200, { 'Content-Type': MIME[ext] ?? 'application/octet-stream' });
	res.end(data);
}

async function tryServe(res, abs) {
	try {
		const st = await stat(abs);
		if (st.isDirectory()) {
			const idx = join(abs, 'index.html');
			await stat(idx);
			await serveFile(res, idx);
			return true;
		}
		await serveFile(res, abs);
		return true;
	} catch {
		return false;
	}
}

const server = createServer(async (req, res) => {
	try {
		const url = new URL(req.url ?? '/', `http://${HOST}:${PORT}`);
		// Normalise + sandbox so a `..` in the URL can't escape PUBLISH_DIR.
		const cleaned = normalize(url.pathname).replace(/^[/\\]+/, '');
		const candidate = resolve(PUBLISH_DIR, cleaned);
		if (!candidate.startsWith(PUBLISH_DIR)) {
			res.writeHead(403);
			res.end('Forbidden');
			return;
		}
		if (await tryServe(res, candidate)) return;
		// Mirror gh-pages: every unknown path falls back to the root 404.html
		// (gh-pages does NOT walk up the directory tree per request — there
		// is exactly one 404.html for the whole Pages site).
		const fallback = join(PUBLISH_DIR, '404.html');
		const data = await readFile(fallback);
		res.writeHead(404, { 'Content-Type': 'text/html; charset=utf-8' });
		res.end(data);
	} catch (err) {
		res.writeHead(500);
		res.end(String(err));
	}
});

await stage();
server.listen(PORT, HOST, () => {
	console.log(`stage-and-serve: http://${HOST}:${PORT}/`);
});
