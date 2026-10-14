// Little synthesised sounds (no audio files), as in the prototype.
import { prefs } from './prefs.svelte';

let ac: AudioContext | null = null;

function audio(): AudioContext | null {
	if (!prefs.sound) return null;
	try {
		ac ??= new AudioContext();
		if (ac.state === 'suspended') void ac.resume();
	} catch {
		ac = null;
	}
	return ac;
}

function tone(type: OscillatorType, f0: number, f1: number, dur: number, vol: number, when = 0) {
	const a = audio();
	if (!a) return;
	const t = a.currentTime + when;
	const o = a.createOscillator();
	const g = a.createGain();
	o.type = type;
	o.frequency.setValueAtTime(f0, t);
	o.frequency.exponentialRampToValueAtTime(f1, t + dur);
	g.gain.setValueAtTime(0.0001, t);
	g.gain.exponentialRampToValueAtTime(vol, t + 0.02);
	g.gain.exponentialRampToValueAtTime(0.0001, t + dur);
	o.connect(g).connect(a.destination);
	o.start(t);
	o.stop(t + dur + 0.05);
}

import type { Skin } from './api';

// One little sound per material, played when the kid picks it.
const SKIN_SOUNDS: Record<Skin, () => void> = {
	toy: () => tone('sine', 900, 1500, 0.12, 0.2), // squeak
	fluffy: () => tone('sine', 420, 260, 0.25, 0.12), // soft puff
	slimy: () => {
		tone('sine', 420, 70, 0.35, 0.3); // squelch
		tone('sine', 180, 60, 0.3, 0.2, 0.08);
	},
	scaly: () => [0, 0.05, 0.1, 0.15].forEach((t) => tone('square', 1800, 900, 0.03, 0.06, t)), // rattle
	knitted: () => [0, 0.12].forEach((t) => tone('triangle', 700, 650, 0.08, 0.12, t)), // click-clack
	clay: () => tone('sine', 200, 55, 0.22, 0.35), // thud
	candy: () => [1319, 1568, 2093].forEach((f, i) => tone('triangle', f, f, 0.15, 0.12, i * 0.07)), // sparkle
	metal: () => {
		tone('square', 880, 860, 0.4, 0.08); // clang
		tone('triangle', 1320, 1300, 0.5, 0.1);
	}
};

export const sfx = {
	skin(skin: Skin) {
		SKIN_SOUNDS[skin]();
	},
	boing() {
		tone('sine', 160, 520, 0.16, 0.3);
		tone('sine', 520, 230, 0.26, 0.22, 0.14);
	},
	click() {
		tone('square', 1200, 300, 0.07, 0.12);
	},
	tada() {
		[523, 659, 784, 1047].forEach((f, i) => tone('triangle', f, f * 1.001, 0.28, 0.2, i * 0.11));
	},
	pop() {
		tone('sine', 300, 900, 0.1, 0.22);
	},
	snore() {
		tone('sawtooth', 90, 70, 0.7, 0.05);
	}
};
