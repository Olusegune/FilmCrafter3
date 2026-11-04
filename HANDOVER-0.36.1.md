# FilmCrafter 0.36.1 handover

This release adds the first executable slice of Agent Studio production automation.

## First-scene proof

- Agent Studio isolates the first planned scene and reports the exact shots, missing keyframes, missing videos, chosen routes and estimated cloud cost.
- When all required media routes are local ComfyUI workflows, **Make first scene locally** queues only that scene and starts the existing renderer.
- Progress is persisted in `agent-production-run.json`. The workspace polls the durable state and advances completed local keyframes into local video jobs.
- When the proof is finished it becomes the `first_scene` approval checkpoint. Remaining scenes are not generated.
- If either route is a cloud provider, Agent Studio refuses to queue it and sends the creator to Manual Studio's live price, budget and one-use spend-token confirmation.

## Verification

- Agent Studio engine tests: 14 passed.
- Agent Studio component tests: 6 passed.
- Rust shell tests: 15 passed.
- Fast release matrix: 11 groups passed, 0 failed, 0 skipped (TypeScript, all Vitest screens, Rust, unit/regression/security/acceptance engine groups, secrets, Bandit, pip-audit and npm audit).
- Production web build passed.

## Limitation

This slice automates the visual proof scene: keyframes and shot videos. Dialogue, score, SFX and motion graphics remain existing department tools and are not yet chained into the proof-scene runner. Cloud work deliberately remains a separate explicit confirmation step.

Windows builds are unsigned because no code-signing certificate is configured.
