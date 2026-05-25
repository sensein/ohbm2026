<script lang="ts">
	import '../app.css';
	// KaTeX stylesheet — required for math spans rendered via
	// `renderMath()` in DetailPanel. Without it math renders as
	// unstyled HTML and column alignment breaks.
	import 'katex/dist/katex.min.css';
	import { onMount } from 'svelte';
	import { base } from '$app/paths';
	import { goto } from '$app/navigation';
	import { page } from '$app/stores';
	import { buildInfoFromEnv, loadManifest, type BuildInfo, type Manifest } from '$lib/shards';
	import BuildInfoFooter from '$lib/components/BuildInfo.svelte';
	import SiteHeader from '$lib/components/SiteHeader.svelte';
	import Tour from '$lib/components/Tour.svelte';
	import CartDrawer from '$lib/components/CartDrawer.svelte';
	import { cartDrawerOpen } from '$lib/stores/cart_ui';
	import { tourStore, tourFlags } from '$lib/stores/tour';
	// SITE_MODE is a build-time constant (Vite substitutes
	// `import.meta.env.VITE_SITE_MODE` at compile time). The unified
	// SiteHeader handles all three builds; mode-specific chrome
	// (tour CTA, atlas-only `main` padding override) branches inside
	// the layout below.
	import { SITE_MODE } from '$lib/site_mode';

	const FEEDBACK_REPO = 'sensein/ohbm2026';

	let manifest: Manifest | null = null;
	const envBuildInfo: BuildInfo | null = buildInfoFromEnv();
	$: dataBuildInfo = manifest?.build_info ?? null;

	/**
	 * Reactive GitHub-issue pre-fill URL. Recomputes on route change so
	 * the body reflects whichever page the user was on when they clicked.
	 * The full build_info block (deploy + data) is templated in so a
	 * maintainer can correlate the report to the exact code revision and
	 * data-package state-keys that were live when the user hit the issue.
	 */
	$: feedbackUrl = (() => {
		const here = $page.url.href;
		const ua = typeof navigator !== 'undefined' ? navigator.userAgent : '';
		const lines: string[] = [
			'<!-- Replace this template with your bug report or feature request. -->',
			'',
			'## What were you doing?',
			'',
			'## What happened?',
			'',
			'## What did you expect?',
			'',
			'---',
			'',
			'## Context (auto-filled; please leave intact)',
			'',
			`- **page**: ${here}`,
			`- **user-agent**: ${ua}`
		];
		if (envBuildInfo) {
			lines.push(
				'',
				'### deploy build_info',
				`- code_revision_short: \`${envBuildInfo.code_revision_short}\``,
				`- code_revision: \`${envBuildInfo.code_revision}\``,
				`- built_at: ${envBuildInfo.built_at}`
			);
		}
		if (dataBuildInfo) {
			lines.push(
				'',
				'### data build_info',
				`- code_revision_short: \`${dataBuildInfo.code_revision_short}\``,
				`- code_revision: \`${dataBuildInfo.code_revision}\``,
				`- corpus_state_key: \`${dataBuildInfo.corpus_state_key}\``,
				`- stage4_rollup_state_key: \`${dataBuildInfo.stage4_rollup_state_key}\``,
				`- built_at: ${dataBuildInfo.built_at}`
			);
		}
		if (!envBuildInfo && !dataBuildInfo) {
			lines.push('', '### build_info', '- (unavailable — page loaded before manifest)');
		}
		const params = new URLSearchParams({
			labels: 'feedback',
			title: '[feedback] ',
			body: lines.join('\n')
		});
		return `https://github.com/${FEEDBACK_REPO}/issues/new?${params.toString()}`;
	})();

	const SPA_REDIRECT_KEY = 'ohbm2026.spa.redirect';

	onMount(async () => {
		// Importing the theme store side-effect-initialises the data-theme
		// attribute + the system-pref watcher.
		await import('$lib/stores/theme');

		// Deep-link restore. When a user direct-loads e.g.
		// `/pr-9/abstract/M-AM-101/`, gh-pages serves the root `404.html`
		// (the hand-written SPA-redirect shim on gh-pages). That shim
		// stashes the original path in BOTH sessionStorage AND a `?spa=…`
		// query param, then redirects to the SPA shell. Query-param wins —
		// sessionStorage is unreliable across cold incognito loads on some
		// browsers, the query param survives any same-origin redirect.
		try {
			let stash: string | null = null;
			const params = new URLSearchParams(window.location.search);
			const fromQuery = params.get('spa');
			if (fromQuery) {
				stash = fromQuery;
				// Strip the param so it doesn't show up in the address bar
				// after goto. replaceState avoids a back-button entry.
				params.delete('spa');
				const cleanedSearch = params.toString();
				const cleanedUrl =
					window.location.pathname +
					(cleanedSearch ? '?' + cleanedSearch : '') +
					window.location.hash;
				window.history.replaceState({}, '', cleanedUrl);
			}
			if (!stash) {
				stash = sessionStorage.getItem(SPA_REDIRECT_KEY);
			}
			sessionStorage.removeItem(SPA_REDIRECT_KEY);
			if (stash && stash.startsWith('/') && !stash.startsWith('//')) {
				// INVARIANT: pass the FULL stash (with base) to `goto`, never
				// the stripped form. SvelteKit's `goto('/foo')` treats a
				// leading slash as ORIGIN-absolute (relative to
				// document.baseURI), NOT base-aware. Stripping the base
				// before calling `goto` would land the navigation outside
				// the SPA's scope — in PR-preview mode that means escaping
				// `/pr-N/ohbm2026/` and loading the gh-pages root redirect
				// (which bounces back to `/ohbm2026/`, losing the deep-link
				// target). The same trap applies in production for any URL
				// under `/ohbm2026/` once spec 009-conference-subpath lands.
				// Do NOT add a `stash.replace(base, '')` step here.
				const currentFull =
					window.location.pathname + window.location.search + window.location.hash;
				if (stash !== currentFull) {
					void goto(stash, { replaceState: true });
				}
			}
		} catch {
			/* sessionStorage / location may be blocked; falling through is fine */
		}

		manifest = await loadManifest();
	});
</script>

<svelte:head>
	{#if SITE_MODE === 'atlas-root'}
		<title>Abstract Atlas — OHBM 2026 in the NeuroScape neuroscience landscape</title>
	{:else if SITE_MODE === 'neuroscape'}
		<title>NeuroScape PubMed Atlas — neuroscience 1999–2023</title>
	{:else}
		<title>OHBM 2026 Atlas (beta)</title>
	{/if}
</svelte:head>

<div class="shell">
	<SiteHeader {feedbackUrl} on:open-cart={() => ($cartDrawerOpen = true)} />

	{#if SITE_MODE === 'ohbm2026' && !$tourFlags.ctaDismissed && !$tourFlags.completedOrSkipped}
		<!-- Tour CTA banner only on /ohbm2026/ for now — atlas-root +
		     neuroscape get their own tour content but skip the CTA
		     banner to avoid pestering visitors on landing pages. -->
		<div class="tour-cta" data-testid="tour-cta">
			<span>
				New here? Take a 60-second tour of the search, map, and saved-list features.
			</span>
			<button
				type="button"
				class="tour-cta-start"
				on:click={() => {
					tourStore.dismissCta();
					tourStore.start();
				}}
				data-testid="tour-cta-start"
			>
				Start tour
			</button>
			<button
				type="button"
				class="tour-cta-skip"
				on:click={() => tourStore.dismissCta()}
				aria-label="Dismiss"
				data-testid="tour-cta-skip"
			>
				×
			</button>
		</div>
	{/if}

	<!-- Atlas-mode `main` only drops the side padding on the HOME route
	     where the UMAP + facets sidebar needs full-bleed width. Detail
	     pages (e.g. /neuroscape/abstract/<pmid>/) keep the normal
	     padding so the article reads with the same breathing room
	     OHBM 2026's permalink page has. -->
	<main
		class:atlas-main={SITE_MODE !== 'ohbm2026' &&
			!$page.url.pathname.includes('/abstract/')}
	>
		<slot />
	</main>

	<Tour />

	<!-- Unifying cart drawer — mounted once for every subsite. The
	     per-mode data lookups (OHBM abstracts + authors / NeuroScape
	     articles) are injected by the corresponding +page.svelte
	     via the slot pattern below… actually for simplicity we just
	     pass empty maps here; the per-site pages mount their own
	     CartDrawer with the right lookups when they have data. The
	     fallback rendering here is id-only ("OHBM 2026 poster 1234"
	     without title) — visible only if the user opens the drawer
	     from a page that hasn't loaded any corpus data yet. -->
	<CartDrawer bind:open={$cartDrawerOpen} />

	<BuildInfoFooter deployBuildInfo={envBuildInfo} {dataBuildInfo} />
</div>

<style>
	/* The shell + tour-CTA + main padding live here; header chrome
	   (title, beta tag, Tour/About/Chat/Theme) moved to
	   `$lib/components/SiteHeader.svelte` and is shared by all
	   three sibling builds. */
	.shell {
		min-height: 100vh;
		display: flex;
		flex-direction: column;
		background: var(--bg);
		color: var(--text);
	}
	.tour-cta {
		display: flex;
		align-items: center;
		gap: 0.6rem;
		background: var(--accent-soft-bg);
		color: var(--accent-soft-text, var(--text));
		padding: 0.5rem 1rem;
		margin: 0.5rem clamp(1rem, 2vw, 2rem);
		border: 1px solid var(--accent);
		border-radius: 6px;
		font-size: 0.88rem;
		flex-wrap: wrap;
	}
	.tour-cta > span {
		flex: 1;
		min-width: 0;
	}
	.tour-cta-start {
		all: unset;
		cursor: pointer;
		background: var(--accent);
		color: var(--accent-text, white);
		padding: 0.3rem 0.7rem;
		border-radius: 4px;
		font-size: 0.82rem;
	}
	.tour-cta-skip {
		all: unset;
		cursor: pointer;
		color: var(--text-muted);
		font-size: 1.2rem;
		padding: 0 0.4rem;
	}
	.tour-cta-skip:hover {
		color: var(--text);
	}
	main {
		flex: 1;
		padding: 0.5rem clamp(1rem, 2vw, 2rem) 1rem;
		width: 100%;
		box-sizing: border-box;
	}
	/* atlas-root + neuroscape pages own the full viewport width
	   (UMAP atlas + facet sidebar grid); skip the side padding the
	   OHBM home + detail pages depend on. */
	main.atlas-main {
		padding: 0;
	}
</style>
