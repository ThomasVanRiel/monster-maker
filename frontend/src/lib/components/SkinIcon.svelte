<script lang="ts">
	// A swatch of what the AI version is made of: no words, a little picture of the material.
	import type { Skin } from '../api';

	let { skin }: { skin: Skin } = $props();
	const clip = $props.id(); // several swatches on screen: each needs its own clip path id
	// the fur's edge: 18 soft bumps around a ball
	const fur = Array.from({ length: 18 }, (_, i) => {
		const a = (i / 18) * Math.PI * 2;
		return [24 + 15 * Math.cos(a), 25 + 15 * Math.sin(a)];
	});
</script>

<svg viewBox="0 0 48 48" aria-hidden="true" stroke="#2E2A3B" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
	{#if skin === 'toy'}
		<!-- a glossy vinyl ball -->
		<circle cx="24" cy="25" r="17" fill="#FF5A3C" />
		<ellipse cx="18" cy="18" rx="6" ry="4" fill="#fff" stroke="none" opacity="0.85" transform="rotate(-30 18 18)" />
		<circle cx="29" cy="14" r="1.8" fill="#fff" stroke="none" />
	{:else if skin === 'fluffy'}
		<!-- a fuzzy puffball -->
		<g fill="#F5B83D">
			{#each fur as [x, y], i (i)}
				<circle cx={x} cy={y} r="5" />
			{/each}
		</g>
		<circle cx="24" cy="25" r="15" fill="#F5B83D" stroke="none" />
		<g fill="none" stroke-width="2" opacity="0.6">
			<path d="M17 21 q2 -3 4 -1 M26 18 q2 -3 4 -1 M22 29 q2 -3 4 -1 M30 27 q2 -3 4 -1 M14 30 q2 -3 4 -1" />
		</g>
	{:else if skin === 'slimy'}
		<!-- a dripping blob of slime -->
		<path
			fill="#7CF29A"
			d="M8 22 C8 10 40 10 40 22 C40 27 38 28 38 33 C38 37 34 37 34 33 C34 30 31 29 30 32 L30 40 C30 44 25 44 25 40 L25 33 C25 30 21 30 20 33 C19 36 15 36 15 32 C15 28 8 29 8 22 Z"
		/>
		<ellipse cx="18" cy="18" rx="4" ry="2.5" fill="#fff" stroke="none" opacity="0.8" />
	{:else if skin === 'scaly'}
		<!-- overlapping dragon scales -->
		<clipPath id="{clip}-c"><circle cx="24" cy="24" r="18" /></clipPath>
		<circle cx="24" cy="24" r="18" fill="#2F9E52" />
		<g clip-path="url(#{clip}-c)" fill="#8CCB6E" stroke-width="2">
			{#each [12, 21, 30, 39] as y, row (y)}
				{#each [0, 1, 2, 3, 4] as k (k)}
					<path d="M{k * 10 - (row % 2) * 5} {y} a5 5 0 0 0 10 0" />
				{/each}
			{/each}
		</g>
		<circle cx="24" cy="24" r="18" fill="none" />
	{:else if skin === 'knitted'}
		<!-- a ball of wool with a loose end -->
		<path fill="none" d="M34 36 C40 42 44 40 45 44" />
		<circle cx="23" cy="23" r="16" fill="#F49AC1" />
		<g fill="none" stroke-width="2">
			<path d="M10 16 C18 22 26 32 30 38" />
			<path d="M14 10 C22 18 32 26 37 30" />
			<path d="M8 26 C14 18 26 10 34 10" />
			<path d="M11 33 C18 26 30 18 38 19" />
		</g>
		<circle cx="23" cy="23" r="16" fill="none" />
	{:else if skin === 'clay'}
		<!-- a lumpy lump of clay with a thumbprint -->
		<path fill="#E07A4F" d="M10 30 C6 20 14 8 25 9 C36 10 43 18 40 29 C38 38 30 41 22 40 C15 39 12 35 10 30 Z" />
		<g fill="none" stroke-width="1.8" opacity="0.7">
			<path d="M20 20 q6 -4 11 1" />
			<path d="M19 25 q7 -5 13 1" />
			<path d="M20 30 q6 -3 10 1" />
		</g>
	{:else if skin === 'candy'}
		<!-- a lollipop swirl -->
		<path d="M24 38 L24 46" stroke-width="4" />
		<clipPath id="{clip}-c"><circle cx="24" cy="21" r="16" /></clipPath>
		<circle cx="24" cy="21" r="16" fill="#fff" />
		<path
			clip-path="url(#{clip}-c)"
			fill="none"
			stroke="#FF5A3C"
			stroke-width="4"
			d="M24 21 m0 -2 a2 2 0 1 1 -2 3 a5 5 0 1 1 8 -4 a9 9 0 1 1 -14 7 a13 13 0 1 1 20 -9"
		/>
		<circle cx="24" cy="21" r="16" fill="none" />
	{:else if skin === 'metal'}
		<!-- a riveted metal plate with a shine -->
		<rect x="7" y="7" width="34" height="34" rx="7" fill="#A9B4C2" />
		<path d="M12 33 L33 12 M18 37 L37 18" stroke="#fff" stroke-width="3" opacity="0.8" />
		{#each [[13, 13], [35, 13], [13, 35], [35, 35]] as [x, y] (x * 100 + y)}
			<circle cx={x} cy={y} r="2.2" fill="#5B6B7D" stroke-width="1.5" />
		{/each}
	{/if}
</svg>

<style>
	svg {
		width: 100%;
		height: 100%;
		display: block;
	}
</style>
