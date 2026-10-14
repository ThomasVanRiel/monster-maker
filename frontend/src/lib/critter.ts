// The wobble / bounce / blink renderer, ported from prototype/index.html.
// The cutout is drawn in horizontal strips that sway more towards the top, breathes by
// squashing, and closes painted lids over the marked eyes (or squashes when it has none).
import type { Eye } from './api';

const reduce = typeof matchMedia !== 'undefined' && matchMedia('(prefers-reduced-motion: reduce)').matches;
const critters = new Set<Critter>();
const LID_FALLBACK = '#E9B98F';

export class Critter {
	c: HTMLCanvasElement;
	ctx: CanvasRenderingContext2D;
	img: HTMLImageElement;
	eyes: Eye[];
	sleeping: boolean;
	showEyes = false;
	phase = Math.random() * 6.28;
	speed = 1.5 + Math.random() * 0.8;
	nextBlink = performance.now() + 1200 + Math.random() * 3000;
	blinkStart = -1;
	iw: number;
	ih: number;
	lids: string[] = [];
	w = 1;
	h = 1;
	d = 1;
	s = 1;
	dw = 1;
	dh = 1;
	ox = 0;
	oy = 0;

	constructor(canvas: HTMLCanvasElement, img: HTMLImageElement, opts: { eyes?: Eye[]; sleeping?: boolean } = {}) {
		this.c = canvas;
		this.ctx = canvas.getContext('2d')!;
		this.img = img;
		this.eyes = opts.eyes ?? [];
		this.sleeping = !!opts.sleeping;
		this.iw = img.naturalWidth || img.width;
		this.ih = img.naturalHeight || img.height;
		this.lidColors();
		this.resize();
		critters.add(this);
		ensureLoop();
	}

	destroy() {
		critters.delete(this);
	}

	/** Lid colour = the drawing just above each eye. */
	lidColors() {
		const t = document.createElement('canvas');
		t.width = this.iw;
		t.height = this.ih;
		const x = t.getContext('2d', { willReadFrequently: true })!;
		x.drawImage(this.img, 0, 0);
		this.lids = this.eyes.map((e) => {
			const px = Math.round(e.x * this.iw);
			const py = Math.max(0, Math.round(e.y * this.ih - e.r * this.iw * 1.7));
			try {
				const d = x.getImageData(Math.min(this.iw - 1, px), Math.min(this.ih - 1, py), 1, 1).data;
				return d[3] < 128 ? LID_FALLBACK : `rgb(${d[0]},${d[1]},${d[2]})`;
			} catch {
				return LID_FALLBACK;
			}
		});
	}

	resize() {
		const r = this.c.getBoundingClientRect();
		const d = Math.min(window.devicePixelRatio || 1, 2);
		this.w = Math.max(1, r.width);
		this.h = Math.max(1, r.height);
		this.d = d;
		this.c.width = Math.round(this.w * d);
		this.c.height = Math.round(this.h * d);
		const m = 0.1;
		const sc = Math.min((this.w * (1 - 2 * m)) / this.iw, (this.h * (1 - m)) / this.ih);
		this.s = sc;
		this.dw = this.iw * sc;
		this.dh = this.ih * sc;
		this.ox = (this.w - this.dw) / 2;
		this.oy = this.h - this.dh - 2;
	}

	sway(t: number, fy: number, amp: number) {
		return Math.sin(t * this.speed + this.phase + fy * 2.2) * amp * (1 - fy);
	}

	/** Client coordinates -> position on the cutout (0..1). */
	toImage(clientX: number, clientY: number) {
		const r = this.c.getBoundingClientRect();
		return { x: (clientX - r.left - this.ox) / this.dw, y: (clientY - r.top - this.oy) / this.dh };
	}

	blinkNow() {
		this.blinkStart = -1;
		this.nextBlink = performance.now() + 120;
	}

	draw(now: number) {
		const { ctx, d, iw, ih } = this;
		ctx.setTransform(1, 0, 0, 1, 0, 0);
		ctx.clearRect(0, 0, this.c.width, this.c.height);
		const t = now / 1000;
		const awake = !this.sleeping;
		const amp = awake ? (reduce ? 0.012 : 0.045) * this.dw : 0;
		const br = awake
			? (reduce ? 0.008 : 0.03) * Math.sin(t * this.speed * 1.15 + this.phase)
			: 0.035 * Math.sin(t * 1.3);
		let lid = this.sleeping && this.eyes.length ? 1 : 0;
		if (awake) {
			if (this.blinkStart < 0 && now > this.nextBlink) this.blinkStart = now;
			if (this.blinkStart >= 0) {
				const p = (now - this.blinkStart) / 190;
				if (p >= 1) {
					this.blinkStart = -1;
					this.nextBlink = now + 2400 + Math.random() * 3600;
				} else lid = Math.sin(p * Math.PI);
			}
		}
		const squash = this.eyes.length ? 0 : lid * 0.06;
		const sx = 1 + br;
		const sy = 1 - br - squash;
		const cx = this.ox + this.dw / 2;
		const by = this.oy + this.dh;
		ctx.setTransform(d * sx, 0, 0, d * sy, d * (cx - cx * sx), d * (by - by * sy));
		const strip = Math.max(2, Math.round(ih / 90));
		for (let y = 0; y < ih; y += strip) {
			const shh = Math.min(strip + 1, ih - y);
			ctx.drawImage(this.img, 0, y, iw, shh, this.ox + this.sway(t, y / ih, amp), this.oy + y * this.s, this.dw, shh * this.s);
		}
		this.eyes.forEach((e, i) => {
			const X = this.ox + this.sway(t, e.y, amp) + e.x * this.dw;
			const Y = this.oy + e.y * this.dh;
			const R = e.r * this.dw * 1.15;
			if (lid > 0) {
				ctx.save();
				ctx.beginPath();
				ctx.arc(X, Y, R, 0, 6.2832);
				ctx.clip();
				ctx.fillStyle = this.lids[i] || LID_FALLBACK;
				ctx.fillRect(X - R, Y - R, 2 * R, 2 * R * lid);
				ctx.restore();
				if (lid > 0.55) {
					const ly = Y - R + 2 * R * lid;
					ctx.strokeStyle = '#2E2A3B';
					ctx.lineWidth = Math.max(2, R * 0.2);
					ctx.lineCap = 'round';
					ctx.beginPath();
					ctx.moveTo(X - R * 0.85, ly - R * 0.08);
					ctx.quadraticCurveTo(X, ly + R * 0.22, X + R * 0.85, ly - R * 0.08);
					ctx.stroke();
				}
			}
			if (this.showEyes) {
				ctx.save();
				ctx.setLineDash([5, 4]);
				ctx.strokeStyle = '#F5B83D';
				ctx.lineWidth = 4;
				ctx.beginPath();
				ctx.arc(X, Y, R + 4, 0, 6.2832);
				ctx.stroke();
				ctx.restore();
			}
		});
	}
}

let running = false;
function ensureLoop() {
	if (running) return;
	running = true;
	const loop = (now: number) => {
		for (const c of critters) {
			if (!c.c.isConnected) critters.delete(c);
			else if (c.c.getClientRects().length) c.draw(now);
		}
		if (critters.size) requestAnimationFrame(loop);
		else running = false;
	};
	requestAnimationFrame(loop);
}

if (typeof window !== 'undefined') {
	let t: ReturnType<typeof setTimeout>;
	addEventListener('resize', () => {
		clearTimeout(t);
		t = setTimeout(() => critters.forEach((c) => c.resize()), 150);
	});
}

/** Restart a CSS animation class (e.g. the hop) on an element. */
export function replay(el: HTMLElement | undefined, cls = 'hop') {
	if (!el) return;
	el.classList.remove(cls);
	void el.offsetWidth;
	el.classList.add(cls);
}
