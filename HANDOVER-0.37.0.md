# FilmCrafter 0.37.0 handover

The code lives in `Olusegune/FilmCrafter3` (branch `main`; this work is on `feature/sonicstage-revoice`). `Olusegune/Filmcrafter-2` is an older copy (0.31.1) and is not the line of development. `HANDOVER.md` is older and still names the first repository; read this file and `HANDOVER-0.36.2.md` first.

## Implemented: speech to speech, "Perform it yourself" (experimental)

First slice of the SonicStage plan. Act a line, have it changed into the character's voice locally, keep it as an immutable synthetic take. Full description, safety rules and honest test status: `docs/SPEECH_TO_SPEECH.md`.

- `analysis/filmcrafter_engine/revoice.py`: records (`voice/revoice.json`), consent and revocation, the install step, conversion, output checks. `vc_worker.py` is the one-shot program that runs the model in its own process.
- `cast_voice.takes` / `use_take` accept WAV takes and mark `source: "revoice"`, `synthetic: true`.
- Shell: `film_revoice` (5 allowed actions, checked against the engine by `tests/test_security.py`). Screens: `src/Revoice.tsx` inside Line Studio; `VoiceRecorder` gained an `onTake` option.
- Tests: `analysis/tests/test_revoice.py` (23), `src/__tests__/component/revoice.dom.test.tsx` (9).

## Not done / next

- **The real model was run once through the engine (2026-11-06)**: Install worked (3.0 GB) and a real conversion took 34 s on a processor. **Nobody has listened to it**, and the screens have not driven the real model. Greenroom Local's repository references `runtime/chatterbox_vc_once.py` (`include_str!` in its `lib.rs`) but that file is not committed, so `vc_worker.py` was written against Chatterbox's public interface. Next: use the app's own Install button and Line Studio panel with human recordings, listen, and fix whatever sounds wrong. The owner's test files are on the Desktop (`listening test`).
- Remaining SonicStage milestones (voice identity profile and casting director, performance plans and nonverbal events, Foley and soundscape, music director, ADR and sync, mixer automation and quality inspector, pro export) and the Virtual Production / WorldLock / DirectorCam brief are planned, not started.
- `rafter run` could not be used: the account's fast-scan quota was used up (1 of 1). A manual review of the new surface is in `docs/QA.md`.
- GitHub: the PC was not logged in (`gh auth login`), so pushing needs the owner.

## Release routine (unchanged)

Bump the version in `package.json`, `package-lock.json` (lines 3 and 9), `src-tauri/tauri.conf.json`, `src-tauri/Cargo.toml` (line 3); changelog and `docs/QA.md`; `npm run tauri build`; installers appear in `src-tauri/target/release/bundle` (msi, nsis); copy to a versioned Desktop folder with checksums; commit and push. Edit version lines with `sed`, not PowerShell `Set-Content -Encoding utf8` (it adds a BOM).
