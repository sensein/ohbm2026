<script lang="ts">
	import '../app.css';
	import { onMount } from 'svelte';
	import { base } from '$app/paths';
	import { goto } from '$app/navigation';
	import { buildInfoFromEnv, loadManifest, type BuildInfo, type Manifest } from '$lib/shards';
	import BuildInfoFooter from '$lib/components/BuildInfo.svelte';
	import ThemeToggle from '$lib/components/ThemeToggle.svelte';

	let manifest: Manifest | null = null;
	const envBuildInfo: BuildInfo | null = buildInfoFromEnv();
	$: dataBuildInfo = manifest?.build_info ?? null;

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
				// Strip the SvelteKit base path from the front; goto()
				// expects a route-relative URL.
				const stripped = base && stash.startsWith(base) ? stash.slice(base.length) : stash;
				if (stripped && stripped !== '/' && stripped !== window.location.pathname) {
					void goto(stripped, { replaceState: true });
				}
			}
		} catch {
			/* sessionStorage / location may be blocked; falling through is fine */
		}

		manifest = await loadManifest();
	});
</script>

<svelte:head>
	{#if envBuildInfo}
		<title>OHBM 2026 Atlas · {envBuildInfo.code_revision_short}</title>
	{:else if dataBuildInfo}
		<title>OHBM 2026 Atlas · {dataBuildInfo.code_revision_short}</title>
	{:else}
		<title>OHBM 2026 Atlas</title>
	{/if}
</svelte:head>

<div class="shell">
	<header>
		<div class="header-row">
			<div class="header-text">
				<h1>OHBM 2026 Atlas</h1>
				<p class="subtitle">
					Browse, search, and explore the 2026 accepted abstracts
				</p>
			</div>
			<div class="header-controls">
				<a class="header-link" href={`${base}/about/`} data-testid="header-about-link">
					About
				</a>
				<ThemeToggle />
			</div>
		</div>
	</header>

	<main>
		<slot />
	</main>

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
	main {
		flex: 1;
		padding: 0.5rem clamp(1rem, 2vw, 2rem) 1rem;
		width: 100%;
		box-sizing: border-box;
	}
</style>
