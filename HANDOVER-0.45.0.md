# FilmCrafter 0.45.0 handover

Read `HANDOVER-0.37.0.md` (repository, release routine, speech to speech), then `HANDOVER-0.38.0.md` to `HANDOVER-0.44.0.md`. The code is `Olusegune/FilmCrafter3`.

## Implemented: music director (SonicStage slice 9, the last SonicStage slice)

Full description and honest limits: `docs/MUSIC_DIRECTOR.md`.

- `analysis/filmcrafter_engine/musicdirector.py`: motifs, spots (score / source / silence), `suggest` (plain word rules, nothing saved), `prompt` (words only, nothing sent), `candidates`, `record_set` (approval history), `to_cues` (ordinary music cues; licence "no" blocked), `report`. Record: `audio/music.json` via safeio. No provider, no key, no paid call.
- Shell: `film_music`. Screen: `src/MusicDirector.tsx` after Sound design in `SceneSound.tsx`.
- Tests: `analysis/tests/test_musicdirector.py` (24, real files and the real mixer), `src/__tests__/component/musicdirector.dom.test.tsx` (12), one real-engine contract test (fixtures `music_*.json` made by `scripts/make_engine_fixtures.py`).

## Not done / next

- No music was generated to test the words; the owner should try one spot end to end (words, generator, choose the result, record, put into the film) and listen.
- The suggestion rules are small and English-only.
- SonicStage is otherwise complete. The Virtual Production / WorldLock / DirectorCam brief has not been started and is the largest remaining piece; start with a plan, then thin slices as before.
- Gotchas: edit files with the Edit tool or small patch scripts, not shell heredocs with backslashes. Write commit messages to a file and use `git commit -F`. Edit version lines with `sed` in Git Bash. Package the Desktop folder right after the build (portable layout: `portable/FilmCrafter/` with exe, icons and `engine/`).
