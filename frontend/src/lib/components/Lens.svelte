<script lang="ts">
	// The magic glass: live camera framed in a big lens. The lens is framing only — the full
	// frame is sent to the server, which crops to the paper. Without a live camera (no HTTPS,
	// no permission) the red button opens the tablet's own camera app instead.
	import { onDestroy, onMount } from 'svelte';
	import { sfx } from '../sfx';

	let { kidColor, onphoto, onback }: { kidColor: string; onphoto: (photo: Blob) => void; onback: () => void } =
		$props();

	let video: HTMLVideoElement;
	let fileCam: HTMLInputElement;
	let fileAny: HTMLInputElement;
	let stream: MediaStream | null = null;
	let noCam = $state(false);
	let gone = false;

	onMount(async () => {
		if (!navigator.mediaDevices?.getUserMedia) {
			noCam = true;
			return;
		}
		try {
			const s = await navigator.mediaDevices.getUserMedia({
				video: { facingMode: { ideal: 'environment' }, width: { ideal: 1920 }, height: { ideal: 1440 } },
				audio: false
			});
			if (gone) {
				s.getTracks().forEach((t) => t.stop());
				return;
			}
			stream = s;
			video.srcObject = s;
			await video.play().catch(() => {});
		} catch {
			noCam = true;
		}
	});

	function stopCam() {
		stream?.getTracks().forEach((t) => t.stop());
		stream = null;
	}

	onDestroy(() => {
		gone = true;
		stopCam();
	});

	function shoot() {
		sfx.click();
		if (!stream || !video.videoWidth) {
			fileCam.click();
			return;
		}
		const c = document.createElement('canvas');
		c.width = video.videoWidth;
		c.height = video.videoHeight;
		c.getContext('2d')!.drawImage(video, 0, 0);
		stopCam();
		c.toBlob((b) => b && onphoto(b), 'image/jpeg', 0.92);
	}

	function fromFile(input: HTMLInputElement) {
		const f = input.files?.[0];
		input.value = '';
		if (f) onphoto(f);
	}
</script>

<section class="screen lensScreen" aria-label="Magic glass camera">
	<div class="lensWrap">
		<div class="lensGlass">
			<!-- svelte-ignore a11y_media_has_caption -->
			<video bind:this={video} playsinline muted autoplay hidden={noCam}></video>
			{#if noCam}
				<div class="nocam">
					<svg
						viewBox="0 0 24 24"
						fill="none"
						stroke="#FFFFFF"
						stroke-width="1.6"
						stroke-linecap="round"
						stroke-linejoin="round"
						aria-hidden="true"
						><path d="M4 8h3l2-3h6l2 3h3a1 1 0 0 1 1 1v10a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V9a1 1 0 0 1 1-1z" /><circle
							cx="12"
							cy="14"
							r="4"
						/></svg
					>
				</div>
			{/if}
		</div>
		<div class="handle" aria-hidden="true"></div>
		<div class="rim" aria-hidden="true"></div>
		<div class="glint" aria-hidden="true"></div>
	</div>
	<button class="round tl" type="button" aria-label="Back to the hill" onclick={onback}>
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
	<div class="kidDot" style:background={kidColor} aria-hidden="true"></div>
	<p class="pill">{noCam ? 'The red button opens the camera' : 'Fit the paper inside the glass'}</p>
	<button class="shutter" type="button" aria-label="Take the photo" onclick={shoot}></button>
	<button class="fromPhotos" type="button" aria-label="Choose a photo from the tablet" onclick={() => fileAny.click()}>
		<svg
			viewBox="0 0 24 24"
			fill="none"
			stroke="#FFFFFF"
			stroke-width="2"
			stroke-linecap="round"
			stroke-linejoin="round"
			aria-hidden="true"><rect x="3" y="4" width="18" height="16" rx="2" /><circle cx="9" cy="10" r="2" /><path d="M21 16l-5-5-9 9" /></svg
		>
	</button>
	<input bind:this={fileCam} type="file" accept="image/*" capture="environment" hidden onchange={(e) => fromFile(e.currentTarget)} />
	<input bind:this={fileAny} type="file" accept="image/*" hidden onchange={(e) => fromFile(e.currentTarget)} />
</section>

<style>
	.lensScreen {
		background: #1e1c26;
		--L: min(84vmin, 760px);
	}
	.lensWrap {
		position: absolute;
		width: var(--L);
		height: var(--L);
		left: calc(45% - var(--L) / 2);
		top: calc(50% - var(--L) / 2);
	}
	.lensGlass {
		position: absolute;
		inset: 0;
		border-radius: 50%;
		overflow: hidden;
		background: #3a3640;
	}
	.lensGlass video {
		width: 100%;
		height: 100%;
		object-fit: cover;
		display: block;
	}
	.nocam {
		position: absolute;
		inset: 0;
		display: grid;
		place-items: center;
	}
	.nocam svg {
		width: 34%;
		height: 34%;
		opacity: 0.55;
	}
	.rim {
		position: absolute;
		inset: 0;
		border-radius: 50%;
		border: calc(var(--L) * 0.04) solid var(--brass);
		box-shadow:
			0 0 0 6px var(--ink),
			0 0 0 200vmax rgba(30, 28, 38, 0.88),
			inset 0 0 0 6px var(--ink);
		pointer-events: none;
		z-index: 1;
	}
	.handle {
		position: absolute;
		left: 85%;
		top: 85%;
		width: calc(var(--L) * 0.4);
		height: calc(var(--L) * 0.1);
		background: var(--wood);
		border: 6px solid var(--ink);
		border-radius: 999px;
		transform: rotate(45deg);
		transform-origin: 0 50%;
		z-index: 2;
	}
	.glint {
		position: absolute;
		left: 14%;
		top: 12%;
		width: 16%;
		height: 5%;
		border-radius: 999px;
		background: var(--paper);
		opacity: 0.5;
		transform: rotate(-38deg);
		z-index: 2;
		pointer-events: none;
	}
	.pill {
		position: absolute;
		top: calc(20px + env(safe-area-inset-top, 0px));
		right: calc(20px + env(safe-area-inset-right, 0px));
		margin: 0;
		background: #14301e;
		color: var(--found);
		border-radius: 999px;
		padding: 8px 18px;
		font-size: clamp(15px, 2.4vmin, 20px);
		font-weight: 600;
		z-index: 3;
		max-width: 40vw;
	}
	.kidDot {
		position: absolute;
		top: calc(116px + env(safe-area-inset-top, 0px));
		left: calc(28px + env(safe-area-inset-left, 0px));
		width: 56px;
		height: 56px;
		border-radius: 50%;
		border: 4px solid var(--paper);
		z-index: 3;
	}
	.shutter {
		position: absolute;
		right: calc(40px + env(safe-area-inset-right, 0px));
		top: 50%;
		translate: 0 -50%;
		width: clamp(120px, 20vmin, 180px);
		aspect-ratio: 1;
		border-radius: 50%;
		background: var(--go);
		border: 12px solid var(--paper);
		box-shadow: 0 0 0 8px rgba(255, 255, 255, 0.22);
		cursor: pointer;
		padding: 0;
		z-index: 3;
		animation: pulse 1.6s ease-in-out infinite;
	}
	.shutter:active {
		transform: scale(0.92);
	}
	.fromPhotos {
		position: absolute;
		left: calc(24px + env(safe-area-inset-left, 0px));
		bottom: calc(24px + env(safe-area-inset-bottom, 0px));
		width: 64px;
		height: 64px;
		border-radius: 18px;
		background: rgba(255, 255, 255, 0.16);
		border: 0;
		display: grid;
		place-items: center;
		cursor: pointer;
		z-index: 3;
	}
	.fromPhotos svg {
		width: 30px;
		height: 30px;
	}
	@media (orientation: portrait) {
		.lensScreen {
			--L: min(88vw, 60vh);
		}
		.lensWrap {
			left: calc(50% - var(--L) / 2);
			top: calc(42% - var(--L) / 2);
		}
		.shutter {
			right: auto;
			left: 50%;
			top: auto;
			bottom: calc(28px + env(safe-area-inset-bottom, 0px));
			translate: -50% 0;
		}
		.handle {
			width: calc(var(--L) * 0.26);
		}
	}
	@media (prefers-reduced-motion: reduce) {
		.shutter {
			animation: none;
		}
	}
</style>
