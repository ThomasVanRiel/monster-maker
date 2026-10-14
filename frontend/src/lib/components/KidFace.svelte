<script lang="ts">
	// Simple faces so kids recognise "their" button without reading.
	let { index }: { index: number } = $props();
</script>

<svg viewBox="0 0 48 48" aria-hidden="true">
	<circle cx="17" cy="20" r="3.5" fill="#fff" /><circle cx="31" cy="20" r="3.5" fill="#fff" />
	{#if index % 3 === 0}
		<path d="M15 30 Q24 38 33 30" fill="none" stroke="#fff" stroke-width="4" stroke-linecap="round" />
	{:else if index % 3 === 1}
		<circle cx="24" cy="32" r="5" fill="none" stroke="#fff" stroke-width="4" />
	{:else}
		<path d="M16 32 H32" fill="none" stroke="#fff" stroke-width="4" stroke-linecap="round" />
	{/if}
</svg>
