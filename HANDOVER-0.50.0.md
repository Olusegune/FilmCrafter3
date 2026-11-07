# FilmCrafter 0.50.0 handover

Read `HANDOVER-0.37.0.md`, then `HANDOVER-0.38.0.md` to `HANDOVER-0.49.0.md`. Plan and slice table: `docs/VIRTUAL_PRODUCTION.md`.

## Implemented: virtual production slice 6, DirectorCam (built before the 3D set; the slice table keeps the brief's numbering)

- `analysis/filmcrafter_engine/directorcam.py`: `place_camera` (shot size = height of world in frame; over the shoulder), `camera_path` (11 moves, deterministic), `plan_beat` (word rules; subject from the name before the verb, carried over otherwise), `checks` (9 rules, `allow` makes a note), plans in `worldlock/<set>/plans/`, `preview`, `package` (frames, strip, 16-bit depth, object map, `package.json`), `capabilities` (from `compose._takes_end` and `REFS_RX`; nothing assumed), `apply` (maps to the film shot's own camera lists, adds the first frame to `reference_assets`).
- `worldlock.py` cameras gained `focal_mm`, `sensor_mm`, `aperture`, `aspect`, `focus`; `render` takes per-view `overrides` (people and things placed elsewhere for one view; the set is unchanged).
- Shell: `film_directorcam` (15 actions; the CLI lists its choices literally so `test_security.py` can read them). Screen: `src/DirectorCam.tsx` from the rail tool **DirectorCam**.
- Tests: `test_directorcam.py` (33, real renders), `directorcam.dom.test.tsx` (16), one real-engine contract test with eight new fixtures.

## Not done / next

- No generation: a package is made, nothing is sent to a model. The brief's visual-difference viewer (generated shot against the set) and automatic validation of a generated shot are not built; that needs a generated shot to look at and, to be honest, a vision check that reports uncertainty.
- The planner is English word rules. A natural improvement is an optional model-written plan that the same checks then validate (with the price shown first); none exists.
- Slice 5 (true 3D: glTF import, Three.js view, Blender bridge) and slice 7 (reconstruction from reference images) are not started. Slice 8 (Fidelity integration, polish) too. See the table.
- Cameras are typed, not dragged; the plan view only selects.
- Read the Bandit output every time. Gotchas as before: Write tool or patch scripts, not heredocs with apostrophes; read a select's value before awaiting.
