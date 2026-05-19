<script lang="ts">
	import '../app.css';
	import { onMount } from 'svelte';
	import { base } from '$app/paths';
	import { goto } from '$app/navigation';
	import { page } from '$app/stores';
	import { buildInfoFromEnv, loadManifest, type BuildInfo, type Manifest } from '$lib/shards';
	import BuildInfoFooter from '$lib/components/BuildInfo.svelte';
	import ThemeToggle from '$lib/components/ThemeToggle.svelte';
	import Tour from '$lib/components/Tour.svelte';
	import { tourStore, tourFlags } from '$lib/stores/tour';

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
	<title>OHBM 2026 Atlas (beta)</title>
</svelte:head>

<div class="shell">
	<header>
		<div class="header-row">
			<div class="header-text">
				<h1>OHBM 2026 Atlas <span class="beta-tag">beta</span></h1>
				<p class="subtitle">
					Browse, search, and explore the 2026 accepted abstracts
				</p>
			</div>
			<div class="header-controls">
				<button
					type="button"
					class="header-link header-tour"
					on:click={() => tourStore.start()}
					title="Take the guided tour"
					data-testid="header-tour-button"
				>
					Tour
				</button>
				<a class="header-link" href={`${base}/about/`} data-testid="header-about-link">
					About
				</a>
				<!--
					Feedback icon — opens a pre-filled GitHub issue in a new tab.
					The body templates the current page URL, the deploy SHA, and
					the user-agent so a maintainer has the minimum context to
					reproduce. Repo owner / project link from a const so it's
					trivial to swap.
				-->
				<a
					class="header-feedback"
					target="_blank"
					rel="noopener noreferrer"
					title="Report a bug or request a feature"
					aria-label="Report a bug or request a feature on GitHub"
					data-testid="header-feedback"
					href={feedbackUrl}
				>
					<!-- Lucide-style "message-square-warning" icon — keeps the meaning
						 unambiguous: a comment bubble with an exclamation. -->
					<svg
						width="20"
						height="20"
						viewBox="0 0 24 24"
						fill="none"
						stroke="currentColor"
						stroke-width="2"
						stroke-linecap="round"
						stroke-linejoin="round"
						aria-hidden="true"
					>
						<path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
						<line x1="12" y1="8" x2="12" y2="12" />
						<line x1="12" y1="16" x2="12.01" y2="16" />
					</svg>
				</a>
				<ThemeToggle />
			</div>
		</div>
	</header>

	{#if !$tourFlags.ctaDismissed && !$tourFlags.completedOrSkipped}
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

	<main>
		<slot />
	</main>

	<Tour />

	<BuildInfoFooter deployBuildInfo={envBuildInfo} {dataBuildInfo} />
</div>

<style>
	.shell {
		min-height: 100vh;
		display: flex;
		flex-direction: column;
		background: var(--bg);
		color: var(--text);
	}
	header {
		padding: 1.25rem clamp(1rem, 2vw, 2rem) 0.75rem;
		width: 100%;
		box-sizing: border-box;
		border-bottom: 1px solid var(--border);
	}
	.header-row {
		display: flex;
		justify-content: space-between;
		align-items: flex-start;
		gap: 1rem;
		flex-wrap: wrap;
	}
	.header-text {
		min-width: 0;
	}
	header h1 {
		margin: 0 0 0.25rem;
		font-size: 1.5rem;
		font-weight: 600;
		color: var(--text);
		display: inline-flex;
		align-items: center;
		gap: 0.5rem;
	}
	.beta-tag {
		font-size: 0.6rem;
		font-weight: 700;
		text-transform: uppercase;
		letter-spacing: 0.08em;
		color: var(--accent-text, white);
		background: var(--accent);
		padding: 0.1rem 0.4rem;
		border-radius: 4px;
		vertical-align: middle;
	}
	.subtitle {
		margin: 0;
		color: var(--text-muted);
		font-size: 0.9rem;
	}
	.header-controls {
		display: flex;
		align-items: center;
		gap: 0.6rem;
	}
	.header-link {
		color: var(--accent);
		text-decoration: none;
		font-size: 0.9rem;
		padding: 0.25rem 0.5rem;
		border-radius: 4px;
	}
	.header-link:hover {
		background: var(--accent-soft-bg);
	}
	button.header-link {
		all: unset;
		cursor: pointer;
		color: var(--accent);
		text-decoration: none;
		font-size: 0.9rem;
		padding: 0.25rem 0.5rem;
		border-radius: 4px;
	}
	button.header-link:hover {
		background: var(--accent-soft-bg);
	}
	.header-feedback {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		width: 2rem;
		height: 2rem;
		color: var(--text-muted);
		border-radius: 4px;
		text-decoration: none;
	}
	.header-feedback:hover {
		color: var(--accent);
		background: var(--accent-soft-bg);
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
</style>
