# FilmCrafter 0.48.0 handover

Read `HANDOVER-0.37.0.md`, then `HANDOVER-0.38.0.md` to `HANDOVER-0.47.0.md`. Plan and slice table: `docs/VIRTUAL_PRODUCTION.md`.

## Implemented: virtual production slice 2

- `analysis/filmcrafter_engine/vpvideo.py`: `capabilities` (asks ffmpeg), `import_clip`, `key_clip` (calibrated once per clip via `keying.calibrate`, optional neighbour smoothing, jitter metric, cancel flag `vp/cancel.flag`), `export_clip` (PNG sequence, ProRes 4444, VP9 alpha, each decoded back), `render_video` (H.264 over a pipe, progress, cancel, removes its own half-made output), `compose_at`/`layer_state` (one frame at a time; `vpstudio.render` now calls it, with a `time`).
- `keying.py`: `auto_hi`, `calibrate`, `clean_keys`, `interp` (keyframes: x, y, scale, rotation, opacity; linear, smooth, hold). Layers in `vpstudio` gained `start`, `loop`, `keys`.
- Shots: `production` field (`shots.set_fields`), `vpstudio.clean_production` and `plate_clause`; `make._visual` asks for a plate and drops the place when the mode is green screen or transparent. Screen: `src/ProductionMode.tsx` on the Camera tab of `ShotLab.tsx`.
- Shell: `film_vpvideo` (6 actions; progress arrives as `engine-progress` with task `vpvideo`). Screen: `CutoutStudio.tsx` now handles clips, alpha export, keyframes and video render.
- Fix: `Studio.tsx` `openTool` switches Agent Studio to the Manual Studio first (Layers did nothing there).
- Tests: `test_vpvideo.py` (21, real encoded video), `test_shotproduction.py` (5), `cutoutvideo.dom.test.tsx` (9), `productionmode.dom.test.tsx` (7), a real-engine contract test with four more fixtures (`vpvideo_*.json`).

## Not done / next

- Never tried on camera footage or a real generated plate/clip: the first job is to key a real green-screen clip and tune the defaults (`keying.DEFAULTS`, `analyze_plate` limits, the smoothing weight).
- The generated plate is only *asked for* through the prompt; nothing here checks a generated shot automatically after it is made (the person uses Cutouts > Check the screen). A natural next step is a one-button "check this shot's plate".
- Slice 3: WorldLock package and 2.5D set builder. Then continuity inspector, 3D, DirectorCam, reconstruction (see the slice table). Layered scene mode is deliberately greyed until it exists.
- Gotchas: write files with the Write tool or patch scripts; shell heredocs containing apostrophes are mangled. Windows keeps ffmpeg's output file open until the process has exited (wait before removing it).
