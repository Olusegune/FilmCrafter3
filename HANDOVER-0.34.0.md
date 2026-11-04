# FilmCrafter 0.34.0 handover

## What changed

- Agent Studio analyses a script with the AI brain selected in Settings, labels its findings and suggestions, and waits for the creator to accept, change or ignore them.
- Visual styles are selected with plain-language cards. A filmmaker craft profile is optional and influences camera, lens, lighting, blocking, colour, pace and performance traits without sending the filmmaker's name to generation providers.
- The available AI brains are OpenAI, Anthropic Claude, Google Gemini, OpenRouter, Ollama and LM Studio. These models plan and reason; the existing image/video providers generate media.
- Guide me, Collaborate and Autopilot modes are available. Autopilot uses the resumable ComfyUI overnight pipeline; cloud keyframes still require a live price confirmation.
- Manual Studio has a small animated Film Guide. It shows progress, opens Agent Studio, and can be minimized or hidden.
- Existing budget gates, one-use spend tokens, approved assets, manual shot controls and restart recovery are preserved.

## Where to find it

Open a project, enter Studio, and choose **AI Agent** in the left rail or **Agent Studio** in the top bar. The animated aperture at the lower right is the optional Film Guide. Configure the AI model in **Settings → AI brain** and its API key in **Settings → Connections**.

## AI and privacy

OpenAI, Claude, Gemini and OpenRouter send the script/project context needed for the request to that provider. Ollama and LM Studio use the configured local server. Keys are kept in Windows Credential Manager. Paid media generation is separate and is never silently authorized by the chat or script analysis.

## Validation

- TypeScript/Vite production build: passed.
- Component tests: 81 passed.
- Agent Studio/director-style Python regressions: passed.
- Rust native tests: 15 passed.
- Full engine run: 3,124 test passes across its phases; the one unit failure was corrected and re-run. Security scan was corrected to zero medium/high findings. Python dependency audit now reports no known vulnerabilities. npm audit reports none.
- MSI, NSIS setup EXE and standalone EXE: built successfully.

## Packaging note

The Windows files are not Authenticode-signed because no code-signing certificate is configured. Windows SmartScreen may therefore warn on first launch. The MSI or setup EXE is the recommended install. The portable folder contains the standalone executable and its engine resources.

## Known limits

- Autopilot requires a configured ComfyUI video workflow for unattended local video. If it needs paid cloud keyframes, it pauses and asks the user to confirm in Manual Studio.
- The app does not impersonate filmmakers or copy a particular film. Profiles are bounded craft attributes and remain optional.
- Direct script attachment still follows the existing project import flow; Agent Studio accepts pasted story/script text for analysis.
