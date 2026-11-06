# FilmCrafter 0.42.0 handover

Read `HANDOVER-0.37.0.md` (repository, release routine, speech to speech), then `HANDOVER-0.38.0.md` to `HANDOVER-0.41.0.md` (voice identity, performance plans, sound design, audio quality inspector). The code is `Olusegune/FilmCrafter3`.

## Implemented: timing, dub-fit and ADR (SonicStage slice 6)

Full description and honest limits: `docs/ADR_SYNC.md`.

- `analysis/filmcrafter_engine/adrsync.py`: frame placement (`nudge`, exact rational time from `edit_time`; `film_fps` reads `film.json` `fps` or uses 24), `fit_plan` / `fit_make` (ffmpeg `atempo`, 8% natural / 15% audible, checked output, cached, a new take), `estimate_shift` / `align` (loudness-envelope cross-correlation, absolute target plus `move_by_frames`, a stated confidence), `adr_mark` / `adr_list` (uses `audioqa.inspect_file`) / `adr_take`. Records: `voice/sync.json`, originals in `voice/_adr/`, takes in `voice/_generated/` (`<shot>-ad<hash>.wav`, `<shot>-df<hash>.wav`, each with a `.json`).
- Integration: `cast_voice.takes` and `_attach_generated` accept the kinds `adr` and `dubfit` (source and name set when chosen); `voiceover.to_render` writes each line's `offset` (seconds) into the render project and `mix_into` places the line that far earlier or later without moving the next line.
- Shell: `film_adrsync`. Screen: `src/TimingAdr.tsx` in Line Studio, between the performance planner and "Perform it yourself"; Line Studio's take list labels the new kinds.
- Tests: `analysis/tests/test_adrsync.py` (23), `src/__tests__/component/timingadr.dom.test.tsx` (11).

## Not done / next

- Nobody has listened to a fitted or ADR take; the line-up has only seen synthetic sound. The guide for lining up is the shot's own take audio or a file; a video model's sound is a weak guide.
- Remaining SonicStage slices: music director (spotting, motifs, approval and licence records on the existing music generation), mixer automation (volume lanes, grouping, M&E and stems), pro export (BWF, cue sheets, OpenTimelineIO). Not built here: word-level alignment, drop-frame timecode, a picture-playing ADR booth, film-level timecode for a line. The Virtual Production / WorldLock / DirectorCam brief is not started.
- Gotchas: edit files with the Edit tool, not shell heredocs (they eat backslashes). Write commit messages to a file and use `git commit -F`. Edit version lines with `sed` in Git Bash. Package a new Desktop folder as soon as the build finishes.
