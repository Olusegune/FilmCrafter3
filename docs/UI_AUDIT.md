# UI audit (2026-11-06 and 2026-11-07)

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

## Second pass (2026-11-07): contrast, keyboard focus, scaling
Method: `PF_AUDIT2=1 PF_OVERFLOW=1` (scripts/ui-audit2.js through the screenshot tool) on 23 scenes at 1280 px and 1536 px wide, which is what a 1920 px screen shows at 150% and 125% scaling (layout depends on CSS pixels, so the same widths cover both).
- **Contrast (WCAG AA): no failures** among about 830 text items per width. (Text on gradients or pictures cannot be measured by this check and is skipped.)
- **Sideways overflow: none** at either width in these scenes.
- **Found and fixed:** the shot blocks of the film strip (Make) and the scrolling story text (Film) could take keyboard focus but showed nothing when they did (now a gold outline); three scene headings that can be cut short had no tooltip (Acting, Film, Continuity). Re-checked after the fix: 0 focus findings, 0 truncation findings in those scenes.
- **Not covered:** the installed app (these are screenshot-tool scenes with sample data), 100% scaling below 1100 px wide, screen readers, and the screens' behaviour when a window is resized while open.
