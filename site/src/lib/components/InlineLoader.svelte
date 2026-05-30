<script lang="ts">
	/**
	 * Spec 019 follow-up — tiny inline "fetching" indicator rendered next to the
	 * result count while the full corpus (or other background data) is still
	 * streaming in. Uniform across atlas-root + /neuroscape/ so the loading
	 * affordance reads the same on every site. Three pulsing dots + an italic
	 * label; respects prefers-reduced-motion.
	 */
	export let label = 'loading';
</script>

<span
	class="inline-loader"
	role="status"
	aria-live="polite"
	data-testid="inline-loader"
	title="Still fetching data — the count will keep updating"
>
	<span class="dot"></span><span class="dot"></span><span class="dot"></span>
	<span class="lbl">{label}</span>
</span>

<style>
	.inline-loader {
		display: inline-flex;
		align-items: center;
		gap: 3px;
		margin-left: 8px;
		vertical-align: middle;
		opacity: 0.8;
	}
	.dot {
		width: 4px;
		height: 4px;
		border-radius: 50%;
		background: currentColor;
		animation: il-pulse 1s infinite ease-in-out;
	}
	.dot:nth-child(2) {
		animation-delay: 0.15s;
	}
	.dot:nth-child(3) {
		animation-delay: 0.3s;
	}
	.lbl {
		font-size: 0.85em;
		font-style: italic;
		margin-left: 3px;
	}
	@keyframes il-pulse {
		0%,
		80%,
		100% {
			opacity: 0.3;
		}
		40% {
			opacity: 1;
		}
	}
	@media (prefers-reduced-motion: reduce) {
		.dot {
			animation: none;
			opacity: 0.7;
		}
	}
</style>
