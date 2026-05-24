<!--
  Stage 15 (spec 015-neuroscape-context, FR-013 + T041):
  the backdrop opacity/density slider on the bare-root atlas
  landing page. Controls the alpha of the NeuroScape backdrop
  points so the OHBM 2026 overlay stays readable at default zoom.

  NOT persisted (re-defaults to 0.25 on each load) — visitors
  rarely want a "remembered" density, and the slider is cheap to
  re-adjust per visit.
-->
<script lang="ts">
	import { createEventDispatcher } from 'svelte';

	/** Current opacity in [0.05, 1.0]. The parent owns the value
	 *  so the same slider can drive multiple consumers (UmapPanel
	 *  WebGL layers, hover targeting). */
	export let value: number = 0.25;

	const dispatch = createEventDispatcher<{ change: number }>();

	function onInput(event: Event) {
		const next = parseFloat((event.target as HTMLInputElement).value);
		value = next;
		dispatch('change', next);
	}
</script>

<label class="density-slider" data-testid="backdrop-density-slider">
	<span class="label-text">Backdrop opacity</span>
	<input
		type="range"
		min="0.05"
		max="1.0"
		step="0.05"
		value={value}
		on:input={onInput}
		aria-label="Backdrop opacity"
	/>
	<span class="value" data-testid="backdrop-density-value">{value.toFixed(2)}</span>
</label>

<style>
	.density-slider {
		display: inline-flex;
		align-items: center;
		gap: 0.5rem;
		padding: 0.35rem 0.6rem;
		border-radius: 4px;
		user-select: none;
		font-size: 0.95rem;
	}

	.label-text {
		color: var(--color-text-muted, #555);
	}

	.value {
		font-variant-numeric: tabular-nums;
		color: var(--color-text-muted, #555);
		min-width: 2.5em;
		text-align: right;
	}

	.density-slider input[type='range'] {
		min-width: 8rem;
	}
</style>
