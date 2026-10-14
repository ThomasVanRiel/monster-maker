// Client for the home server API (server/monster/api.py), served under /api.

export type Kid = { id: number; name: string; color: string };
export type Eye = { x: number; y: number; r: number };
export type JobStatus = 'queued' | 'running' | 'done' | 'failed' | 'waiting_for_gpu';
export type Job = { id: number; step: string; status: JobStatus; worker: 'cpu' | 'gpu'; attempts: number; error: string | null };
export type Creature = {
	id: number;
	kid_id: number;
	name: string | null;
	created_at: number;
	chosen_style: string | null;
	eyes: Eye[];
	files: Partial<Record<'photo' | 'cutout' | 'mask' | 'mesh_faithful' | 'print_3mf', string>>;
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
export const updateCreature = (id: number, patch: { name?: string; eyes?: Eye[] }) =>
	call<Creature>('PATCH', `/creatures/${id}`, patch);
export const deleteCreature = (id: number) => call<void>('DELETE', `/creatures/${id}`);

export function uploadPhoto(kidId: number, photo: Blob): Promise<Creature> {
	const form = new FormData();
	form.append('kid_id', String(kidId));
	form.append('photo', photo, 'drawing.jpg');
	return call<Creature>('POST', '/creatures', form);
}

/** Resolves when every job of the creature has finished (true) or one failed (false). */
export function whenJobsSettle(id: number): Promise<boolean> {
	return new Promise((resolve) => {
		const es = new EventSource(`/api/creatures/${id}/events`);
		let jobs: Job[] = [];
		es.addEventListener('jobs', (e) => (jobs = JSON.parse((e as MessageEvent).data)));
		es.addEventListener('end', () => {
			es.close();
			resolve(jobs.every((j) => j.status === 'done'));
		});
		// EventSource reconnects by itself on network hiccups; only give up if it is closed for good.
		es.onerror = () => {
			if (es.readyState === EventSource.CLOSED) resolve(false);
		};
	});
}
