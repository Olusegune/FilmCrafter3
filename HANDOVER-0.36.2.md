# FilmCrafter 0.36.2 handover

This release extends the first-scene production proof across the film departments.

## Implemented

- A seven-department proof board: picture, dialogue, score, SFX, motion graphics, mix and preview.
- Durable voice/score/SFX prompts and provider choices in `agent-production-run.json`.
- Suggested titles and motion graphics are created as **disabled** `agent-proof` layers, visible for editing and approval but absent from the film until enabled.
- Audio departments distinguish skipped, user-media and paid-cost-review states. Preparation makes no provider request.
- A completed visual proof can be exported locally as a scene-only preview through FilmCrafter's existing mix, caption and overlay pipeline.
- Remaining scenes are not queued or exported by the proof runner.

## Safety boundary

Local preparation and preview are automatic. Generated voices, music and SFX still use their existing live estimates, rights acknowledgement, ledger and explicit confirmation. Agent Studio does not treat “automate my film” as permission to spend.

## Verification

The final complete matrix passed **13 groups with 0 failures and 0 skips**: TypeScript; 734 Vitest tests; 15 Rust tests; 1,771 unit, 337 regression, 235 security, 61 acceptance, 729 integration and 2 end-to-end engine tests; repository secrets; Bandit; pip-audit; and npm audit. Agent Studio's focused tests are 15 engine and 6 component tests. See `docs/QA.md` for scope and the manual/paid checks that were not performed. Windows executables are unsigned because no code-signing certificate is configured.
