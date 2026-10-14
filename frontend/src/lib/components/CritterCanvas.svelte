<script lang="ts">
	// A creature on the hill: loads its cutout and keeps a Critter animating it.
	import { onDestroy } from 'svelte';
	import { Critter } from '../critter';
	import type { Eye } from '../api';

	let { src, eyes, critter = $bindable() }: { src: string; eyes: Eye[]; critter?: Critter } = $props();
	let canvas: HTMLCanvasElement;

	$effect(() => {
		const im = new Image();
		let gone = false;
		im.src = src;
		im.decode()
			.catch(() => {})
			.then(() => {
				if (gone || !im.naturalWidth) return;
				critter?.destroy();
				critter = new Critter(canvas, im, { eyes });
			});
		return () => {
			gone = true;
		};
	});

	onDestroy(() => critter?.destroy());
</script>

<canvas bind:this={canvas}></canvas>

<style>
	canvas {
		display: block;
		width: var(--crit);
		height: var(--crit);
		position: relative;
	}
</style>
