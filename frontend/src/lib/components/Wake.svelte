<script lang="ts">
	// Sleep, then wake: night falls while the photo uploads and the server cuts it out; the
	// creature wakes up under its blanket, the parent can mark eyes and type a name, then save.
	// A slow or failed cleanup is never an error: the monster just stays asleep for now.
	import { onDestroy, onMount } from 'svelte';
	import { deleteCreature, getCreature, rotateCreature, rotateEyes, updateCreature, uploadPhoto, whenStepSettles, type Eye } from '../api';
	import { Critter, replay } from '../critter';
	import { sfx } from '../sfx';

	let {
		kidId,
		photo,
		onsaved,
		onleave,
		onretake
	}: {
		kidId: number;
		photo: Blob;
		onsaved: (id: number) => void;
		onleave: () => void;
		onretake: () => void;
	} = $props();

	const MIN_SLEEP_MS = 2800;
	let phase = $state<'sleeping' | 'waking' | 'awake' | 'stuck'>('sleeping');
	let creatureId: number | null = null;
	let name = $state('');
	let marking = $state(false);
	let eyes: Eye[] = [];
	let canvas: HTMLCanvasElement;
	let bod: HTMLElement;
	let critter: Critter | null = null;
	let gone = false;

	const wait = (ms: number) => new Promise((r) => setTimeout(r, ms));

	onMount(async () => {
		sfx.snore();
		const t0 = performance.now();
		try {
			const c = await uploadPhoto(kidId, photo);
			creatureId = c.id;
			if (gone) return void deleteCreature(c.id).catch(() => {});
			const ok = await whenStepSettles(c.id, 'cleanup');
			if (gone) return;
			const cutout = ok ? (await getCreature(c.id)).files.cutout : undefined;
			if (!cutout) throw new Error('no cutout');
			const im = new Image();
			im.src = cutout;
			await im.decode();
			if (gone) return;
			critter = new Critter(canvas, im, { sleeping: true, eyes });
			phase = 'waking';
			await wait(Math.max(400, MIN_SLEEP_MS - (performance.now() - t0)));
			if (!gone) wakeUp();
		} catch {
			if (!gone) phase = 'stuck';
		}
	});

	onDestroy(() => {
		gone = true;
		critter?.destroy();
	});

	function wakeUp() {
		if (!critter || !critter.sleeping) return;
		critter.sleeping = false;
		critter.blinkNow();
		phase = 'awake';
		replay(bod);
		sfx.tada();
	}

	// Drawn sideways? A quarter turn per tap; the server turns the cutout and redoes 3D and print.
	let turning = $state(false);
	async function turn() {
		if (creatureId == null || !critter || turning) return;
		turning = true;
		sfx.pop();
		try {
			const c = await rotateCreature(creatureId);
			const im = new Image();
			im.src = c.files.cutout!;
			await im.decode();
			if (gone) return;
			eyes = rotateEyes(eyes, critter.iw, critter.ih);
			critter.destroy();
			critter = new Critter(canvas, im, { eyes });
			critter.showEyes = marking;
			if (!matchMedia('(prefers-reduced-motion: reduce)').matches)
				bod.animate([{ transform: 'rotate(-90deg) scale(0.9)' }, { transform: 'none' }], {
					duration: 380,
					easing: 'cubic-bezier(0.34, 1.56, 0.64, 1)'
				});
		} catch {
			/* server busy or unreachable: it just doesn't turn */
		} finally {
			turning = false;
		}
	}

	function setMarking(on: boolean) {
		marking = on;
		if (critter) critter.showEyes = on;
	}

	function tapCanvas(e: MouseEvent) {
		if (!critter) return;
		if (critter.sleeping) return wakeUp();
		if (marking) {
			const p = critter.toImage(e.clientX, e.clientY);
			if (p.x < 0 || p.x > 1 || p.y < 0 || p.y > 1) return;
			const c = critter;
			const near = eyes.findIndex((q) => Math.hypot((q.x - p.x) * c.dw, (q.y - p.y) * c.dh) < q.r * c.dw * 1.4);
			if (near >= 0) eyes.splice(near, 1);
			else if (eyes.length < 6) eyes.push({ x: p.x, y: p.y, r: 0.06 });
			c.eyes = eyes;
			c.lidColors();
			c.blinkNow();
			sfx.pop();
			return;
		}
		replay(bod);
		sfx.boing();
		critter.blinkNow();
	}

	async function save(e: SubmitEvent) {
		e.preventDefault();
		if (creatureId == null || phase !== 'awake') return;
		try {
			await updateCreature(creatureId, { name: name.trim().slice(0, 24), eyes });
		} catch {
			/* the creature itself is saved already; name/eyes can be fixed later */
		}
		sfx.boing();
		onsaved(creatureId);
	}

	/** Leaving before saving throws the new creature away — unless it is stuck asleep,
	 *  then it stays on the hill and wakes up when the server gets to it. */
	function discardThen(next: () => void) {
		gone = true;
		if (creatureId != null && phase !== 'stuck') void deleteCreature(creatureId).catch(() => {});
		next();
	}
</script>

<section class="screen wake" class:night={phase !== 'awake'} aria-label="Your new monster">
	<div aria-hidden="true">
		<div class="sun"></div>
		<div class="cloud c1"></div>
		<div class="cloud c2"></div>
		<div class="moon"></div>
		<i class="star" style="top:14%;left:38%"></i><i class="star" style="top:9%;left:64%"></i><i
			class="star"
			style="top:24%;left:84%"
		></i><i class="star" style="top:30%;left:26%"></i>
	</div>
	<div class="hillback" aria-hidden="true"></div>
	<div class="hillfront" aria-hidden="true"></div>
	<button class="round tl" type="button" aria-label="Back to the hill without saving" onclick={() => discardThen(onleave)}>
		<svg
			viewBox="0 0 24 24"
			fill="none"
			stroke="#2E2A3B"
			stroke-width="3"
			stroke-linecap="round"
			stroke-linejoin="round"
			aria-hidden="true"><path d="M15 5l-7 7 7 7" /></svg
		>
	</button>
	{#if marking}<p class="eyehint">Tap each eye so it can blink</p>{/if}
	<div class="bed" class:asleep={phase !== 'awake'} class:awake={phase === 'awake'} class:marking>
		<div class="bod" bind:this={bod}>
			<canvas bind:this={canvas} aria-label="Your monster" onclick={tapCanvas}></canvas>
		</div>
		<div class="blanket" aria-hidden="true"></div>
		<div class="zzz" aria-hidden="true"><span>z</span><span>z</span><span>z</span></div>
	</div>
	{#if phase !== 'awake'}
		<div class="dots" aria-hidden="true"><i></i><i></i><i></i></div>
		<p class="hint">
			{#if phase === 'sleeping'}Shh… your monster is sleeping
			{:else if phase === 'waking'}Shh… your monster is waking up
			{:else}Your monster is fast asleep. It will wake up later on the hill{/if}
		</p>
	{:else}
		<form class="sheet" onsubmit={save}>
			<button
				class="big plain eyes"
				type="button"
				aria-pressed={marking}
				aria-label="Mark the eyes"
				onclick={() => setMarking(!marking)}
			>
				<svg
					viewBox="0 0 24 24"
					fill="none"
					stroke="#2E2A3B"
					stroke-width="2.2"
					stroke-linecap="round"
					stroke-linejoin="round"
					aria-hidden="true"><path d="M2 12s3.5-6 10-6 10 6 10 6-3.5 6-10 6S2 12 2 12z" /><circle cx="12" cy="12" r="3" /></svg
				>
			</button>
			<button class="big plain" type="button" aria-label="Turn the monster" disabled={turning} onclick={turn}>
				<svg
					viewBox="0 0 24 24"
					fill="none"
					stroke="#2E2A3B"
					stroke-width="2.4"
					stroke-linecap="round"
					stroke-linejoin="round"
					aria-hidden="true"><path d="M12 8 19 15 12 22 5 15Z" fill="#FFD45C" /><path d="M3.5 10a9.5 7.5 0 0 1 15.5-5.5" /><path d="M20 1.5v4.5h-4.5" /></svg
				>
			</button>
			<label class="sr" for="cname">Monster name</label>
			<input id="cname" bind:value={name} maxlength="24" autocomplete="off" placeholder="Name it!" />
			<button class="big save" type="submit" aria-label="Save to the hill">
				<svg
					viewBox="0 0 24 24"
					fill="none"
					stroke="#FFFFFF"
					stroke-width="3.2"
					stroke-linecap="round"
					stroke-linejoin="round"
					aria-hidden="true"><path d="M5 12l5 5 9-10" /></svg
				>
			</button>
			<button class="big plain" type="button" aria-label="Take another photo" onclick={() => discardThen(onretake)}>
				<svg
					viewBox="0 0 24 24"
					fill="none"
					stroke="#2E2A3B"
					stroke-width="2.4"
					stroke-linecap="round"
					stroke-linejoin="round"
					aria-hidden="true"><path d="M20 12a8 8 0 1 1-2.3-5.6" /><path d="M20 4v5h-5" /></svg
				>
			</button>
		</form>
	{/if}
</section>

<style>
	.wake {
		background: var(--sky);
		transition: background-color 1s;
	}
	.wake.night {
		background: var(--night);
	}
	.wake .sun,
	.wake .cloud {
		transition: opacity 1s;
	}
	.wake.night .sun,
	.wake.night .cloud {
		opacity: 0;
	}
	.moon,
	.star {
		position: absolute;
		opacity: 0;
		transition: opacity 1s;
	}
	.wake.night .moon,
	.wake.night .star {
		opacity: 1;
	}
	.moon {
		top: 10%;
		left: 12%;
		width: clamp(60px, 10vmin, 96px);
		aspect-ratio: 1;
		border-radius: 50%;
		box-shadow: calc(clamp(60px, 10vmin, 96px) * 0.24) calc(clamp(60px, 10vmin, 96px) * -0.1) 0 0 var(--moon);
		background: transparent;
	}
	.star {
		width: 8px;
		height: 8px;
		border-radius: 50%;
		background: var(--moon);
	}
	.wake .hillback,
	.wake .hillfront {
		transition: background-color 1s;
	}
	.wake.night .hillback {
		background: var(--hill-night);
	}
	.wake.night .hillfront {
		background: var(--hill-night-deep);
	}
	.bed {
		position: absolute;
		left: 50%;
		top: 44%;
		--W: min(52vmin, 430px);
		width: var(--W);
		height: var(--W);
		translate: -50% -50%;
	}
	.bed .bod {
		position: absolute;
		inset: 0;
	}
	.bed canvas {
		width: 100%;
		height: 100%;
		display: block;
		transition: filter 1s;
		cursor: pointer;
	}
	.bed.asleep canvas {
		filter: brightness(0.38) saturate(0.3);
	}
	.bed.marking canvas {
		cursor: crosshair;
	}
	.blanket {
		position: absolute;
		left: -10%;
		right: -10%;
		bottom: -6%;
		height: 46%;
		background: var(--sun);
		border: 6px solid var(--ink);
		border-radius: 46% 46% 22px 22px / 34% 34% 22px 22px;
		transition:
			transform 0.8s cubic-bezier(0.5, -0.3, 0.6, 1),
			opacity 0.8s;
		z-index: 2;
		pointer-events: none;
	}
	.blanket::after {
		content: '';
		position: absolute;
		left: 8%;
		right: 8%;
		top: 30%;
		border-top: 5px dashed #c99a1e;
	}
	.bed.awake .blanket {
		transform: translateY(140%) rotate(10deg);
		opacity: 0;
	}
	.zzz {
		position: absolute;
		right: -6%;
		top: 6%;
		font-size: clamp(34px, 6vmin, 58px);
		font-weight: 700;
		color: var(--moon);
		pointer-events: none;
		z-index: 3;
	}
	.zzz span {
		position: absolute;
		animation: zz 3s linear infinite;
		opacity: 0;
	}
	.zzz span:nth-child(2) {
		animation-delay: -1s;
		font-size: 0.8em;
		left: 0.6em;
	}
	.zzz span:nth-child(3) {
		animation-delay: -2s;
		font-size: 0.62em;
		left: 1.2em;
	}
	@keyframes zz {
		0% {
			transform: translate(0, 0);
			opacity: 0;
		}
		20% {
			opacity: 1;
		}
		100% {
			transform: translate(40px, -120px);
			opacity: 0;
		}
	}
	.bed.awake .zzz {
		display: none;
	}
	.dots {
		position: absolute;
		left: 0;
		right: 0;
		bottom: calc(92px + env(safe-area-inset-bottom, 0px));
		display: flex;
		justify-content: center;
		gap: 26px;
	}
	.dots i {
		width: 40px;
		height: 40px;
		border-radius: 50%;
		border: 5px solid var(--paper);
		animation: fill 2.4s ease-in-out infinite;
	}
	.dots i:nth-child(2) {
		animation-delay: 0.8s;
	}
	.dots i:nth-child(3) {
		animation-delay: 1.6s;
	}
	@keyframes fill {
		0%,
		100% {
			background: transparent;
			transform: scale(1);
		}
		40% {
			background: var(--sun);
			transform: scale(1.2);
		}
	}
	.hint {
		position: absolute;
		left: 16px;
		right: 16px;
		bottom: calc(30px + env(safe-area-inset-bottom, 0px));
		margin: 0;
		text-align: center;
		font-size: clamp(20px, 3.4vmin, 30px);
		font-weight: 500;
		color: var(--paper);
		text-wrap: balance;
	}
	.sheet {
		position: absolute;
		left: 50%;
		translate: -50% 0;
		bottom: calc(18px + env(safe-area-inset-bottom, 0px));
		display: flex;
		flex-wrap: wrap;
		justify-content: center;
		align-items: center;
		gap: 12px;
		background: var(--paper);
		border-radius: 28px;
		padding: 12px;
		box-shadow: 0 8px 0 rgba(46, 42, 59, 0.16);
		width: max-content;
		max-width: calc(100vw - 32px);
		box-sizing: border-box;
		z-index: 5;
	}
	.sheet input {
		font: inherit;
		font-size: 24px;
		font-weight: 600;
		min-height: 60px;
		border: 3px solid #d5e2ec;
		border-radius: 18px;
		padding: 0 18px;
		width: min(44vw, 320px);
		box-sizing: border-box;
		color: var(--ink);
		background: var(--paper);
		-webkit-user-select: text;
		user-select: text;
	}
	.sheet input::placeholder {
		color: #8a97a6;
	}
	.big {
		width: 68px;
		height: 68px;
		border-radius: 50%;
		border: 0;
		display: grid;
		place-items: center;
		cursor: pointer;
		padding: 0;
		box-shadow: 0 5px 0 rgba(46, 42, 59, 0.2);
	}
	.big svg {
		width: 34px;
		height: 34px;
	}
	.big:active {
		transform: translateY(3px);
		box-shadow: 0 2px 0 rgba(46, 42, 59, 0.2);
	}
	.big.save {
		background: var(--ok);
		width: 88px;
		height: 88px;
		box-shadow: 0 6px 0 var(--ok-deep);
	}
	.big.save svg {
		width: 46px;
		height: 46px;
	}
	.big.plain {
		background: var(--mist);
	}
	.big.eyes[aria-pressed='true'] {
		background: var(--brass);
	}
	.eyehint {
		position: absolute;
		left: 50%;
		translate: -50% 0;
		top: calc(18px + env(safe-area-inset-top, 0px));
		margin: 0;
		background: var(--paper);
		border-radius: 999px;
		padding: 8px 18px;
		font-size: 18px;
		font-weight: 600;
		z-index: 5;
		max-width: calc(100vw - 140px);
		text-align: center;
	}
	@media (orientation: portrait) {
		.bed {
			top: 38%;
			--W: min(70vw, 48vh);
		}
	}
	@media (prefers-reduced-motion: reduce) {
		.zzz span {
			animation-duration: 6s;
		}
	}
</style>
