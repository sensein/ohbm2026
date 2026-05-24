<!--
  Stage 15 (spec 015-neuroscape-context, FR-014 + T039):
  bare-root cross-conference atlas landing-page header.

  Brand text on the left + two outbound subsite links in the
  center. Visible only when SITE_MODE === 'atlas-root'; in
  ohbm2026 / neuroscape modes the existing header chrome stays.
-->
<script lang="ts">
	import { base } from '$app/paths';
	import { SITE_MODE } from '$lib/site_mode';
	import ThemeToggle from '$lib/components/ThemeToggle.svelte';
	import { onMount } from 'svelte';

	// Outbound subsite links target SIBLING bases, not children of the
	// current mode's base. Each build's `base` includes the per-mode
	// suffix:
	//   • atlas-root build → base = `/pr-37`        (no suffix)
	//   • ohbm2026 build   → base = `/pr-37/ohbm2026`
	//   • neuroscape build → base = `/pr-37/neuroscape`
	// Constructing `${base}/ohbm2026/` from the neuroscape build would
	// give `/pr-37/neuroscape/ohbm2026/` (a child of neuroscape, 404).
	// Strip the per-mode suffix first to recover the deploy root.
	function rootBase(): string {
		if (SITE_MODE === 'ohbm2026' && base.endsWith('/ohbm2026'))
			return base.slice(0, -'/ohbm2026'.length);
		if (SITE_MODE === 'neuroscape' && base.endsWith('/neuroscape'))
			return base.slice(0, -'/neuroscape'.length);
		return base; // atlas-root: base IS the deploy root.
	}
	const ROOT = rootBase();
	const HOME_HREF = ROOT || '/';
	const OHBM2026_HREF = `${ROOT}/ohbm2026/`;
	const NEUROSCAPE_HREF = `${ROOT}/neuroscape/`;

	// Side-effect-initialise the theme store on first mount so the
	// data-theme attribute reflects the user's chosen / system theme
	// (the OHBM 2026 +layout.svelte does this; the atlas-root +
	// neuroscape paths use this header instead of that layout).
	onMount(async () => {
		await import('$lib/stores/theme');
	});
</script>

<header class="landing-header" data-testid="landing-page-header">
	<a class="brand" href={HOME_HREF}>abstractatlas</a>
	<nav class="nav-links" aria-label="Sibling subsites">
		<!-- rel="external" tells SvelteKit's prerenderer + link-
		     interceptor that these point at a SIBLING SvelteKit
		     deployment (a separately-built bundle under /ohbm2026/
		     and /neuroscape/), NOT an in-app route. Without it the
		     atlas-root prerender step would fail because no
		     /ohbm2026/ route exists inside this bundle.

		     T071 — surface every sibling EXCEPT the one we're on.
		     atlas-root shows both subsite links; ohbm2026 shows root
		     + neuroscape; neuroscape shows root + ohbm2026. -->
		{#if SITE_MODE !== 'atlas-root'}
			<a class="nav-link" href={HOME_HREF} rel="external" data-testid="nav-root"
				>Browse the cross-conference atlas <span class="arrow">→</span></a
			>
		{/if}
		{#if SITE_MODE !== 'ohbm2026'}
			<a class="nav-link" href={OHBM2026_HREF} rel="external" data-testid="nav-ohbm2026"
				>Browse OHBM 2026 abstracts <span class="arrow">→</span></a
			>
		{/if}
		{#if SITE_MODE !== 'neuroscape'}
			<a class="nav-link" href={NEUROSCAPE_HREF} rel="external" data-testid="nav-neuroscape"
				>Browse the NeuroScape PubMed atlas <span class="arrow">→</span></a
			>
		{/if}
	</nav>
	<div class="header-controls" data-testid="atlas-root-header-controls">
		<ThemeToggle />
	</div>
</header>

<style>
	.landing-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 1.5rem;
		padding: 0.75rem 1.25rem;
		border-bottom: 1px solid var(--border);
		background: var(--bg-elevated);
		min-height: 3rem;
	}

	.brand {
		font-weight: 600;
		font-size: 1.1rem;
		letter-spacing: -0.01em;
		color: var(--text);
		text-decoration: none;
	}

	.nav-links {
		display: flex;
		gap: 1.25rem;
		align-items: center;
	}

	.header-controls {
		display: flex;
		gap: 0.5rem;
		align-items: center;
	}

	.nav-link {
		color: var(--text);
		text-decoration: none;
		font-size: 0.95rem;
		padding: 0.35rem 0.6rem;
		border-radius: 4px;
	}

	.nav-link:hover {
		background: var(--bg-subtle);
	}

	.arrow {
		display: inline-block;
		margin-left: 0.25em;
	}

	@media (max-width: 600px) {
		.landing-header {
			flex-direction: column;
			align-items: flex-start;
			gap: 0.5rem;
		}
		.nav-links {
			flex-direction: column;
			gap: 0.25rem;
			align-items: flex-start;
		}
	}
</style>
