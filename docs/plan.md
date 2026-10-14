# Monster Maker – Project Plan

Oct 13, 2026

## Vision and goals

A self-hosted family web app where kids photograph a drawing of a monster or character and watch it come alive: animated on screen first, then as a 3D model they can see in AR and print on the home FDM printer.

- **Users:** kids under 5 and 5–8. A parent drives the app; the kid draws, watches and picks.
- **Scope:** family project first. Landscapes and game worlds come later.
- **Core principle:** the result must still look like *their* drawing. Offer both a faithful version and an AI-interpreted one and let the kid choose until the preferred style is clear.
- **Constraint:** everything runs on home hardware. No kids' drawings go to cloud AI services.
- **First output:** animation on screen. 3D print, AR and game world follow from the same 3D model.

**Paper first.** Drawing always happens on paper. The only in-app input is optional rigging aids: the kid taps the photo to mark head, legs, hands and tail. These marks guide Animated Drawings and UniRig, and can rescue monsters the AI can't read.

## Prior art

Every piece exists somewhere, but no product combines self-hosted, faithful-to-the-drawing, and one 3D model feeding animation, AR and print.

| Product | What it does | Gap for us |
| --- | --- | --- |
| [Meta Animated Drawings](https://about.fb.com/news/2021/12/using-ai-to-animate-childrens-drawings/) | Open-source 2D animation of kids' drawings, \~180k-drawing dataset | Human-shaped figures only; 2D |
| [Drawings Alive](https://drawingsalive.com/animate-kids-drawings) | Cloud app: AI videos, 3D models (.glb, .usdz) for AR | Cloud, paid, reimagines the drawing |
| [Bambu PrintMon Maker](https://all3dp.com/4/bambu-lab-launches-ai-powered-printmon-maker-tool-on-makerworld/) and [MakerWorld Image-to-3D (Meshy)](https://3dprintingindustry.com/news/meshy-and-makerworld-team-up-to-put-ai-3d-model-generation-in-bambu-lab-users-hands-250281/) | Image to printable figurine, STL/3MF | Cloud; stylises into a generic creature |
| [Crayon Creatures](https://waag.org/en/article/childs-drawing-3d-print/), [Kids Creation Station](https://3dprint.com/26806/kids-creation-station-3d-print/) | Hand-modelled prints of kids' drawings, about €100 each | Manual, slow; proves parents value it |
| [Quiver](https://apps.apple.com/us/app/-/id650645305) | AR colouring: coloured template pages come alive | Only works with its own printed pages |
| Monster Mash (Google research, from memory) | Sketch-based inflation and animation of casual characters | Worth checking as the basis for faithful 3D |

**Our angle:** a faithful "balloon" 3D mode, animation for non-humanoid monsters, and print prep tuned for FDM and small hands.

## Architecture

The home server is the always-on brain; the gaming PC is borrowed muscle that pulls GPU jobs when nobody is gaming.

```
Tablet (PWA, browser)
   │  HTTPS (Caddy, LAN only)
   ▼
Home server — always on (Ryzen 5 5500GT, 16 GB)
   Caddy · FastAPI · SQLite · creatures/{id}/ files · jobs queue
   CPU worker: photo cleanup, cutout, balloon 3D, print prep
   ▲
   │  pulls GPU jobs over LAN (GET /jobs/next?worker=gpu), only when idle
Gaming PC — part-time (RTX 4070 Ti Super, 16 GB)
   GPU worker: TRELLIS.2, UniRig, Animated Drawings
```

The tablet only talks to the home server. Faithful 3D and print files work with the PC switched off; only the AI steps wait for it.

## Pipeline and output tiers

One photo becomes a cleaned cutout, and every output branches from it; the two 3D versions meet at the kid's choice before rigging, viewing and printing.

```
photo ──► cleanup + cutout (CPU, seconds) ──┬──► wobble / bounce / blink in browser   (Phase 1)
                                            ├──► faithful balloon 3D (CPU, ~1 min) ─┐
                                            ├──► AI 3D, TRELLIS.2 (GPU, when free) ─┴─► kid picks ─┬─► 3D viewer + AR   (Phase 2)
                                            │                                                       ├─► print prep → 3MF (Phase 3)
                                            │                                                       └─► rig + motions     (Phase 4)
                                            └──► 2D dance, Animated Drawings (GPU, humanoid figures only)
```

The wobble appears in seconds so young kids never wait on an empty screen; faithful 3D and print files take about a minute on the server; AI 3D, rigging and the 2D dance wait until the PC is free.

## Data model

Everything hangs off a **creature**; each pipeline step is a **job** that adds an **artifact** to it. SQLite holds the records, plain folders hold the files.

| Entity | Key fields | Notes |
| --- | --- | --- |
| Kid | id, name, avatar colour | Gallery is filtered per kid |
| Creature | id, kid\_id, name, created\_at, chosen\_style | One per drawing; the kid names it |
| Job | id, creature\_id, step, status, worker (cpu/gpu), attempts, error | Status: queued, running, done, failed, waiting\_for\_gpu |
| Artifact | id, creature\_id, job\_id, kind, path | Kinds: photo, cutout, mask, mesh\_faithful, mesh\_ai, rig, anim, print\_3mf |

Files live at `creatures/{id}/` (`drawing.jpg`, `cutout.png`, `faithful.glb`, `ai.glb`, `rigged.glb`, `print.3mf`). Backing up is copying one folder plus the database. A **World** entity for landscapes is added in a later phase.

## GPU worker behaviour

The gaming PC never serves anything; it borrows work from the home server only when it is idle, and can vanish mid-job without breaking anything.

1. **Pull, don't push.** The worker polls `GET /jobs/next?worker=gpu` over the LAN, downloads inputs, runs the step, uploads the artifact, and asks again. No shared drives, no open ports on the PC.
2. **Game check before every job.** Skip polling when `nvidia-smi` shows a game process or VRAM use above a threshold (e.g. 2 GB). A job never starts mid-game.
3. **Quiet hours as a backup.** A configurable window, e.g. only run 08:00–18:00 on weekdays.
4. **One model at a time.** Each model loads, runs, and frees the GPU. This keeps peak use within the 16 GB of the RTX 4070 Ti Super.
5. **Resumable steps.** Each step saves its own artifact. A job that disappears gets requeued after a lease timeout (e.g. 10 minutes) and resumes from the last finished step.
6. **Lifecycle.** A systemd service starts the worker on boot; it stops cleanly on SIGTERM and returns its job to the queue.
7. **Optional wake-on-LAN.** A parent-mode button on the server wakes the PC when jobs are waiting.

The tablet shows waiting GPU jobs as a friendly status ("your monster is sleeping") rather than an error.

## Tech stack

Boring, well-supported tools everywhere except the AI models, which each get their own container.

| Layer | Choice | Why |
| --- | --- | --- |
| API | Python, FastAPI | Same language as the AI tooling |
| Database | SQLite | Family scale; one file to back up |
| Queue | Jobs table in SQLite with leases | No Redis needed; pull-based workers |
| Live progress | Server-sent events | Simple one-way updates to the tablet |
| HTTPS on LAN | Home server's nginx (Let's Encrypt, LAN-only) in front of Caddy | Tablets only allow camera access over HTTPS |
| Frontend | PWA (e.g. SvelteKit or React) + `<model-viewer>` | 3D viewer and AR on Android and iPad |
| Instant animation | Canvas or PixiJS mesh warp of the cutout | Runs on the tablet, no server |
| CPU steps | rembg, OpenCV, trimesh / PyMeshLab | Background removal, cleanup, inflation, print prep |
| GPU models | Animated Drawings, TRELLIS.2 (MIT), UniRig; TripoSR as fallback | Each in its own Docker image with the NVIDIA container toolkit |
| Deployment | Docker Compose on server and PC | Same images on both machines |

Avoid Hunyuan3D unless its licence is confirmed to cover Belgium; its community licence has excluded the EU.

## Phases

Phase 1 delivers the "it's alive!" moment with the least machinery; each later phase adds one output.

1. **Phase 1 – Alive on screen.** Photo in, cleaned cutout wobbling, bouncing and blinking on the tablet. Runs entirely on the home server and tablet; no GPU needed.
2. **Phase 2 – 3D creatures.** GPU worker on the PC, faithful balloon 3D on the server, TRELLIS.2 on the PC, side-by-side choice, 3D viewer and AR.
3. **Phase 3 – Print.** Print prep step and 3MF export for the FDM printer.
4. **Phase 4 – Moving 3D.** Tap-to-mark rigging aids, UniRig auto-rigging plus a small library of motions; procedural wobble for creatures that won't rig. Animated Drawings once the kids draw recognisable figures.
5. **Phase 5 – Worlds.** Landscapes become places the creatures live in.

### Milestone 1 checklist

- [x] Docker Compose skeleton on the home server: FastAPI, SQLite, Caddy behind the host's nginx (HTTPS)
- [x] Tablet PWA: kid picker, take photo, gallery
- [x] Upload endpoint creating a creature and a cleanup job
- [x] Jobs table with leases and server-sent progress events
- [x] CPU worker: perspective crop, background removal, cutout and mask
- [x] Instant wobble, bounce and blink animation of the cutout in the browser
- [ ] Test with real drawings from the kids and note which ones fail (one so far; paused to start Phase 2)

### Phase 2, first step: faithful balloon 3D (done)

`balloon` CPU step after `cleanup`: the sticker's shape inflated (Poisson, then square root: a disc becomes a flattened hemisphere), drawing as texture front and back, closed mesh, about 20 cm tall → `faithful.glb` (artifact `mesh_faithful`). On the tablet: a yellow 3D badge on the hill opens a spinning view with AR, via a bundled `<model-viewer>`. Next: the GPU worker and TRELLIS.2 for the AI version beside it.

### Phase 2, second step: GPU worker and TRELLIS.2 (built, not yet run on the PC)

Branch `phase2-gpu-trellis`. The `ai3d` GPU step after `cleanup` turns `creature.png` (the creature alone, its mask as alpha, so TRELLIS's own background remover is never loaded) into `ai.glb` (artifact `mesh_ai`), scaled like the balloon. The worker pulls over HTTPS with a shared token: `POST /worker/claim`, heartbeat, `done` (multipart upload; the server picks the file names and checks the GLB), `fail`, `release`. GPU jobs wait as `waiting_for_gpu`, which the tablet treats as settled. Each job runs in a fresh process (VRAM is free afterwards; a game starting mid-job kills it and hands the job back). Game check: Steam/Proton process names via `pid: host`, plus VRAM in use by others. On the tablet the other version spins in a bubble; tapping it swaps them and sets `chosen_style`. Parent mode shows the PC's state.

Open: does `1024_cascade` fit 16 GB with low-VRAM mode (falls back to `512` on out-of-memory)? Which way does the result face? DINOv3 is gated on Hugging Face (needs a token once); its licence is worldwide, with Meta Platforms Ireland as licensor in the EEA, so unlike Hunyuan3D it covers Belgium. AI versions aren't printed yet: `print_prep` still uses the balloon.

### Phase 3, first step: print prep (done)

`print_prep` CPU step after `cleanup` → `print.3mf` for the home printer, a Prusa MK3S+ (single colour, 0.4 mm nozzle). Two objects: "standing" (balloon 8 cm tall, feet sunk 2 mm into a 3 mm oval plinth at least 40% as deep as it is tall) and "lying" (front half on a 1.6 mm plate, no supports). One colour can't show the drawing, so thin dark strokes are engraved 0.6 mm deep, widened to ~1 mm. Both are checked as closed solids (manifold3d); the plinth is a boolean union. Downloaded from parent mode.

## Risks and open questions

The biggest risk is non-humanoid animation; the rest are known engineering problems.

| Risk | Mitigation |
| --- | --- |
| Monsters with odd limbs won't rig or animate | Tiered animation: procedural wobble always works, UniRig when a skeleton fits, humanoid moves only for humanoids |
| AI 3D strays from the drawing | Faithful balloon mode as the default option; kid picks |
| Conflicting CUDA and PyTorch versions | One Docker image per model |
| VRAM spikes on 16 GB at high resolution | 512³ resolution, one model at a time, free cache between jobs |
| Fragile or unprintable meshes | Print prep: flat base, minimum wall thickness, scale to \~8 cm |
| Kids' photos are messy (shadows, angles, notebook lines) | Perspective crop and a parent "fix outline" tool |
| UniRig skinning model not fully released | Check the repo before Phase 4; fall back to simple automatic weights |

**Open questions**

- [x] Is Monster Mash sufficient as the base for faithful 3D, or is a simpler inflation enough? Simple inflation for now; revisit Monster Mash if the results look too much like pillows.
- [x] Which frontend framework do you prefer? SvelteKit.
