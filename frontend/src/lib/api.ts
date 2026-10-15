// Client for the home server API (server/monster/api.py), served under /api.

export type Kid = { id: number; name: string; color: string };
export type Eye = { x: number; y: number; r: number };
export type JobStatus = 'queued' | 'running' | 'done' | 'failed' | 'waiting_for_gpu';
export type Job = { id: number; step: string; status: JobStatus; worker: 'cpu' | 'gpu'; attempts: number; error: string | null };
export type Style = 'faithful' | 'ai';
/** What the AI version is made of (server/monster/steps/__init__.py, SKINS). */
export const SKINS = ['toy', 'fluffy', 'slimy', 'scaly', 'knitted', 'clay', 'candy', 'metal'] as const;
export type Skin = (typeof SKINS)[number];
export type Creature = {
	id: number;
	kid_id: number;
	name: string | null;
	created_at: number;
	chosen_style: Style | null;
	eyes: Eye[];
	rotation: number;
	skin: Skin;
	files: Partial<Record<'photo' | 'cutout' | 'mask' | 'creature' | 'mesh_faithful' | 'imagined' | 'mesh_ai' | 'print_3mf' | 'print_ai_3mf', string>>;
	jobs: Job[];
};

async function call<T>(method: string, path: string, body?: BodyInit | object): Promise<T> {
	const init: RequestInit = { method };
	if (body instanceof FormData || body instanceof Blob) init.body = body;
	else if (body !== undefined) {
		init.body = JSON.stringify(body);
		init.headers = { 'content-type': 'application/json' };
	}
	const res = await fetch('/api' + path, init);
	if (!res.ok) throw new Error(`${method} ${path}: ${res.status}`);
	return (res.status === 204 ? undefined : await res.json()) as T;
}

export const listKids = () => call<Kid[]>('GET', '/kids');
export const listCreatures = (kidId: number) => call<Creature[]>('GET', `/creatures?kid_id=${kidId}`);
export const getCreature = (id: number) => call<Creature>('GET', `/creatures/${id}`);
export const updateCreature = (id: number, patch: { name?: string; eyes?: Eye[]; chosen_style?: Style; skin?: Skin }) =>
	call<Creature>('PATCH', `/creatures/${id}`, patch);
export const deleteCreature = (id: number) => call<void>('DELETE', `/creatures/${id}`);
/** The gaming PC that makes the AI 3D versions: is it around, and how much waits for it. */
export type GpuStatus = {
	enabled: boolean;
	waiting: number;
	running: number;
	workers: { id: string; state: string; detail: string | null; last_seen: number }[];
	now: number;
};
export const getGpu = () => call<GpuStatus>('GET', '/gpu');

/** Turn a sideways drawing a quarter turn clockwise (the server redoes 3D and print). */
export const rotateCreature = (id: number) => call<Creature>('POST', `/creatures/${id}/rotate`, { turns: 1 });

/** Eye marks after turning a w x h cutout a quarter turn clockwise (same as the server). */
export const rotateEyes = (eyes: Eye[], w: number, h: number): Eye[] =>
	eyes.map((e) => ({ x: 1 - e.y, y: e.x, r: (e.r * w) / h }));

export function uploadPhoto(kidId: number, photo: Blob): Promise<Creature> {
	const form = new FormData();
	form.append('kid_id', String(kidId));
	form.append('photo', photo, 'drawing.jpg');
	return call<Creature>('POST', '/creatures', form);
}

/** Resolves when the creature's `step` job has finished (true) or failed (false). Later steps
 *  (3D, print) keep running on the server; nobody has to wait for them. */
export function whenStepSettles(id: number, step = 'cleanup'): Promise<boolean> {
	return new Promise((resolve) => {
		const es = new EventSource(`/api/creatures/${id}/events`);
		const done = (ok: boolean) => {
			es.close();
			resolve(ok);
		};
		es.addEventListener('jobs', (e) => {
			const job = (JSON.parse((e as MessageEvent).data) as Job[]).find((j) => j.step === step);
			if (job?.status === 'done') done(true);
			else if (job?.status === 'failed') done(false);
		});
		es.addEventListener('end', () => done(false)); // everything settled without that step
		// EventSource reconnects by itself on network hiccups; only give up if it is closed for good.
		es.onerror = () => {
			if (es.readyState === EventSource.CLOSED) resolve(false);
		};
	});
}
