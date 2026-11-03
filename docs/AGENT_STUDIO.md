# Agent Studio

Agent Studio is the guided face of the same FilmCrafter project used by Manual Studio. It is not a second render engine and it does not copy assets. The hybrid design keeps automated production understandable while preserving every existing shot-level control.

## Why a hybrid workspace

A permanently open assistant would compete with the film and timeline. A completely separate automatic product would split project state and make recovery dangerous. Agent Studio is therefore a focused workspace for the creative brief, production sequence, approvals, budget and recovery; **Manual Studio** remains the precision editor. The switch in either workspace preserves the project and current jobs.

The tradeoff is that the first slice deliberately orchestrates rather than autonomously renders. A stage that needs detailed preparation opens Manual Studio. This is safer than introducing a second queue, approval system or spending path.

## Optional director style

In Manual Studio, choose **Director style** to browse the worldwide filmmaker library. The detail pane explains camera and lens behaviour, lighting, colour, editing rhythm, movement, design and performance. This layer is optional and can be cleared at any time. It does not select or replace the film's visual look, rewrite the story, alter timing, change who appears or regenerate approved work. FilmCrafter stores the selected name for attribution in the interface, but generation providers receive only the bounded craft traits.

## Using it

1. Open a render project in Studio and choose **Agent Studio**.
2. Paste a story or idea, then choose a visual style, target length, aspect ratio, budget limit and check-in frequency.
3. Choose **Create production plan**. This is local and free.
4. Review the current milestone. **Approve & continue** records an explicit approval tied to the asset versions shown. Silence never approves anything.
5. Use **Request changes** for a focused revision. The request is recorded without replacing approved work. Paid revision execution still shows affected scope and price in FilmCrafter's existing confirmation UI.
6. Choose **Manual Studio** whenever an individual shot, take, reference, sound or edit needs precise control.

## Safety and recovery

- Workflow state is written atomically to `agent-studio.json` inside the project and reloads after a restart.
- Pause prevents Agent Studio from advancing upcoming work. Provider jobs already submitted can still finish or incur their confirmed charge, and the interface says so.
- Actual completed costs, committed active-job estimates and the user's limit are separate values.
- Agent Studio has no provider-submission command. Paid jobs continue to require the existing short-lived, single-use spend token bound to the displayed batch.
- Approvals and revision requests are append-only records. A revision does not erase earlier approvals, takes or assets.

## Current limitation

This release provides the persistent shell, story intake, plan, checkpoints, budget status, pause/restart recovery, activity history and Manual Studio handoff. Automatic dependency expansion, affected-asset previews for natural-language revisions, budget reservation across a newly proposed Agent batch, and automatic execution of the next confirmed stage remain to be connected to the existing generation commands. Until then, Agent Studio routes detailed production work to Manual Studio and never claims unsupported work is running.
