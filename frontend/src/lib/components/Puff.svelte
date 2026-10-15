<script lang="ts">
	// The puffy 3D monster: the balloon version of the drawing turning on the hill. Kids spin it
	// with a finger; the AR button (only where the tablet supports it) puts it on the table.
	// Once the gaming PC has made the AI version, it spins in a bubble in the corner: tapping the
	// bubble swaps the two, and the one in front is the kid's pick (chosen_style).
	// The swatch in the top corner is what the AI version is made of (fluffy, slimy, metal, ...):
	// it opens the other swatches, and a new pick makes the AI version again on the gaming PC.
	// In parent mode a printer button downloads the print file of the one in front.
	// model-viewer (and three.js) load only when this screen opens.
	import { onMount, untrack } from 'svelte';
	import { getGpu, SKINS, type Creature, type Skin, type Style } from '../api';
	import { sfx } from '../sfx';
	import SkinIcon from './SkinIcon.svelte';

	let {
		creature,
		parent = false,
		onback,
		onchoose,
		onskin
	}: {
		creature: Creature;
		parent?: boolean;
		onback: () => void;
		onchoose: (style: Style) => void;
		onskin: (skin: Skin) => void;
	} = $props();
	let ready = $state(false);
	let shown = $state(false);
	let gpu = $state(false); // no gaming PC set up: no AI version, nothing to pick
	let picking = $state(false);
	// a new skin is on its way (the old AI version shows until then)
	const remaking = $derived(
		creature.jobs.some((j) => (j.step === 'imagine' || j.step === 'ai3d') && j.status !== 'done' && j.status !== 'failed')
	);

	function pick(skin: Skin) {
		sfx.skin(skin);
		picking = false;
		if (skin !== creature.skin) onskin(skin);
	}

	const src = (style: Style) => (style === 'ai' ? creature.files.mesh_ai : creature.files.mesh_faithful);
	const hasAi = $derived(!!creature.files.mesh_ai && !!creature.files.mesh_faithful);
	// a pick of the AI version falls back to the balloon while the AI one is being made again
	let front = $state<Style>(
		untrack(() => (creature.chosen_style === 'ai' && creature.files.mesh_ai ? 'ai' : 'faithful'))
	);
	const other = $derived<Style>(front === 'ai' ? 'faithful' : 'ai');

	// the AI print is made after the AI version, so for a moment it may not be there yet
	const print = $derived(front === 'ai' ? creature.files.print_ai_3mf : creature.files.print_3mf);

	function swap() {
		sfx.boing();
		shown = false;
		front = other;
		onchoose(front);
	}

	onMount(async () => {
		getGpu().then(
			(g) => (gpu = g.enabled),
			() => {}
		);
		await import('@google/model-viewer');
		ready = true;
	});
</script>

<section class="screen" aria-label="{creature.name || 'Monster'} in 3D">
	<div class="hill" aria-hidden="true"></div>

	{#if ready}
		<model-viewer
			src={src(front)}
			alt="{creature.name || 'Monster'}, {front === 'ai' ? 'imagined' : 'puffed up'} in 3D"
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
		{#if hasAi}
			<button class="bubble" type="button" aria-label="Show the other monster" onclick={swap}>
				<model-viewer
					src={src(other)}
					alt=""
					auto-rotate
					auto-rotate-delay="0"
					rotation-per-second="60deg"
					interaction-prompt="none"
					camera-orbit="0deg 80deg auto"
					exposure="1.1"
				></model-viewer>
				<span class="mark" class:ai={other === 'ai'} aria-hidden="true">
					{#if other === 'ai'}
						<svg viewBox="0 0 24 24"
							><path d="M12 2 L14.2 9.2 L21.5 9.5 L15.6 13.9 L17.8 21 L12 16.7 L6.2 21 L8.4 13.9 L2.5 9.5 L9.8 9.2 Z" /></svg
						>
					{:else}
						<svg viewBox="0 0 24 24"><ellipse cx="12" cy="11" rx="7" ry="8.5" /><path d="M12 19.5 L10.5 22 H13.5 Z" /></svg>
					{/if}
				</span>
			</button>
		{/if}
	{/if}
	{#if !shown}
		<div class="waiting" aria-hidden="true"><span></span></div>
	{/if}

	{#if gpu}
		<div class="skins">
			<button
				class="skin current"
				class:remaking
				type="button"
				aria-label="What it is made of"
				aria-expanded={picking}
				onclick={() => {
					sfx.click();
					picking = !picking;
				}}
			>
				<SkinIcon skin={creature.skin} />
				{#if remaking}<span class="zzz" aria-hidden="true">z</span>{/if}
			</button>
			{#if picking}
				<div class="palette">
					{#each SKINS.filter((s) => s !== creature.skin) as skin, i (skin)}
						<button class="skin" type="button" aria-label={skin} style="--i: {i}" onclick={() => pick(skin)}>
							<SkinIcon {skin} />
						</button>
					{/each}
				</div>
			{/if}
		</div>
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
	{#if parent && print}
		<a
			class="print"
			href={print}
			download="{creature.name || `monster-${creature.id}`}{front === 'ai' ? '-ai' : ''}.3mf"
			aria-label="Download {front === 'ai' ? 'the AI version' : 'the puffy version'} for the 3D printer"
		>
			<svg viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"
				><path d="M7 9V3h10v6" /><rect x="3" y="9" width="18" height="8" rx="2" /><path d="M7 14h10v7H7z" /></svg
			>
		</a>
	{/if}
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
	.bubble {
		position: absolute;
		left: calc(24px + env(safe-area-inset-left, 0px));
		bottom: calc(24px + env(safe-area-inset-bottom, 0px));
		width: clamp(120px, 24vmin, 200px);
		aspect-ratio: 1;
		border-radius: 50%;
		border: 6px solid var(--ink);
		background: rgba(255, 255, 255, 0.7);
		box-shadow: 0 6px 0 rgba(46, 42, 59, 0.25);
		padding: 0;
		cursor: pointer;
		overflow: visible;
		animation: bob 2.4s ease-in-out infinite;
	}
	.bubble model-viewer {
		inset: 0;
		border-radius: 50%;
		overflow: hidden;
		pointer-events: none;
		opacity: 1;
		transform: none;
	}
	.mark {
		position: absolute;
		top: -10px;
		right: -10px;
		width: 44px;
		height: 44px;
		border-radius: 50%;
		border: 4px solid var(--ink);
		background: var(--paper);
		display: grid;
		place-items: center;
	}
	.mark svg {
		width: 70%;
		fill: var(--hill);
		stroke: var(--ink);
		stroke-width: 2;
		stroke-linejoin: round;
	}
	.mark.ai {
		background: var(--night);
	}
	.mark.ai svg {
		fill: var(--sun);
	}
	@keyframes bob {
		50% {
			transform: translateY(-8px);
		}
	}
	.back,
	.print,
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
	.print {
		top: calc(32px + clamp(64px, 11vmin, 92px) + env(safe-area-inset-top, 0px));
		left: calc(16px + env(safe-area-inset-left, 0px));
		width: clamp(64px, 11vmin, 92px);
		aspect-ratio: 1;
		background: var(--ink);
		border: 5px solid var(--paper);
	}
	.print svg {
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
	.skins {
		position: absolute;
		top: calc(16px + env(safe-area-inset-top, 0px));
		right: calc(16px + env(safe-area-inset-right, 0px));
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: 10px;
		max-height: calc(100% - 32px);
	}
	.skin {
		position: relative;
		width: clamp(60px, 10vmin, 84px);
		aspect-ratio: 1;
		border-radius: 50%;
		border: 5px solid var(--ink);
		background: var(--paper);
		padding: 6px;
		cursor: pointer;
		box-shadow: 0 6px 0 rgba(46, 42, 59, 0.25);
	}
	.skin.current {
		width: clamp(72px, 12vmin, 100px);
		border-color: var(--brass);
		background: var(--moon);
	}
	.skin.remaking :global(svg) {
		animation: snooze 2.4s ease-in-out infinite;
	}
	.zzz {
		position: absolute;
		top: -14px;
		left: -8px;
		font: 700 26px var(--display);
		color: var(--night);
		animation: drift 2.4s ease-in-out infinite;
	}
	@keyframes snooze {
		50% {
			transform: scale(0.88) rotate(-6deg);
			opacity: 0.7;
		}
	}
	@keyframes drift {
		0% {
			transform: translate(0, 6px);
			opacity: 0;
		}
		50% {
			opacity: 1;
		}
		100% {
			transform: translate(-8px, -10px);
			opacity: 0;
		}
	}
	.palette {
		display: grid;
		grid-template-columns: repeat(2, auto);
		gap: 10px;
		overflow-y: auto;
		padding: 4px 4px 10px;
	}
	.palette .skin {
		animation: pop-in 0.3s cubic-bezier(0.34, 1.56, 0.64, 1) both;
		animation-delay: calc(var(--i) * 35ms);
	}
	@keyframes pop-in {
		from {
			transform: scale(0);
		}
	}
	@media (prefers-reduced-motion: reduce) {
		model-viewer {
			transition: opacity 0.3s;
			transform: none;
		}
		.waiting span,
		.bubble,
		.skin.remaking :global(svg),
		.zzz,
		.palette .skin {
			animation: none;
		}
	}
</style>
