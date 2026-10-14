# Monster Maker

Kids draw monsters on paper; a parent photographs them with the tablet; the home server cuts them out and they come alive on screen, puff up in 3D, step into the room in AR and come out of the 3D printer. Fully self-hosted.

<p align="center">
  <img src="tests/fixtures/monster-1.jpeg" alt="The starting point: a photo of a pen drawing on paper, a figure with spiky hair, two small eyes, outstretched arms and two legs, with a shadow across the left of the sheet" width="200">
  <img src=".github/assets/screenshot-1.jpeg" alt="Monster Hill on the tablet: a kid's drawing, cut out as a sticker and named Marvin, stands on a green hill under a sunny sky, with kid avatars top-left, the parent lock top-right and the magnifying-glass camera button bottom-right" width="200">
  <img src=".github/assets/screenshot-2.jpeg" alt="Marvin in 3D: the same drawing puffed up like a soft balloon, the kid's pen line still on it, turning above the hill, with a back button top-left and a red AR button bottom-right" width="200">
  <img src=".github/assets/screenshot-3.jpeg" alt="Marvin in AR: the puffy 3D monster standing on a tiled floor between office chairs, seen through the phone camera" width="200">
</p>
<p align="center"><em>The photo of the drawing · on the hill · the faithful 3D balloon · in the room with AR</em></p>

- `CLAUDE.md` — project context for Claude Code (read automatically each session)
- `docs/plan.md` — full plan: architecture, pipeline, data model, phases, risks
- `docs/kids-ui.md` — the chosen kids UI ("Monster Hill")
- `prototype/` — working single-page UI prototype

## How the machines fit together

```
dev machine A ─┐
dev machine B ─┼─ git push ──► central repo ──► CI builds images ──► registry
dev machine C ─┘                                                      │
                                         docker compose pull ◄────────┤
                                         home server (compose.yaml)   │
                                                                      │
                                         docker compose pull ◄────────┘
                                         gaming PC (compose.gpu.yaml, Phase 2+)
```

- **Develop:** clone the repo on any dev machine, run `claude` in it. `CLAUDE.md` comes along with the repo, so every machine gets the same context. Pull before you start, push when you stop.
- **Deploy:** on the home server, `docker compose pull && docker compose up -d`. To roll back, set the image tag to an earlier git sha.
- **Data:** kids' drawings and the database stay on the home server only. They are never committed or put into images.

## Layout

- `server/` — Python package `monster`: FastAPI app (`api.py`), SQLite job queue with leases (`jobs.py`), CPU worker (`worker.py`), pipeline steps (`steps/`). One image runs both the API and the worker.
- `frontend/` — tablet PWA, SvelteKit (static SPA, pnpm). Screens: `Hill`, `Lens` (camera), `Wake` (sleep → wake, eyes, name), `Puff` (3D + AR); renderer in `src/lib/critter.ts`.
- `web/` — Caddy config and image (serves the built frontend over HTTP, proxies `/api`); the host's nginx terminates TLS in front of it. `Caddyfile.dev` proxies to the Vite dev server instead.
- `compose.yaml` (home server, images only) · `compose.dev.yaml` (dev, build + hot reload) · `.env.example` · `deploy/nginx/monster.conf` (home server vhost).

## Dev quick start

```
cd server && uv sync && uv run pytest            # backend tests
cd frontend && pnpm install && pnpm check        # frontend type check
docker compose -f compose.dev.yaml up --build    # full stack with hot reload at http://localhost:8099
```

Without Docker, three terminals: in `server/`, `MONSTER_DATA_DIR=../data uv run uvicorn monster.api:app --reload` and `MONSTER_DATA_DIR=../data uv run python -m monster.worker`; in `frontend/`, `pnpm dev` (proxies `/api` to port 8000). The live camera needs HTTPS (or localhost, which browsers treat as a secure context); otherwise the red button falls back to the tablet's camera app.

## AR support

The AR button on the 3D screen only appears when `<model-viewer>` finds a way into AR on the device; otherwise the monster still spins in 3D.

| Device | AR route | Notes |
| --- | --- | --- |
| iPhone / iPad, Safari | Apple AR Quick Look (model converted to USDZ in the browser) | Not when the app is opened from a home-screen icon: iOS disables Quick Look there, so open it in Safari itself. Other iOS browsers may not offer it. |
| Android, Chrome or Samsung Internet | Google Scene Viewer, or WebXR in Chrome | Needs Google Play Services for AR (ARCore), which [not every phone supports](https://developers.google.com/ar/devices). Scene Viewer is a Google app on the device that downloads the model straight from the home server; to keep AR inside the browser only, drop `scene-viewer` from `ar-modes` in `Puff.svelte` (fewer phones will then offer AR). |
| Android Firefox, desktop browsers | none | 3D only. |

The model is about 20 cm tall in AR and stands on the floor or table it is placed on.

## 3D printing

Every monster also gets a `print.3mf` (parent mode → the dark printer button on the monster). It holds two versions side by side; delete the one you don't want in the slicer:

- **standing** — the whole balloon, 8 cm tall, feet sunk into an oval plinth. The arms usually need supports.
- **lying** — the front half on a 1.6 mm base plate, printed on its back. No supports, sturdiest for small hands.

<p align="center">
  <img src=".github/assets/screenshot-4.png" alt="Both print versions of Marvin sliced in PrusaSlicer: on the left the standing one on its oval plinth, on the right the lying one on its base plate, with the drawn lines engraved into the surface" width="500">
</p>

Tuned for a single-colour FDM printer with a 0.4 mm nozzle (Prusa MK3S+ with PrusaSlicer): the drawing's pen lines are engraved 0.6 mm deep and widened to about 1 mm so the nozzle can draw them. Sizes and depths are constants at the top of `server/monster/steps/print_prep.py`.

## Deploy

CI (`.github/workflows/build.yml`) tests and builds `monster-maker-api` and `monster-maker-web` on every push to `main` and pushes them to GHCR. The home server keeps no checkout: it has a directory (`~/dockerfiles/monster-maker/`) holding `compose.yaml`, `.env` and `data/`, and updates with `docker compose pull && docker compose up -d`. Set `REGISTRY=ghcr.io/<user>` in `.env` and `docker login ghcr.io` once with a classic PAT scoped `read:packages`. When `compose.yaml` changes in the repo, copy it over again — `pull` only updates images.

Containers run unprivileged as `PUID`/`PGID` (default 1000), which must own `DATA_DIR`, so `creatures/` and the SQLite file stay readable and backup-able without sudo. Create `DATA_DIR` before the first start: a bind-mount target that Docker has to create itself lands as root, and the containers then cannot write to it.

The home server already runs nginx on 80/443 for the other household services, so the web container listens on `127.0.0.1:8095` (`WEB_HOST_BIND`/`WEB_HOST_PORT`) and nginx terminates TLS in front of it. Install `deploy/nginx/monster.conf` once — it is a template for `monster.example.com` (the header shows how to install it under your own name) with a Let's Encrypt certificate (so nothing to install on the tablet) and restricts access to the LAN, since the app has no login of its own. Setup steps are in the file's header.

First prompt suggestion: "Read CLAUDE.md and the prototype, then propose a plan for Milestone 1." Use plan mode for the first pass.
