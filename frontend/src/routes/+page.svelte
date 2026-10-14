<script lang="ts">
	// Monster Hill: hill (gallery) -> magic glass (camera) -> sleep & wake -> back to the hill.
	import { onDestroy, onMount } from 'svelte';
	import { deleteCreature, listCreatures, listKids, type Creature, type Kid } from '#lib/api.ts';
	import { prefs } from '#lib/prefs.svelte.ts';
	import { sfx } from '#lib/sfx.ts';
	import Hill from '#lib/components/Hill.svelte';
	import Lens from '#lib/components/Lens.svelte';
	import Puff from '#lib/components/Puff.svelte';
	import Wake from '#lib/components/Wake.svelte';

	let screen = $state<'hill' | 'lens' | 'wake' | 'puff'>('hill');
	let puffId = $state<number | null>(null);
	let kids = $state<Kid[]>([]);
	let creatures = $state<Creature[]>([]);
	const puffed = $derived(creatures.find((c) => c.id === puffId));
	let photo = $state<Blob | null>(null);
	let hopId = $state<number | null>(null);
	let parent = $state(false);
	let flashOn = $state(false);
	let fileAny: HTMLInputElement;

	const kid = $derived(kids.find((k) => k.id === prefs.kidId) ?? kids[0]);

	async function refresh() {
		if (!kid) return;
		try {
			creatures = await listCreatures(kid.id);
		} catch {
			/* server unreachable: keep showing what we have */
		}
	}

	// Creatures still asleep on the hill wake up (and get their 3D badge) once the server is done.
	const stillSleeping = $derived(
		creatures.some((c) => c.jobs.some((j) => j.status === 'queued' || j.status === 'running'))
	);
	let poll: ReturnType<typeof setInterval> | undefined;
	$effect(() => {
		if (screen !== 'hill' || !stillSleeping) return;
		poll = setInterval(refresh, 4000);
		return () => clearInterval(poll);
	});

	onMount(async () => {
		try {
			kids = await listKids();
		} catch {
			kids = [];
		}
		if (kid) prefs.kidId = kid.id;
		await refresh();
	});
	onDestroy(() => clearInterval(poll));

	function pickKid(id: number) {
		if (prefs.kidId === id) return;
		prefs.kidId = id;
		sfx.pop();
		creatures = [];
		void refresh();
	}

	function takePhoto(p: Blob) {
		flashOn = false;
		requestAnimationFrame(() => (flashOn = true));
		photo = p;
		parent = false;
		screen = 'wake';
	}

	async function saved(id: number) {
		await refresh();
		hopId = id;
		screen = 'hill';
	}

	async function remove(id: number) {
		creatures = creatures.filter((c) => c.id !== id);
		await deleteCreature(id).catch(() => {});
	}
</script>

<div class="flash" class:on={flashOn} onanimationend={() => (flashOn = false)}></div>

{#if screen === 'hill'}
	<Hill
		{kids}
		{creatures}
		{hopId}
		bind:parent
		onpickkid={pickKid}
		onglass={() => (screen = 'lens')}
		onaddphoto={() => fileAny.click()}
		ondelete={remove}
		onpuff={(id) => {
			puffId = id;
			screen = 'puff';
		}}
	/>
{:else if screen === 'puff' && puffed}
	<Puff creature={puffed} onback={() => (screen = 'hill')} />
{:else if screen === 'lens' && kid}
	<Lens kidColor={kid.color} onphoto={takePhoto} onback={() => (screen = 'hill')} />
{:else if screen === 'wake' && kid && photo}
	<Wake
		kidId={kid.id}
		{photo}
		onsaved={saved}
		onleave={() => {
			screen = 'hill';
			void refresh();
		}}
		onretake={() => (screen = 'lens')}
	/>
{/if}

<input
	bind:this={fileAny}
	type="file"
	accept="image/*"
	hidden
	onchange={(e) => {
		const f = e.currentTarget.files?.[0];
		e.currentTarget.value = '';
		if (f) takePhoto(f);
	}}
/>
