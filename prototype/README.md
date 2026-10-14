# Prototype

`index.html` is the single-page Monster Hill prototype: kid picker, magnifying-glass camera, sleep → wake, tap-to-mark eyes, naming, and the wobble / bounce / blink renderer. Photo → cutout runs in the browser here; in the real app that moves to the Python CPU worker.

It is a reference, not production code. Serve it behind Caddy (HTTPS) to use the live camera on the tablet; without HTTPS it falls back to picking a photo from the gallery.

Useful sections:
- `segment()` / `processPhoto()` — cutout pipeline to port to Python (between `/*SEG-START*/` and the end of `processPhoto`)
- "the wobble / bounce / blink renderer" — the mesh-warp animation to carry into the frontend
- `startWake()` / `wakeUp()` / `setEyeMode()` — the sleep → wake flow and eye marking
