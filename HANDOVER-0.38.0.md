# FilmCrafter 0.38.0 handover

Read `HANDOVER-0.37.0.md` first for the repository, the release routine and the state of speech to speech. The code is `Olusegune/FilmCrafter3`.

## Implemented: voice identity (SonicStage slice 2)

Full description and honest limits: `docs/VOICE_IDENTITY.md`.

- `analysis/filmcrafter_engine/voiceid.py`: lock (voice, model and speech-to-speech reference recorded; changes reported), listening ratings and an accent status that is the listener's own judgement, casting comparison (builds on `voicedirect.score_voice`, adds audition estimate, licence reminder, where it runs, earlier ratings), cast library (`~/.filmcrafter/cast_library.json`, references not audio). Records: `voice/identity.json`.
- `bible.IDENTITY_FIELDS` (nine fields) are stored in the same `voice_profile`; the AI proposal still covers only `VOICE_PROFILE_FIELDS`.
- Shell: `film_voiceid` (no key given to the engine). Screen: `src/VoiceIdentity.tsx` inside the character voice editor in `SoundMusic.tsx`.
- Tests: `analysis/tests/test_voiceid.py` (21), `src/__tests__/component/voiceidentity.dom.test.tsx` (9).

## Not done / next

- Pronunciation notes are saved but not applied to spoken lines.
- No real ElevenLabs call was made in testing; nobody has used the panel on a real film.
- Next SonicStage slices: performance director (phrase-level emotion plans, nonverbal events, effort, retakes), then Foley and soundscapes, music director, ADR and sync, mixer automation and quality inspector, pro export. The Virtual Production / WorldLock / DirectorCam brief is not started.
- Edit version lines with `sed` in Git Bash (PowerShell's `Set-Content -Encoding utf8` adds a BOM). Commit messages: write to a file and use `git commit -F`.
