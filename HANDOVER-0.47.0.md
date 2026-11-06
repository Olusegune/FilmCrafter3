# FilmCrafter 0.47.0 handover

Read `HANDOVER-0.37.0.md`, then `HANDOVER-0.38.0.md` to `HANDOVER-0.46.0.md`. The code is `Olusegune/FilmCrafter3`. SonicStage is finished (0.37 to 0.45); 0.46.0 made the menu rail one component. This starts the Virtual Production / WorldLock / DirectorCam brief; the plan and the slice table are in `docs/VIRTUAL_PRODUCTION.md`.

## Implemented: slice 1, the cutout studio

- `analysis/filmcrafter_engine/keying.py`: pure numpy and Pillow, no film and no network (reusable by Pulseframe as it stands): `analyze_plate`, `key` (chroma-plane distance, auto-scaled straight ramp), `refine`, `despill`, `decontaminate`, `transform_layer`, `over`, `contact_shadow`, `color_match`, `composite`, `anchor_of`.
- `analysis/filmcrafter_engine/vpstudio.py`: the film's side. Record `vp/vp.json` (safeio): sources, cutouts, compositions, removed. Files under `vp/sources`, `vp/cutouts/<id>`, `vp/renders`, `exports/virtual-production`. Nothing deleted; paths that lead outside the film are refused.
- Shell: `film_vp` (10 actions). Screen: `src/CutoutStudio.tsx`, opened from the rail tool **Cutouts** (`FilmRail.tsx` TOOLS, `Studio.tsx` `openTool`).
- Tests: `analysis/tests/test_keying.py` (26, synthetic plates with known truth), `analysis/tests/test_vpstudio.py` (20, real files), `src/__tests__/component/cutoutstudio.dom.test.tsx` (12), one real-engine contract test (`vp_*.json` fixtures from `scripts/make_engine_fixtures.py`).

## Not done / next

- Never tried on a real photograph or a real generated plate: the first job is to take a real green-screen image, run Check the screen and Cut out, and tune the defaults from what is seen. The thresholds in `keying.py` (analyze_plate limits, `DEFAULTS`) come from synthetic plates.
- Next slice (2): Production Mode selector on shots, video (frame sequences, temporal alpha smoothing, PNG sequences with alpha, transform keyframes, compositing over footage). Then WorldLock 2.5D, and so on: see the slice table.
- No segmentation or matting model, no OpenCV, no 3D library is in the product. Adding one is a deliberate step (show size, hardware and licence; install on request).
- Gotchas: write files with the Write tool or small patch scripts, not shell heredocs containing apostrophes (the shell tool mangles them). Commit messages to a file, `git commit -F`. Version lines with `sed`. Package the Desktop folder right after the build (`portable/FilmCrafter/` with exe, icons, `engine/`).
