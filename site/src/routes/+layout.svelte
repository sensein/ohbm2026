<script lang="ts">
	import '../app.css';
	import { onMount } from 'svelte';
	import { base } from '$app/paths';
	import { buildInfoFromEnv, loadManifest, type BuildInfo, type Manifest } from '$lib/shards';
	import BuildInfoFooter from '$lib/components/BuildInfo.svelte';
	import ThemeToggle from '$lib/components/ThemeToggle.svelte';

	let manifest: Manifest | null = null;
	const envBuildInfo: BuildInfo | null = buildInfoFromEnv();
	$: dataBuildInfo = manifest?.build_info ?? null;

	onMount(async () => {
		// Importing the theme store side-effect-initialises the data-theme
		// attribute + the system-pref watcher. Static import is fine in
		// browser-only context; for SSR-safety it just exports the store.
		await import('$lib/stores/theme');
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
