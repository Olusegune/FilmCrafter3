# FilmCrafter 0.43.0 handover

Read `HANDOVER-0.37.0.md` (repository, release routine, speech to speech), then `HANDOVER-0.38.0.md` to `HANDOVER-0.42.0.md`. The code is `Olusegune/FilmCrafter3`.

## Implemented: professional audio export (SonicStage slice 7)

Full description and honest limits: `docs/PRO_AUDIO.md`.

- `analysis/filmcrafter_engine/proaudio.py`: `plan` (writes nothing) and `export` into `exports/audio/<title> <time>/`. Stems come from the existing mixer (`audiomix.mix_cues` with every other lane muted, so ducking, levels, fades and balance match the film mix) plus a dialogue stem built here (recordings in shot order with the usual gap, moved by `adrsync` frames, cut at the shot end). The mixes are the stems summed and given **one steady gain** (`master_gain`: loudness target, capped by the true-peak ceiling; no limiter), so stems times gain equal the mix. Files are written by ffmpeg (`volume` and `aresample`, optional triangular dither at 16 bit), then a Broadcast WAV `bext` chunk (version 2, 602-byte fixed part) is inserted (`add_bext`) and read back (`read_bext`, and by ffmpeg in the tests). Also a cue sheet (CSV, JSON), an OpenTimelineIO timeline (`otio_timeline`, hand-written JSON, clips pointing at copies in `media/`), `README.txt` and `report.json`; `verify` reads every file back.
- Mixer changes: a **Foley lane** (`audiomix.LANES`, cue field `foley` set by `sounddesign.to_cues`; an ordinary effect cue is unchanged) and a `raw_float` option so `mix_cues` can write a stem with no limiter and no loudness change. The Sound & Music mute toggles and previews list Foley.
- Shell: `film_proaudio` (plan, export). Screen: `src/ProAudio.tsx` in `SceneSound.tsx` after the audio check.
- Tests: `analysis/tests/test_proaudio.py` (21), `src/__tests__/component/proaudio.dom.test.tsx` (7). `opentimelineio` was installed in `analysis/.venv` for the tests (listed, commented, in `analysis/requirements.txt`); the OTIO checks skip without it.

## Not done / next

- No editor has opened an export. First job when the owner has an editor to hand: export a real film, open the stems, the mixes and the `.otio` in it, and fix what it complains about. Positions follow the shot list, not a trimmed cut; a per-scene export, per-person dialogue stems, iXML, AAF, RF64, drop-frame timecode and surround are not built.
- Remaining SonicStage slices: the music director (spotting, motifs, approval and licence records on the existing music generation) and mixer automation (volume lanes, grouping). The Virtual Production / WorldLock / DirectorCam brief is not started.
- Gotchas: edit files with the Edit tool, not shell heredocs or `sed -i` with parentheses (they eat or change backslashes and regex groups). Write commit messages to a file and use `git commit -F`. Edit version lines with `sed` in Git Bash. Package a new Desktop folder as soon as the build finishes.
