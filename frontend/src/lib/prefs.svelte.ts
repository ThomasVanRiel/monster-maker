// Per-tablet settings, kept in localStorage: which kid is playing and whether sound is on.

const KEY = 'monsterHill.prefs.v1';

function load(): { kidId: number | null; sound: boolean } {
	try {
		const s = JSON.parse(localStorage.getItem(KEY) ?? '{}');
		return { kidId: typeof s.kidId === 'number' ? s.kidId : null, sound: s.sound !== false };
	} catch {
		return { kidId: null, sound: true };
	}
}

export const prefs = $state(load());

$effect.root(() => {
	$effect(() => {
		try {
			localStorage.setItem(KEY, JSON.stringify({ kidId: prefs.kidId, sound: prefs.sound }));
		} catch {
			/* private mode: settings just won't stick */
		}
	});
});
