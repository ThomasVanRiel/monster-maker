<script lang="ts">
	// The puffy 3D monster: the balloon version of the drawing turning on the hill. Kids spin it
	// with a finger; the AR button (only where the tablet supports it) puts it on the table.
	// model-viewer (and three.js) load only when this screen opens.
	import { onMount } from 'svelte';
	import type { Creature } from '../api';
	import { sfx } from '../sfx';

	let { creature, onback }: { creature: Creature; onback: () => void } = $props();
	let ready = $state(false);
	let shown = $state(false);

	onMount(async () => {
		await import('@google/model-viewer');
		ready = true;
	});
</script>

<section class="screen" aria-label="{creature.name || 'Monster'} in 3D">
	<div class="hill" aria-hidden="true"></div>

	{#if ready}
		<model-viewer
			src={creature.files.mesh_faithful}
			alt="{creature.name || 'Monster'}, puffed up in 3D"
			camera-controls
			disable-zoom
			disable-pan
			auto-rotate
			auto-rotate-delay="0"
			rotation-per-second="40deg"
			interaction-prompt="none"
			camera-orbit="0deg 80deg auto"
			shadow-intensity="1"
			exposure="1.1"
			ar
			ar-modes="webxr scene-viewer quick-look"
			ar-placement="floor"
			class:shown
			onload={() => {
				shown = true;
				sfx.pop();
			}}
		>
			<button slot="ar-button" class="ar" type="button" aria-label="Put {creature.name || 'the monster'} on the table">
				<svg viewBox="0 0 48 48" fill="none" stroke="#fff" stroke-width="4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"
					><path d="M24 6 L38 14 V28 L24 36 L10 28 V14 Z" /><path d="M10 14 L24 22 L38 14 M24 22 V36" /><path
						d="M4 40 Q24 48 44 40"
					/></svg
				>
			</button>
		</model-viewer>
	{/if}
	{#if !shown}
		<div class="waiting" aria-hidden="true"><span></span></div>
	{/if}

	<button
		class="back"
		type="button"
		aria-label="Back to the hill"
		onclick={() => {
			sfx.click();
			onback();
		}}
	>
		<svg viewBox="0 0 24 24" fill="none" stroke="#2E2A3B" stroke-width="3.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"
			><path d="M15 5 L8 12 L15 19" /></svg
		>
	</button>
</section>

<style>
	.screen {
		position: fixed;
		inset: 0;
		background: var(--sky);
		overflow: hidden;
	}
	.hill {
		position: absolute;
		left: -20%;
		right: -20%;
		bottom: -55vh;
		height: 90vh;
		border-radius: 50%;
		background: var(--hill);
	}
	model-viewer {
		position: absolute;
		inset: 0;
		width: 100%;
		height: 100%;
		--poster-color: transparent;
		opacity: 0;
		transform: scale(0.6);
		transition:
			opacity 0.3s,
			transform 0.5s cubic-bezier(0.34, 1.56, 0.64, 1);
	}
	model-viewer.shown {
		opacity: 1;
		transform: none;
	}
	.waiting {
		position: absolute;
		inset: 0;
		display: grid;
		place-items: center;
	}
	.waiting span {
		width: 90px;
		height: 90px;
		border-radius: 50%;
		background: rgba(255, 255, 255, 0.6);
		border: 5px dashed var(--ink);
		animation: puff 1.2s ease-in-out infinite;
	}
	@keyframes puff {
		50% {
			transform: scale(1.25);
		}
	}
	.back,
	.ar {
		position: absolute;
		display: grid;
		place-items: center;
		border-radius: 50%;
		cursor: pointer;
		padding: 0;
		box-shadow: 0 6px 0 rgba(46, 42, 59, 0.25);
	}
	.back {
		top: calc(16px + env(safe-area-inset-top, 0px));
		left: calc(16px + env(safe-area-inset-left, 0px));
		width: clamp(64px, 11vmin, 92px);
		aspect-ratio: 1;
		background: var(--paper);
		border: 5px solid var(--ink);
	}
	.back svg {
		width: 55%;
	}
	.ar {
		right: calc(24px + env(safe-area-inset-right, 0px));
		bottom: calc(24px + env(safe-area-inset-bottom, 0px));
		width: clamp(84px, 15vmin, 130px);
		aspect-ratio: 1;
		background: var(--go);
		border: 6px solid var(--ink);
	}
	.ar svg {
		width: 58%;
	}
	@media (prefers-reduced-motion: reduce) {
		model-viewer {
			transition: opacity 0.3s;
			transform: none;
		}
		.waiting span {
			animation: none;
		}
	}
</style>
