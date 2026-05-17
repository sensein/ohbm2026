<script lang="ts">
	import { themeChoice, effectiveTheme } from '$lib/stores/theme';

	$: choice = $themeChoice;
	$: effective = $effectiveTheme;

	$: label =
		choice === 'auto'
			? `Theme: auto (currently ${effective})`
			: choice === 'dark'
				? 'Theme: dark'
				: 'Theme: light';

	$: icon = choice === 'light' ? '☀' : choice === 'dark' ? '☾' : '◐';

	function handleClick() {
		themeChoice.cycle();
	}
</script>

<button
	type="button"
	class="theme-toggle"
	on:click={handleClick}
	aria-label={label}
	title={label}
	data-testid="theme-toggle"
	data-theme-choice={choice}
>
	<span class="icon" aria-hidden="true">{icon}</span>
	<span class="label-text">{choice}</span>
</button>

<style>
	.theme-toggle {
		all: unset;
		cursor: pointer;
		display: inline-flex;
		align-items: center;
		gap: 0.35rem;
		padding: 0.4rem 0.7rem;
		border: 1px solid var(--border-strong);
		border-radius: 4px;
		background: var(--bg);
		color: var(--text);
		font-size: 0.85rem;
		line-height: 1;
	}
	.theme-toggle:hover {
		background: var(--bg-sunken);
	}
	.icon {
		font-size: 1rem;
	}
	.label-text {
		text-transform: capitalize;
		color: var(--text-muted);
	}
</style>
