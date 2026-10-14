# Kids UI

Decided 2026-10-13. The prototype implementing all of this is `prototype/index.html`.

## Requirements

- Works for a non-reader under 5: icons, big touch targets, colour and sound instead of text.
- Home screen = gallery of creatures per kid. Kid picker with avatar colours, no login.
- Main flow: pick kid → big "take photo" button → playful waiting moment → creature appears and wobbles → kid names it (parent types) → saved to gallery.
- Tapping a creature in the gallery makes it react (bounce, blink, wobble).
- Status for slow steps is friendly, never an error ("your monster is sleeping, it'll wake up soon").
- Hidden parent mode (long-press) for deleting, retrying, settings and, later, printing.

## Chosen direction: "Monster Hill"

Chosen over "Magic Book" and "Monster Machine".

- **Hill.** Each kid's creatures live on a sunny hill that scrolls sideways as the collection grows. Sky, sun and drifting clouds above; kid avatars top-left; parent lock (long-press with a progress ring) top-right.
- **Camera = magnifying glass.** The home button is a brass magnifying glass, bottom-right. The camera screen shows the live view inside a giant lens on a dark background, with a big red shutter button and a small "from photos" button. The lens is framing only: the full frame is captured and the server crops to the paper.
- **Waiting moment = the creature sleeps.** Night falls, the creature lies dimmed under a yellow blanket with floating z's, then wakes up (blanket slides away, day returns). No eggs or hatching — kids may draw mammals.
- **Blink.** Eyes can't be detected in drawings, so after waking the parent taps each eye (the first rigging aid). Creatures without marked eyes do a small squash instead of a blink.
- **Turn.** Drawings made with the pad sideways can be turned a quarter turn per tap (button with a tilted yellow square, next to the eyes button; also in parent mode on the hill). The app can't know which way is up, so the kid or parent decides.
- **Naming.** A sheet with a text field (parent types), a big green save button.
- **Parent mode.** Shows a bar with settings (e.g. sound) and a red delete button on each creature (tap twice to confirm).

## Visual tokens (from the prototype)

- Font: Fredoka (rounded).
- Colours: sky `#CFEAF7`, night `#33376E`, hill `#8CCB6E` / `#74B85A`, ink `#2E2A3B`, sun `#FFD45C`, brass `#F5B83D`, wood `#B5651D`, go/shutter `#FF5A3C`, ok/save `#2F9E52`, stop/delete `#D7372B`, kid colours `#FF8A3D` and `#3D7BFF`.
- Respects `prefers-reduced-motion`.

## Later phases

Tap-to-mark rigging aids for head, legs, hands and tail; faithful vs AI 3D side-by-side choice; 3D viewer and AR via `<model-viewer>`; printing from parent mode.
