# FilmCrafter 0.49.0 handover

Read `HANDOVER-0.37.0.md`, then `HANDOVER-0.38.0.md` to `HANDOVER-0.48.0.md`. Plan and slice table: `docs/VIRTUAL_PRODUCTION.md`.

## Implemented: virtual production slice 3, WorldLock 2.5D

- `analysis/filmcrafter_engine/worldmath.py`: pure geometry (conventions written at the top: metres, X right, Y up, Z forward; pinhole camera with yaw, pitch, fov; `project`, `layer_corners`, `homography`, `draw_layer`, `coverage`/`uncovered`, `state_at` for events over shots, `side_of_axis`). No film, no files; reusable by Pulseframe.
- `analysis/filmcrafter_engine/worldlock.py`: sets in `worldlock/<id>/` (`set.json`, `history.json`, `versions/`, `assets/`, `views/`). One mutation path (`_mutate`): lock check, undo snapshot, version count, atomic write. Actions: create, assets (add from file, cutout or picture; set; remove; `cut_layer`), characters, cameras, lights, events, shot-to-camera, `render`, `check`, `check_move`, lock/unlock, undo/redo, named versions, set removal (put away, never deleted).
- Shell: `film_worldlock` (28 actions). Screen: `src/SetBuilder.tsx` (floor plan SVG, numeric editing, cameras with views and gap warnings, over-the-shots events and shot cameras, checks and versions), opened from the rail tool **Sets** (`FilmRail.tsx` `worldlock`, `Studio.tsx` `openTool`).
- Tests: `test_worldmath.py` (15), `test_worldlock.py` (28, real pictures, real renders, measured positions), `setbuilder.dom.test.tsx` (14), one real-engine contract test (`worldlock_*.json` fixtures from `scripts/make_engine_fixtures.py`).

## Not done / next

- Never tried with a real photograph set. The first job is to make a set from a real backdrop and a few real cutouts (Cutouts can feed `asset_add` through `{"cutout": id}`; the screen does not offer that button yet, only a file picker) and see whether the layout feels right.
- The screen cannot drag things on the plan and has no "use a cutout" button; both are small next steps. Lights and environment are stored but not shown anywhere yet (DirectorCam will use them).
- Slice 4: the fuller continuity inspector. Slice 5: true 3D (glTF, Three.js, Blender backend). Slice 6: DirectorCam (shot plan from a story beat on a set, blocking, eyelines, conditioning images). Slice 7: reconstruction from reference images. Slice 8: Fidelity integration and polish. See the slice table.
- Bandit output must be READ each time (a finding was missed once). Gotchas as before: write files with the Write tool or patch scripts; shell heredocs with apostrophes are mangled.
