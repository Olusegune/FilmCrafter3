# Agent Studio

Agent Studio is the guided face of the same FilmCrafter project used by Manual Studio. It is not a second render engine and it does not copy assets. The hybrid design keeps automated production understandable while preserving every existing shot-level control.

## Why a hybrid workspace

A permanently open assistant would compete with the film and timeline. A completely separate automatic product would split project state and make recovery dangerous. Agent Studio is therefore a focused workspace for the creative brief, production sequence, approvals, budget and recovery; **Manual Studio** remains the precision editor. The switch in either workspace preserves the project and current jobs.

The visual Film Guide is a small animated aperture in Manual Studio. It reports the current milestone and opens Agent Studio, but can be minimized or hidden. It shares Agent Studio's persisted state and never blocks editing.

## Optional director style

In Manual Studio, choose **Director style** to browse the worldwide filmmaker library. The detail pane explains camera and lens behaviour, lighting, colour, editing rhythm, movement, design and performance. This layer is optional and can be cleared at any time. It does not select or replace the film's visual look, rewrite the story, alter timing, change who appears or regenerate approved work. FilmCrafter stores the selected name for attribution in the interface, but generation providers receive only the bounded craft traits.

## Using it

1. Open a render project in Studio and choose **Agent Studio**.
2. Paste a story or idea, choose the film length, frame and budget, then select Guide me, Collaborate or Autopilot.
3. Choose **Analyse script**. The selected AI brain lists story facts and optional visual/director-profile suggestions. Accept, change or ignore them; the script remains the source of truth. You can also skip analysis.
4. Build the production plan. Planning is free; generated media is not started here.

## First-scene proof

After a shot plan exists, Agent Studio isolates its first scene as a bounded proof. The card names the scene, shot count, missing keyframes and videos, chosen image/video routes, and estimated cloud price. **Make first scene locally** is available only when every required generation step uses the user's running ComfyUI workflows. It queues only those shots, starts the existing renderer, resumes from `agent-production-run.json`, advances from keyframes to video, and returns the result for approval. Remaining scenes are untouched.

If either route is a cloud provider, Agent Studio does not queue it. **Review price & make first scene** opens Manual Studio, where the live price, project budget and one-use spend token remain mandatory. This separation prevents a broad automation instruction from becoming permission to spend.

The proof card also tracks **Picture, Dialogue, Score, SFX, Graphics, Mix and Preview**. **Prepare sound & graphics** stores the first-scene department plan in the durable run and places suggested titles as disabled Motion Graphics drafts. The creator must enable or edit them; preparing never calls an audio provider. Voice, music and SFX marked **needs cost review** continue through their existing department screens, with separate price, rights and confirmation checks. When the visual proof is complete, **Build local preview** exports only that scene through the existing overlay and audio-mix pipeline.

## Whole-film departments and model choice

The analysis package covers characters (appearance, wardrobe and voice direction), locations/sets and lighting, continuity props, scenes, a provider-neutral score prompt, sound direction, SFX/ambience cues, and useful titles or motion graphics. Before analysis, **Production models** lets the creator choose independent models/providers for reference and keyframe images, shot video, voices, music/score and SFX. Automatic follows the project's Plan & budget router. Accepted image/video choices are pinned into that router; every department choice and approved design is saved in `agent-production.json` so the run can resume after restart.

FilmCrafter's existing department engines remain responsible for execution: the Bible and reference tools make cast/world assets, Voice Design handles casting and dialogue, Sound handles score/SFX/ambience and mix, Motion Graphics creates titles and cards, Studio makes keyframes/video and the editor/review/export tools finish the film. Agent Studio coordinates the same project rather than creating incompatible parallel assets.
4. Review the current milestone. **Approve & continue** records an explicit approval tied to the asset versions shown. Silence never approves anything.
5. Use **Request changes** for a focused revision. FilmCrafter first previews the matched scenes and shots, downstream stages and how many approved assets remain locked. An ambiguous request asks for a clearer character, location or shot instead of guessing. Confirming records the request; it still does not generate or charge anything. Paid revision execution shows its price in FilmCrafter's existing confirmation UI.
6. Choose **Manual Studio** whenever an individual shot, take, reference, sound or edit needs precise control.

## Ask the director

**Ask the director** connects Agent Studio to the AI brain selected in Settings: OpenAI, Anthropic Claude, Google Gemini, OpenRouter, Ollama or LM Studio. The chat can summarize the project, inspect shots and keyframes, read the optional filmmaker craft profile, and prepare focused revisions or generation requests. Project details and chat messages go to the selected cloud provider; Ollama and LM Studio keep them on the local server.

Changes are suggestions by default. Review each one and choose **Apply** or **Reject**. The optional **Make non-paid changes straight away** switch applies only local project changes; it never applies to a generation request. Every paid request remains a proposal and must be opened in Manual Studio, priced against the current provider settings, and confirmed through the existing one-use spend token.

## Safety and recovery

- Workflow state is written atomically to `agent-studio.json` inside the project and reloads after a restart.
- **Recheck project** reconciles the persisted workflow with real project files and jobs. It reports the safe next action but never fabricates completion or submits a provider job.
- **Production inbox** gathers milestone approvals, failed or uncertain jobs, and pending revision requests in one place. Uncertain provider jobs must be checked before retrying to avoid a duplicate purchase.
- Pause prevents Agent Studio from advancing upcoming work. Provider jobs already submitted can still finish or incur their confirmed charge, and the interface says so.
- Actual completed costs, committed active-job estimates and the user's limit are separate values.
- Agent Studio has no provider-submission command. Paid jobs continue to require the existing short-lived, single-use spend token bound to the displayed batch.
- Approvals and revision requests are append-only records. A revision does not erase earlier approvals, takes or assets.
- Revision impact is derived from the approved character/location manifest and shot plan. Only exact matches are proposed for regeneration; an unscoped request remains blocked from confirmation.
- The chat has a fixed tool allow-list with strict argument schemas. It has no path, shell, delete or export tool. Its activity is recorded in `agent/log.jsonl`; suggestions and their resolution are recorded in `agent/proposals.json`.

## Autopilot and limits

Autopilot starts the existing resumable overnight pipeline when ComfyUI has a video workflow: keyframes, video and export can run unattended on the user's computer. If cloud keyframes are required, Agent Studio stops and sends the user to the live price confirmation in Manual Studio. It does not silently accept charges, invent missing creative decisions, or regenerate approved assets. Director-chat generation requests remain reviewable proposals rather than direct provider submissions.
