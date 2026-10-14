# Monster Maker

Self-hosted family web app. Kids draw monsters **on paper**, a parent photographs the drawing with a tablet, and the app brings the creature to life: first as a wobbling, bouncing, blinking cutout on screen; later as a 3D model for AR and the home FDM printer.

Users are two young kids (under 5, and 5–8) who mostly can't read, plus a parent who drives the camera and settings. Family project, not a product.

More detail: `docs/plan.md` (architecture, pipeline, data model, GPU worker, risks) and `docs/kids-ui.md` (the chosen UI direction). The working UI prototype is `prototype/index.html`.

## Non-negotiables

- **Self-hosted only.** No drawing or photo ever goes to a cloud AI service or third-party API. Everything runs on the home server or the gaming PC.
- **Paper first.** Kids never draw in the app. The only in-app kid input is tapping the photo (rigging aids: eyes now; head, legs, hands, tail later).
- **Faithful to the drawing.** The result must still look like the kid's own drawing. Don't "improve" or restyle it. Later, AI-interpreted versions are offered *beside* the faithful one, never instead of it.
- **Kid UI has no text that matters.** Icons, big touch targets, colour and sound. Slow steps are friendly states ("your monster is sleeping"), never error messages. Destructive and technical actions live behind the hidden parent mode.

## Machines

| Machine | Role |
| --- | --- |
| Home server (always on) — Ryzen 5 5500GT, 16 GB RAM, Linux, no GPU | nginx (TLS, shared with other household services), Caddy (SPA + `/api`, HTTP on `127.0.0.1:8095`), FastAPI, SQLite, creature files, job queue, CPU worker |
| Gaming PC (only when idle) — Linux, RTX 4070 Ti Super 16 GB | GPU worker that **pulls** heavy AI jobs from the server; skips when a game is running. Not needed in Phase 1. |
| Tablet | Browser / PWA at the home server's HTTPS name (LAN-only, real certificate; the real name and addresses are in `CLAUDE.local.md`, which is gitignored). Camera needs HTTPS. |

## Development and deployment

Code is developed on several machines; none of them is the server. Git is the single source of truth.

- **One central remote** (private repo). Every dev machine clones it; commit small, push often, pull before starting. Never rely on files that exist on only one machine.
- **Images are built in CI, not on the servers.** On push to `main`, CI builds the images and pushes them to a private registry, tagged `:main` and `:<git sha>`.
- **Servers only pull.** The home server and the gaming PC have no source checkout. They hold a compose file plus a local `.env` (on the home server: `~/dockerfiles/monster-maker/`, alongside the other services), and update with `docker compose pull && docker compose up -d`. Roll back by pinning a `:<git sha>` tag. A changed `compose.yaml` has to be copied over by hand — `pull` only updates images.
- **Containers run unprivileged** as `PUID`/`PGID` (default 1000), which must own `DATA_DIR`, so the drawings stay readable without sudo.
- **Compose files:**
  - `compose.yaml` — home server: `image:` references only (api, cpu-worker, caddy). The vhost for the host's nginx is `deploy/nginx/monster.conf`.
  - `compose.gpu.yaml` — gaming PC: the GPU worker only (Phase 2+).
  - `compose.dev.yaml` — dev machines: `build:` from source with hot reload, local test data.
- **Config and secrets** go in a per-machine `.env` (gitignored); commit a `.env.example` listing every variable.
- **Data never leaves the home server.** `creatures/` and the SQLite file live in volumes there; they are never committed, baked into images or pushed to the registry. Dev machines use test fixtures.
- All machines are x86-64 Linux, so single-arch (`linux/amd64`) images are enough.

## Stack

- Python + FastAPI, SQLite (jobs table with leases as the queue; no Redis), server-sent events for progress.
- The home server's existing nginx terminates HTTPS (Let's Encrypt, LAN-restricted); Caddy inside the stack serves the SPA and routes `/api` over HTTP.
- Docker Compose for deployment.
- CPU steps: OpenCV, rembg (later trimesh / PyMeshLab).
- Frontend: tablet PWA in **SvelteKit** (Svelte 5 runes, static adapter as an SPA), package manager **pnpm**.
- Repo on **GitHub**; CI = GitHub Actions, registry = GHCR.
- Animation: canvas / PixiJS mesh warp of the cutout, in the browser.

## Data model

Kid → Creature (one per drawing) → Jobs (pipeline steps) → Artifacts (files).

- Kid: id, name, avatar colour
- Creature: id, kid_id, name, created_at, chosen_style
- Job: id, creature_id, step, status (`queued`, `running`, `done`, `failed`, `waiting_for_gpu`), worker (`cpu`/`gpu`), attempts, error, lease
- Artifact: id, creature_id, job_id, kind (`photo`, `cutout`, `mask`, later `mesh_faithful`, `mesh_ai`, `rig`, `anim`, `print_3mf`), path

Files live in `creatures/{id}/` (`drawing.jpg`, `cutout.png`, …). Backup = that folder + the SQLite file.

## Phase 1, Milestone 1 — "Alive on screen"

- [x] Docker Compose skeleton: FastAPI, SQLite, Caddy behind the host's nginx (`compose.yaml` + `compose.dev.yaml`, `deploy/nginx/monster.conf`) — deployed and serving on the LAN
- [x] CI: build images on push to `main` and push them to the registry; home server updates with `docker compose pull`
- [x] Tablet PWA: kid picker, take photo, gallery (Monster Hill) — no service worker / offline yet
- [x] Upload endpoint creating a creature and a cleanup job
- [x] Jobs table with leases and server-sent progress events
- [x] CPU worker: perspective crop, background removal, cutout and mask (`server/monster/steps/cleanup.py`)
- [x] Instant wobble, bounce and blink of the cutout in the browser
- [ ] Test with real drawings from the kids; note which ones fail — two fixtures so far (`monster-1`: shadow, outline gaps, faint strokes; `monster-2`: ruled pad, printed logos, wooden desk); both pass

## Phase 2 — 3D creatures

- [x] Faithful balloon 3D on the CPU: `balloon` step after `cleanup` → `faithful.glb` (artifact `mesh_faithful`); 3D badge on the hill opens a spinning `<model-viewer>` with AR (`Puff.svelte`, model-viewer bundled and lazy-loaded). Steps chain through `NEXT_STEPS` in `server/monster/steps/__init__.py`; the worker backfills missing follow-up steps for older creatures at start.
- [ ] GPU worker on the gaming PC (pull-based, game check)
- [ ] AI 3D (TRELLIS.2) beside the faithful one; kid picks

## Phase 3 — Print

- [x] `print_prep` CPU step after `cleanup` → `print.3mf` (artifact `print_3mf`) for the Prusa MK3S+ (single colour, 0.4 mm nozzle, PrusaSlicer): "standing" on an oval plinth and "lying" on a base plate, pen lines engraved. Download from parent mode. Meshes are checked and unioned with manifold3d.
- [ ] Test prints; tune engraving depth/width, plinth size and the 8 cm height

## The cutout (photo → sticker)

`server/monster/steps/cleanup.py` is a port of the prototype's `segment()` / `processPhoto()`, changed where real photos broke it:

1. Find the paper by growing it from a bright seed near the middle (small neighbour steps pass soft shading, the sheet's edge stops it) — Otsu split a half-shadowed sheet in two. Straighten it only when it is clearly a four-sided sheet; a wrong warp bends the drawing.
2. Even out lighting: per-block paper brightness (90th percentile), one max-spread pass, bilinear per pixel.
3. Ink = clearly darker than local paper, or clearly coloured; faint stretches count when they are thin (black-hat) and touch the dark ink.
4. Drop specks below a minimum area.
5. Close outline gaps with the smallest closing that encloses nearly as much as the widest, flood from the border, shrink back to the line. Keep the biggest shape plus pieces close to it: printed logos or headers elsewhere on the sheet are dropped.
6. White-balance against the paper per channel with a mild contrast curve; add a white "sticker" edge.
7. Fallback when nothing is found: a soft rounded window in the middle of the photo.

To tune: put photos in `tests/fixtures/` and run `uv run python scripts/cutout_debug.py ../tests/fixtures/*` in `server/` — it writes every stage side by side to `cutout-debug/`. Each fixture gets a test in `server/tests/test_cleanup.py`.

## Working conventions

- Keep the kid-facing look and behaviour of the prototype (Monster Hill, magnifying-glass camera, sleep → wake, tap-to-mark eyes) when rebuilding the UI in the real frontend.
- Prefer small, testable steps. Write tests for the cutout pipeline against real photos in `tests/fixtures/` once they exist.
- Don't add cloud services, analytics or external APIs. CDN fonts/libraries are OK only if they can be vendored for offline LAN use later.
- Avoid Hunyuan3D unless its licence is confirmed to cover Belgium.
