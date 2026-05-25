<!--
  Atlas-root hub-and-spoke subsite navigation strip.

  Mounted only by the atlas-root +page.svelte build (the cross-
  conference landing). Surfaces an "outbound" link per sibling
  subsite so visitors can drop into a specific corpus directly.
  Subsites do NOT mirror this strip — they only carry a home icon
  back to the root (see SiteHeader). This keeps the navigation
  hub-and-spoke: adding a new subsite just touches this strip; no
  per-sibling rewiring.

  When the subsite count grows past ~4–5, swap the inline links
  for a compact searchable dropdown that reads the available list
  from `data/outputs/parquets/<state-key>/atlas.parquet`'s
  manifest (subsites are listed there as part of the cross-
  parquet drift contract).
-->
<script lang="ts">
	import { base } from '$app/paths';

	// `base` on the atlas-root build IS the deploy root (no per-mode
	// suffix), so we don't need the `rootBase()` strip dance that
	// SiteHeader does — atlas-root is the only mode that mounts this.
	const ROOT = base;
	const OHBM2026_HREF = `${ROOT}/ohbm2026/`;
	const NEUROSCAPE_HREF = `${ROOT}/neuroscape/`;
</script>

<nav class="subsite-nav" aria-label="Sibling subsites" data-testid="atlas-subsite-nav">
	<span class="label">Browse a corpus directly:</span>
	<!-- rel="external" tells SvelteKit's prerenderer + link-interceptor
	     these point at SIBLING SvelteKit deployments (separately-built
	     bundles), NOT in-app routes. -->
	<a
		class="subsite-link"
		href={OHBM2026_HREF}
		rel="external"
		data-testid="nav-ohbm2026"
	>
		OHBM 2026 abstracts <span class="arrow">→</span>
	</a>
	<a
		class="subsite-link"
		href={NEUROSCAPE_HREF}
		rel="external"
		data-testid="nav-neuroscape"
	>
		NeuroScape PubMed atlas <span class="arrow">→</span>
	</a>
</nav>

<style>
	.subsite-nav {
		display: flex;
		align-items: center;
		flex-wrap: wrap;
		gap: 0.4rem 1rem;
		padding: 0.5rem clamp(1rem, 2vw, 2rem);
		font-size: 0.88rem;
		border-bottom: 1px solid var(--border);
		background: var(--bg-elevated, var(--bg));
	}
	.label {
		color: var(--text-muted);
	}
	.subsite-link {
		color: var(--accent);
		text-decoration: none;
		padding: 0.25rem 0.5rem;
		border-radius: 4px;
	}
	.subsite-link:hover {
		background: var(--accent-soft-bg);
	}
	.arrow {
		display: inline-block;
		margin-left: 0.25em;
	}
</style>
