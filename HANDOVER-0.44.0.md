# FilmCrafter 0.44.0 handover

Read `HANDOVER-0.37.0.md` (repository, release routine, speech to speech), then `HANDOVER-0.38.0.md` to `HANDOVER-0.43.0.md`. The code is `Olusegune/FilmCrafter3`.

## Implemented: mixer automation (SonicStage slice 8)

Full description and honest limits: `docs/MIXER_AUTOMATION.md`.

- `audiomix.py`: settings gain `automation` (per lane and `master`), `groups`, `markers`; functions `clean_points`, `auto_gain`, `set_automation`, `set_group`, `remove_group`, `marker_add`, `marker_remove`, `crossfade`; `placements` applies group level and mute; `mix_cues` applies cue curve, lane curve, then the whole-film curve on the sum (not on `raw_float` stems) and also runs with an empty plan when a whole-film curve exists.
- `audiocues.py`: cue fields `group` and `auto`. `voiceover.mix_into` and `proaudio` (dialogue stem, mixes, cue sheet `MARKER` rows, OTIO stack markers) use the same curves.
- Shell: new actions on `film_mix` (`automation_set, group_set, group_remove, marker_add, marker_remove, crossfade`); `tests/test_security.py` and `soundmusic.test.ts` check the list. Screen: `src/MixerAutomation.tsx` after the audio export panel in `SceneSound.tsx`.
- Tests: `analysis/tests/test_mixerauto.py` (19, real audio), `src/__tests__/component/mixerautomation.dom.test.tsx` (10).

## Not done / next

- Nothing here was judged by ear, and no editor has opened the markers. The screen edits numbers; a draggable curve is not built.
- Remaining SonicStage: the music director (spotting, motifs, approval and licence records on the existing music generation). The Virtual Production / WorldLock / DirectorCam brief has not been started.
- Gotchas: edit files with the Edit tool, not shell heredocs or `sed -i` with parentheses. Write commit messages to a file and use `git commit -F`. Edit version lines with `sed` in Git Bash (PowerShell adds a BOM). Package the Desktop folder right after the build.

## Also in 0.44.0: one rail on every film screen

`src/FilmRail.tsx` (the shared left rail) is used by `FilmView.tsx` (all stages), `AgentStudio.tsx`, and the timeline Studio's own rail has Story/Cast/Shots buttons (`onFilm`). Owner's rule: the menu rail is available on every screen inside a film, not on Home. Not looked at in the installed app yet: check the layout at narrow widths (the rail hides under 700 px).
