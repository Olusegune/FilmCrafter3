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

Agent Studio engine tests: 15 passed. Agent Studio UI tests: 6 passed. TypeScript and Rust shell tests passed. Windows executables are unsigned because no code-signing certificate is configured.
