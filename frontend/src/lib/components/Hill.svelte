<script lang="ts">
	// Home screen: the current kid's creatures on a sideways-scrolling hill, kid avatars,
	// the parent lock (press and hold) and the magic glass that opens the camera.
	import { getGpu, type Creature, type GpuStatus, type Kid } from '../api';
	import { replay, type Critter } from '../critter';
	import { prefs } from '../prefs.svelte';
	import { sfx } from '../sfx';
	import CritterCanvas from './CritterCanvas.svelte';
	import KidFace from './KidFace.svelte';

	let {
		kids,
		creatures,
		hopId = null,
		parent = $bindable(false),
		onpickkid,
		onglass,
		onaddphoto,
		ondelete,
		onpuff,
		onrotate
	}: {
		kids: Kid[];
		creatures: Creature[];
		hopId?: number | null;
		parent?: boolean;
		onpickkid: (id: number) => void;
		onglass: () => void;
		onaddphoto: () => void;
		ondelete: (id: number) => void;
		onpuff: (id: number) => void;
		onrotate: (id: number) => void;
	} = $props();

	let vw = $state(innerWidth);
	let vh = $state(innerHeight);
	const size = $derived(Math.round(Math.max(110, Math.min(180, 0.2 * Math.min(vw, vh)))));
	const spacing = $derived(size * 1.28);
	const pad = $derived(Math.max(24, vw * 0.05));
	const glassW = $derived(Math.max(150, Math.min(236, 0.27 * Math.min(vw, vh))));
	const worldW = $derived(Math.max(vw, pad + creatures.length * spacing + glassW + 40));
	const OFFS = [0.15, 0.05, 0.22, 0.09];

	const bods: Record<number, HTMLElement> = $state({});
	const critters: Record<number, Critter | undefined> = $state({});
	let armed = $state<number | null>(null);
	let armT: ReturnType<typeof setTimeout>;

	function tap(id: number) {
		replay(bods[id]);
		sfx.boing();
		critters[id]?.blinkNow();
	}

	function del(id: number) {
		if (armed === id) {
			clearTimeout(armT);
			armed = null;
			ondelete(id);
			return;
		}
		armed = id;
		armT = setTimeout(() => (armed = null), 2500);
	}

	$effect(() => {
		if (hopId != null && bods[hopId]) replay(bods[hopId]);
	});

	// parent mode: how the gaming PC is doing (it makes the AI 3D versions)
	let gpu = $state<GpuStatus | null>(null);
	$effect(() => {
		if (!parent) return;
		const load = () => getGpu().then((g) => (gpu = g), () => (gpu = null));
		load();
		const t = setInterval(load, 10000);
		return () => clearInterval(t);
	});
	const GPU_STATES: Record<string, string> = {
		ready: 'ready',
		working: 'working',
		gaming: 'paused, someone is gaming',
		gpu_busy: 'paused, GPU in use',
		quiet_hours: 'off hours',
		no_gpu: 'no GPU found'
	};
	function gpuText(g: GpuStatus): string {
		if (!g.enabled) return 'AI 3D off';
		const w = g.workers[0];
		const away = !w || g.now - w.last_seen > 180; // it checks in every 30 s
		const state = away ? 'PC off' : `PC ${GPU_STATES[w.state] ?? w.state}`;
		const queue = g.waiting + g.running;
		return queue ? `${state} · ${queue} waiting` : state;
	}

	// parent lock: press and hold 1.2 s to enter, tap to leave
	let holding = $state(false);
	let holdT: ReturnType<typeof setTimeout>;
	function lockDown(e: PointerEvent) {
		e.preventDefault();
		if (parent) {
			parent = false;
			return;
		}
		holding = true;
		holdT = setTimeout(() => {
			holding = false;
			parent = true;
			sfx.pop();
		}, 1200);
	}
	function lockUp() {
		clearTimeout(holdT);
		holding = false;
	}
</script>

<svelte:window bind:innerWidth={vw} bind:innerHeight={vh} />

<section class="screen" class:parent aria-label="Monster Hill" style:--crit="{size}px">
	<div aria-hidden="true"><div class="sun"></div><div class="cloud c1"></div><div class="cloud c2"></div></div>
	<div class="world">
		<div class="worldInner" style:width="{worldW}px">
			<div class="hillback" aria-hidden="true"></div>
			<div class="hillfront" aria-hidden="true"></div>
			{#each creatures as cr, i (cr.id)}
				{@const asleep = !cr.files.cutout}
				<div class="critter" style:left="{pad + i * spacing}px" style:bottom="{Math.round(vh * OFFS[i % 4] + 24)}px">
					<button
						type="button"
						class="bodyBtn"
						aria-label="{cr.name || 'Monster'}, tap to play"
						onclick={() => tap(cr.id)}
					>
						<div class="shadow"></div>
						<div class="bod" bind:this={bods[cr.id]}>
							{#if asleep}
								<div class="sleeping" aria-hidden="true">
									<svg viewBox="0 0 120 120"
										><path
											d="M20 70 C15 35 45 15 65 22 C95 28 108 55 98 82 C90 104 40 108 26 92 Z"
											fill="rgba(255,255,255,.5)"
											stroke="#2E2A3B"
											stroke-width="4"
											stroke-dasharray="10 9"
											stroke-linecap="round"
										/><path
											d="M42 58 Q50 64 58 58 M68 56 Q76 62 84 56"
											fill="none"
											stroke="#2E2A3B"
											stroke-width="4"
											stroke-linecap="round"
										/></svg
									>
									<span class="z">z</span>
								</div>
							{:else}
								<CritterCanvas src={cr.files.cutout!} eyes={cr.eyes} bind:critter={critters[cr.id]} />
							{/if}
						</div>
					</button>
					{#if cr.name}<span class="name">{cr.name}</span>{/if}
					{#if cr.files.mesh_faithful}
						<button
							type="button"
							class="puff"
							aria-label="{cr.name || 'Monster'} in 3D"
							onclick={() => {
								sfx.pop();
								onpuff(cr.id);
							}}
						>
							{#if cr.files.mesh_ai}
								<svg class="sparkle" viewBox="0 0 24 24" aria-hidden="true"
									><path d="M12 1 L14.6 9.4 L23 12 L14.6 14.6 L12 23 L9.4 14.6 L1 12 L9.4 9.4 Z" /></svg
								>
							{/if}
							<svg viewBox="0 0 48 48" fill="none" stroke="#2E2A3B" stroke-width="3.6" stroke-linecap="round" aria-hidden="true"
								><ellipse cx="24" cy="24" rx="10" ry="13" fill="#fff" /><path d="M6 20 Q4 30 16 34" /><path
									d="M42 28 Q44 18 32 14"
								/><path d="M12 30 L16 34 L12 38 M36 18 L32 14 L36 10" stroke-linejoin="round" /></svg
							>
						</button>
					{/if}
					{#if cr.files.print_3mf}
						<a
							class="print"
							href={cr.files.print_3mf}
							download="{cr.name || `monster-${cr.id}`}.3mf"
							aria-label="Download {cr.name || 'this monster'} for the 3D printer"
						>
							<svg viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"
								><path d="M7 9V3h10v6" /><rect x="3" y="9" width="18" height="8" rx="2" /><path d="M7 14h10v7H7z" /></svg
							>
						</a>
					{/if}
					{#if cr.files.cutout}
						<button type="button" class="turn" aria-label="Turn {cr.name || 'this monster'}" onclick={() => onrotate(cr.id)}>
							<svg viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"
								><path d="M4 12a8 8 0 0 1 14.3-4.9" /><path d="M19 3v5h-5" /><path d="M20 12a8 8 0 0 1-14.3 4.9" /></svg
							>
						</button>
					{/if}
					<button
						type="button"
						class="del"
						class:armed={armed === cr.id}
						aria-label="Delete {cr.name || 'this monster'} (tap twice)"
						onclick={() => del(cr.id)}
					>
						<svg viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="3.4" stroke-linecap="round" aria-hidden="true"
							><path d="M6 6l12 12M18 6L6 18" /></svg
						>
					</button>
				</div>
			{/each}
		</div>
	</div>

	{#if creatures.length === 0}
		<div class="empty" aria-hidden="true">
			<svg class="ghost" viewBox="0 0 120 120"
				><path
					d="M20 70 C15 35 45 15 65 22 C95 28 108 55 98 82 C90 104 40 108 26 92 Z"
					fill="rgba(255,255,255,.35)"
					stroke="#2E2A3B"
					stroke-width="4"
					stroke-dasharray="10 9"
					stroke-linecap="round"
				/><path d="M46 56 Q52 62 58 56 M70 54 Q76 60 82 54" fill="none" stroke="#2E2A3B" stroke-width="4" stroke-linecap="round" /></svg
			>
			<svg class="arrow" viewBox="0 0 100 100"
				><path d="M10 20 Q60 20 80 72" fill="none" stroke="#2E2A3B" stroke-width="9" stroke-linecap="round" /><path
					d="M60 66 L82 78 L88 52"
					fill="none"
					stroke="#2E2A3B"
					stroke-width="9"
					stroke-linecap="round"
					stroke-linejoin="round"
				/></svg
			>
		</div>
	{/if}

	<div class="topbar">
		<div class="kids" role="group" aria-label="Who is playing">
			{#each kids as k, i (k.id)}
				<button
					type="button"
					class="kid"
					style:background={k.color}
					aria-label={k.name}
					aria-pressed={prefs.kidId === k.id}
					onclick={() => onpickkid(k.id)}
				>
					<KidFace index={i} />
				</button>
			{/each}
		</div>
		{#if parent}
			<div class="parentbar">
				<strong>Parent mode</strong>
				<button class="pbtn" type="button" onclick={onaddphoto}>Add from photos</button>
				{#if gpu}<span class="gpu" title={gpu.workers[0]?.detail ?? ''}>{gpuText(gpu)}</span>{/if}
				<button
					class="pbtn"
					type="button"
					aria-pressed={prefs.sound}
					onclick={() => {
						prefs.sound = !prefs.sound;
						sfx.pop();
					}}>{prefs.sound ? 'Sound on' : 'Sound off'}</button
				>
				<button class="pbtn" type="button" onclick={() => (parent = false)}>Done</button>
			</div>
		{/if}
		<button
			class="lock"
			class:holding
			type="button"
			aria-label={parent ? 'Leave parent mode' : 'Parent mode: press and hold'}
			onpointerdown={lockDown}
			onpointerup={lockUp}
			onpointerleave={lockUp}
			onpointercancel={lockUp}
			onclick={(e) => {
				if (e.detail === 0) parent = !parent; // keyboard
			}}
			oncontextmenu={(e) => e.preventDefault()}
		>
			<svg class="ring" viewBox="0 0 68 68" aria-hidden="true"><circle cx="34" cy="34" r="32" /></svg>
			<svg
				class="icon"
				viewBox="0 0 24 24"
				fill="none"
				stroke="#2E2A3B"
				stroke-width="2"
				stroke-linecap="round"
				stroke-linejoin="round"
				aria-hidden="true"><rect x="5" y="11" width="14" height="10" rx="2" /><path d="M8 11V8a4 4 0 0 1 8 0v3" /></svg
			>
		</button>
	</div>

	<button
		class="glass"
		type="button"
		aria-label="Find a new monster with the magic glass"
		onclick={() => {
			sfx.pop();
			onglass();
		}}
	>
		<svg viewBox="0 0 120 120" aria-hidden="true"
			><path d="M78 78 L108 108" stroke="#2E2A3B" stroke-width="22" stroke-linecap="round" /><path
				d="M78 78 L108 108"
				stroke="#B5651D"
				stroke-width="13"
				stroke-linecap="round"
			/><circle cx="50" cy="50" r="42" fill="#2E2A3B" /><circle cx="50" cy="50" r="38" fill="#F5B83D" /><circle
				cx="50"
				cy="50"
				r="30"
				fill="#DDF3FB"
				stroke="#2E2A3B"
				stroke-width="3"
			/><path d="M32 42 Q36 30 48 26" fill="none" stroke="#FFFFFF" stroke-width="6" stroke-linecap="round" /><circle
				cx="58"
				cy="56"
				r="5"
				fill="#2E2A3B"
			/></svg
		>
	</button>
</section>

<style>
	.world {
		position: absolute;
		inset: 0;
		overflow-x: auto;
		overflow-y: hidden;
		scrollbar-width: none;
		-webkit-overflow-scrolling: touch;
	}
	.world::-webkit-scrollbar {
		display: none;
	}
	.worldInner {
		position: relative;
		height: 100%;
		min-width: 100%;
	}
	.topbar {
		position: absolute;
		top: calc(16px + env(safe-area-inset-top, 0px));
		left: calc(16px + env(safe-area-inset-left, 0px));
		right: calc(16px + env(safe-area-inset-right, 0px));
		display: flex;
		flex-wrap: wrap;
		align-items: flex-start;
		gap: 14px;
		z-index: 5;
		pointer-events: none;
	}
	.topbar > * {
		pointer-events: auto;
	}
	.kids {
		display: flex;
		gap: clamp(10px, 2vmin, 22px);
		align-items: center;
	}
	.kid {
		width: clamp(64px, 11vmin, 100px);
		aspect-ratio: 1;
		border-radius: 50%;
		border: 6px solid transparent;
		display: grid;
		place-items: center;
		cursor: pointer;
		padding: 0;
		transition: transform 0.25s;
	}
	.kid :global(svg) {
		width: 58%;
		height: 58%;
	}
	.kid[aria-pressed='true'] {
		border-color: var(--ink);
		box-shadow: 0 0 0 6px var(--paper);
		transform: scale(1.04);
	}
	.kid[aria-pressed='false'] {
		transform: scale(0.84);
	}
	.lock {
		margin-left: auto;
		position: relative;
		width: 56px;
		height: 56px;
		border-radius: 50%;
		border: 2px dashed #7a8aa0;
		background: transparent;
		opacity: 0.6;
		display: grid;
		place-items: center;
		cursor: pointer;
		padding: 0;
		touch-action: none;
	}
	.lock svg.icon {
		width: 26px;
		height: 26px;
	}
	.lock .ring {
		position: absolute;
		inset: -6px;
		width: 68px;
		height: 68px;
		transform: rotate(-90deg);
		pointer-events: none;
	}
	.lock .ring circle {
		fill: none;
		stroke: var(--ink);
		stroke-width: 4;
		stroke-linecap: round;
		stroke-dasharray: 201;
		stroke-dashoffset: 201;
	}
	.lock.holding .ring circle {
		transition: stroke-dashoffset 1.2s linear;
		stroke-dashoffset: 0;
	}
	.parent .lock {
		opacity: 1;
		border-style: solid;
		border-color: var(--ink);
		background: var(--paper);
	}
	.parentbar {
		display: flex;
		flex-wrap: wrap;
		gap: 8px;
		align-items: center;
		background: var(--paper);
		border-radius: 18px;
		padding: 8px;
		box-shadow: 0 6px 0 rgba(46, 42, 59, 0.14);
		font-size: 17px;
		max-width: 100%;
	}
	.parentbar strong {
		padding: 0 8px;
		font-weight: 700;
	}
	.pbtn {
		font-weight: 600;
		border: 0;
		border-radius: 12px;
		background: var(--mist);
		padding: 10px 14px;
		min-height: 44px;
		cursor: pointer;
	}
	.pbtn[aria-pressed='false'] {
		color: var(--ink-soft);
	}
	.critter {
		position: absolute;
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: 4px;
		width: var(--crit);
	}
	.bodyBtn {
		background: none;
		border: 0;
		padding: 0;
		cursor: pointer;
		position: relative;
		display: block;
		border-radius: 24px;
	}
	.shadow {
		position: absolute;
		left: 20%;
		right: 20%;
		bottom: -6px;
		height: 16px;
		border-radius: 50%;
		background: rgba(46, 42, 59, 0.18);
	}
	.sleeping {
		width: var(--crit);
		height: var(--crit);
		position: relative;
		opacity: 0.8;
	}
	.sleeping svg {
		width: 100%;
		height: 100%;
	}
	.sleeping .z {
		position: absolute;
		right: 4%;
		top: 0;
		font-size: calc(var(--crit) * 0.22);
		font-weight: 700;
		color: var(--night);
		animation: zz 3s ease-in-out infinite;
	}
	@keyframes zz {
		0%,
		100% {
			transform: translate(0, 0);
			opacity: 0.4;
		}
		50% {
			transform: translate(6px, -12px);
			opacity: 1;
		}
	}
	.name {
		background: var(--paper);
		border-radius: 999px;
		padding: 3px 14px;
		font-weight: 700;
		font-size: clamp(15px, 2.4vmin, 20px);
		max-width: calc(var(--crit) + 30px);
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.del {
		display: none;
		position: absolute;
		top: -4px;
		right: 0;
		width: 52px;
		height: 52px;
		border-radius: 50%;
		border: 4px solid var(--paper);
		background: var(--stop);
		place-items: center;
		cursor: pointer;
		padding: 0;
		z-index: 2;
	}
	.del svg {
		width: 24px;
		height: 24px;
	}
	.puff {
		position: absolute;
		top: -4px;
		left: 0;
		width: 56px;
		height: 56px;
		border-radius: 50%;
		border: 4px solid var(--ink);
		background: var(--sun);
		display: grid;
		place-items: center;
		cursor: pointer;
		padding: 0;
		z-index: 2;
	}
	.puff svg {
		width: 78%;
	}
	.puff .sparkle {
		position: absolute;
		top: -12px;
		right: -12px;
		width: 30px;
		fill: var(--paper);
		stroke: var(--ink);
		stroke-width: 2.2;
		stroke-linejoin: round;
	}
	.gpu {
		padding: 0 8px;
		color: var(--ink-soft);
		font-weight: 600;
	}
	.print {
		display: none;
		position: absolute;
		top: -4px;
		left: 0;
		width: 52px;
		height: 52px;
		border-radius: 50%;
		border: 4px solid var(--paper);
		background: var(--ink);
		place-items: center;
		z-index: 2;
	}
	.print svg {
		width: 60%;
	}
	.parent .print {
		display: grid;
	}
	.turn {
		display: none;
		position: absolute;
		top: -4px;
		left: 50%;
		translate: -50% 0;
		width: 52px;
		height: 52px;
		border-radius: 50%;
		border: 4px solid var(--paper);
		background: var(--ink-soft);
		place-items: center;
		cursor: pointer;
		padding: 0;
		z-index: 2;
	}
	.turn svg {
		width: 62%;
	}
	.parent .turn {
		display: grid;
	}
	.parent .puff {
		display: none;
	}
	.parent .del {
		display: grid;
	}
	.del.armed {
		transform: scale(1.25);
		animation: shake 0.25s 3;
	}
	@keyframes shake {
		0%,
		100% {
			rotate: 0deg;
		}
		33% {
			rotate: -12deg;
		}
		66% {
			rotate: 12deg;
		}
	}
	.glass {
		position: absolute;
		right: calc(18px + env(safe-area-inset-right, 0px));
		bottom: calc(10px + env(safe-area-inset-bottom, 0px));
		width: clamp(150px, 27vmin, 236px);
		aspect-ratio: 1;
		background: none;
		border: 0;
		padding: 0;
		cursor: pointer;
		z-index: 4;
		animation: pulse 2.2s ease-in-out infinite;
	}
	.glass svg {
		width: 100%;
		height: 100%;
		filter: drop-shadow(0 8px 0 rgba(46, 42, 59, 0.18));
	}
	.empty {
		position: absolute;
		left: 50%;
		bottom: 16vh;
		transform: translateX(-60%);
		display: flex;
		align-items: flex-end;
		gap: 2vmin;
		pointer-events: none;
	}
	.empty svg.ghost {
		width: clamp(110px, 20vmin, 180px);
		height: auto;
	}
	.empty svg.arrow {
		width: clamp(70px, 12vmin, 120px);
		height: auto;
		animation: nudge 1.2s ease-in-out infinite;
	}
	@keyframes nudge {
		0%,
		100% {
			transform: translate(0, 0);
		}
		50% {
			transform: translate(14px, 8px);
		}
	}
	@media (prefers-reduced-motion: reduce) {
		.glass,
		.empty svg.arrow,
		.sleeping .z {
			animation: none;
		}
	}
</style>
