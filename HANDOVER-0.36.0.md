# FilmCrafter 0.36.0 handover

## What changed

Agent Studio now has a durable coordination layer on top of FilmCrafter's existing project, jobs and approval records:

- **Production inbox:** one list for milestone approvals, failed or uncertain jobs, and proposed revisions.
- **Restart recovery:** **Recheck project** derives a safe next action from persisted project files and jobs. It never submits provider work.
- **Revision impact preview:** a request is matched against approved characters, locations, scenes and shots before it is recorded. The UI shows affected shots, downstream review and approved assets that stay locked. Ambiguous requests must be made more specific.
- **Compatibility migration:** older `agent-studio.json` records acquire the current production stages without losing approvals, revisions or activity.

The safety boundary is unchanged: Agent Studio has no provider-submission action. Cloud generation must still pass through FilmCrafter's price display, budget protection and one-use confirmation token.

## Verification

`npm run test:all` completed with **13 passed, 0 failed, 0 skipped**. This covered TypeScript, Vitest screens, Rust shell tests, unit/regression/security/acceptance/integration/end-to-end engine groups, secret scanning, Bandit, pip-audit and npm audit. The targeted Agent Studio engine file has 12 passing tests and the component suite has 83 passing tests. A production Tauri build produced the portable executable, MSI and NSIS installer.

## Windows builds

The binaries are unsigned because no Windows code-signing certificate is configured. Windows may therefore show a SmartScreen warning. This is a distribution limitation, not a failed build.

## Important files

- `docs/AGENT_STUDIO.md` — user and safety behavior
- `analysis/filmcrafter_engine/agent_studio.py` — orchestration, inbox and impact engine
- `src/AgentStudio.tsx` and `src/agent-studio.css` — workspace UI
- `analysis/tests/test_agent_studio.py` and `src/__tests__/component/AgentStudio.test.tsx` — regression coverage
- `CHANGELOG.md` — release notes

## Known limitation

This milestone coordinates and safeguards work; it does not silently run paid cloud production. Local ComfyUI Autopilot remains the unattended path. Cloud work still stops at the explicit live cost confirmation, by design.
