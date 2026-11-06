# FilmCrafter 0.41.0 handover

Read `HANDOVER-0.37.0.md` (repository, release routine, speech to speech), `HANDOVER-0.38.0.md` (voice identity), `HANDOVER-0.39.0.md` (performance plans) and `HANDOVER-0.40.0.md` (sound design) first. The code is `Olusegune/FilmCrafter3`.

## Implemented: audio quality inspector (SonicStage slice 5)

Full description and honest limits: `docs/AUDIO_QA.md`.

- `analysis/filmcrafter_engine/audioqa.py`: `measure` (pure; numpy only) gives peak, clipping runs, silences (start / inside / end), noise floor (only where there are pauses; relative to the loud parts), dropouts, clicks, DC, mono fold-down loss; `findings` turns measurements into fix / look / note findings by role (voice, effect, music, mix); `inspect_file` adds ffmpeg loudness and true peak (`export.measure_loudness`); `film` checks recordings (and longer-than-shot), approved cue sounds, abrupt cue edges (no fade, not looping), per-person loudness outliers (low confidence) and more-than-one-voice-or-model, and an optional finished film. Every limit is in `LIMITS` and is returned with the report. Read-only.
- Shell: `film_audioqa` (film, inspect). Screen: `src/AudioCheck.tsx`, in `SceneSound.tsx` before "How it is mixed".
- Tests: `analysis/tests/test_audioqa.py` (23), `src/__tests__/component/audiocheck.dom.test.tsx` (7).

## Also this session: 0.40.1

The Studio player showed the selected shot instead of the shot under the playhead, so scrubbing did not change the picture; fixed in `src/playerMath.ts` (`shotToShow`, `needsSeek`, `seekForSelection`), `Clip` in `Studio.tsx`, `PlayerOverlays.tsx` and `OwnMedia.tsx`. The owner confirmed scrubbing works in the installed 0.40.1.

## Not done / next

- The inspector has only seen synthetic sound. Thresholds (clip run length, dropout length, click jump, 6 dB level outlier, -50 dBFS voice noise) need tuning against real recordings; change them only in `LIMITS` and keep the tests in step.
- Remaining SonicStage slices: music director (spotting, motifs, approval and licence records on the existing music generation), ADR and picture sync (dub-fit, frame-accurate placement, audio-first), mixer automation (volume lanes, grouping), pro export (stems, BWF, cue sheets, OpenTimelineIO). The Virtual Production / WorldLock / DirectorCam brief is not started.
- Gotchas: edit files with the Edit tool, not shell heredocs (they eat backslashes: a `\b` regex became backspace characters twice). Write commit messages to a file and use `git commit -F`. Edit version lines with `sed` in Git Bash. Package a new Desktop folder as soon as the build finishes (the owner looks for it there).
