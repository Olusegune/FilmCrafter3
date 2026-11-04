# FilmCrafter 0.35.1 handover

This is the QA-hardened whole-pipeline Agent Studio release. It retains the 0.35.0 production manifest and separate image, video, voice, music and SFX routing, with a cleaner intake and stronger recovery.

## Findings fixed

- Music and SFX providers now populate correctly from the audio-provider response.
- Filmmaker regions use a geographic/global taxonomy rather than treating a medium as a region.
- Empty sound-provider replies no longer produce a console error.
- Production model controls are collapsed into a clear Automatic/choice-count summary instead of crowding the intake.
- Approved briefs show the chosen department routes; long AI descriptions wrap in the review grid.

## Evidence

- Engine: 1,765 unit, 337 regression, 235 security, 61 acceptance, 729 integration and 2 end-to-end passes.
- Agent Studio: 9 focused engine tests, 4 component tests and 2 Playwright browser checks.
- UI/Vitest: 732 passed (including 82 focused component tests). Rust shell: 15 passed.
- TypeScript production build, secrets scan, Bandit, Python dependency audit and npm production audit passed.

No real paid provider generation was performed. The MSI/EXE files are unsigned because no Authenticode certificate is configured.
