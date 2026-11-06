# FilmCrafter 0.40.0 handover

Read `HANDOVER-0.37.0.md` (repository, release routine, speech to speech), `HANDOVER-0.38.0.md` (voice identity) and `HANDOVER-0.39.0.md` (performance plans) first. The code is `Olusegune/FilmCrafter3`.

## Implemented: sound design (SonicStage slice 4)

Full description and honest limits: `docs/SOUND_DESIGN.md`.

- `analysis/filmcrafter_engine/sounddesign.py`: soundscape profiles per Bible place (layers at a distance), Foley events (action, object, material, surface, distance, side, intensity, start, library sound, approval), `suggest` (plain rules over a shot's written action; at most 6 per shot; nothing saved), `candidates` (library search through `audiocues.match_assets`), `to_cues` (approved things with a sound become ordinary cues; ambience is one scene-wide looping cue per layer; re-running updates the same cues). Records: `audio/sounddesign.json`.
- `audiocues` cues gained `pan` (-1 to 1; old cues read as 0). `audiomix.pan_gains` applies it (centre unity, never louder).
- Shell: `film_sounddesign`. Screen: `src/SoundDesign.tsx`, mounted in `SceneSound.tsx` before "How it is mixed".
- Tests: `analysis/tests/test_sounddesign.py` (23, including the real mixer), `src/__tests__/component/sounddesign.dom.test.tsx` (9).

## Gotcha found this time

Writing a regular expression through a shell heredoc (`python - <<'EOF'` with `\\b`) put backspace characters into the source and the pattern silently never matched. Edit files with the Edit tool, then print the line to check it.

## Not done / next

- Nobody has listened to a designed scene. Reverb is only a note (the mixer does not add reverb). No room, occlusion or 3D: that needs WorldLock, which does not exist yet.
- Foley suggestions are keyword rules; they will need tuning on real screenplays.
- Next SonicStage slices: music director (spotting, motifs, approval and licence records on top of the existing music generation), ADR and picture sync (dub-fit, frame-accurate placement, audio-first), mixer automation and the audio quality inspector, pro export (stems, BWF, cue sheets). The Virtual Production / WorldLock / DirectorCam brief is not started.
- Commit messages: write to a file and use `git commit -F`. Edit version lines with `sed` in Git Bash, not PowerShell `Set-Content -Encoding utf8` (it adds a BOM).
