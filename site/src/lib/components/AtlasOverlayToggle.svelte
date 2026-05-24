<!--
  Stage 15 (spec 015-neuroscape-context, FR-009 + T040):
  the binary "Show OHBM 2026 overlay" toggle on the bare-root
  cross-conference atlas landing page.

  Bound to the localStorage-backed `atlasOverlay` writable store.
  Mirror of the existing `ThemeToggle` / `showMap` patterns.
-->
<script lang="ts">
	import { atlasOverlay, toggleAtlasOverlay } from '$lib/stores/atlas_overlay';

	$: checked = $atlasOverlay;
	$: label = checked ? 'Show OHBM 2026 overlay: on' : 'Show OHBM 2026 overlay: off';
</script>

<label
	class="atlas-overlay-toggle"
	data-testid="atlas-overlay-toggle"
	data-state={checked ? 'on' : 'off'}
	aria-label={label}
	title={label}
>
	<input
		type="checkbox"
		checked={checked}
		on:change={toggleAtlasOverlay}
		aria-label={label}
	/>
	<span class="visible-label">Show OHBM 2026 overlay</span>
</label>

<style>
	.atlas-overlay-toggle {
		display: inline-flex;
		align-items: center;
		gap: 0.5rem;
		cursor: pointer;
		padding: 0.35rem 0.6rem;
		border-radius: 4px;
		user-select: none;
		font-size: 0.95rem;
	}

	.atlas-overlay-toggle:hover {
		background: var(--color-surface-hover, rgba(0, 0, 0, 0.04));
	}

	.atlas-overlay-toggle input {
		cursor: pointer;
	}

	.visible-label {
		color: var(--color-text, #111);
	}
</style>
