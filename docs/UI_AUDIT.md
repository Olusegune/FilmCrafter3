# UI audit (in progress, 2026-11-06)

Method: every screenshot-harness scene (`scripts/docshots-edge.mjs`, 61 scenes plus new ones for Sets, 3D, DirectorCam, Cutouts) at 1100, 1366 and 1920 px wide with `PF_A11Y=1 PF_OVERFLOW=1 PF_QA=1` (axe-core WCAG 2.1 A/AA, sideways overflow, console errors). Real screenshots of the screens only; the harness uses sample data, not the installed app.

## Found and fixed
- 3D tab: each model took three rows of number boxes (now folded under "Position and size"); fog box clipped; intro text said "pictures" only; remove button's accessible name did not contain its visible text (now "Remove").
- Four-view framing was dominated by far objects (fixed in 0.51.1).
- Shot inspector header pushed the panel 14-135 px past the window at 1100 px wide (Studio, Shots, Make): header may now shrink.
- Home preset cards: accessible name did not contain the visible text (axe label-content-name-mismatch).

## Found, not fixed
- Shot-suggestions scene still reports an inspector header 14 px past the window at 1100 px (a hidden panel behind the sheet; not looked into).
- Console errors in the harness: `Cannot read properties of null (reading 'manifest')` (Studio shot/advanced), `shots is not iterable` (voice-over scene), `reading 'sfx'` (sound effects scene). May be gaps in the sample data rather than app bugs; not checked.
- At 1366 px one `.chip` is 48 px past the window edge in one scene.
- The Studio at 1100 px is cramped (tab row and "Fewer" button tight).
- Not yet done: contrast/focus checks (`scripts/ui-audit2.js`), 125%/150% scaling, review of the new DirectorCam and Cutouts scenes' screenshots, re-capture of the guide's pictures.
