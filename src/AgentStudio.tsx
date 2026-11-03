import { useEffect, useMemo, useState } from "react";
import { open as openDialog } from "@tauri-apps/plugin-dialog";
import { api, errorText, type AgentStudioState, type LoadedProject } from "./api";
import "./agent-studio.css";

const STATUS: Record<string, string> = { not_started: "Not started", ready: "Ready", working: "Working", needs_approval: "Needs approval", complete: "Complete", failed: "Failed", paused: "Paused" };

export function AgentStudio({ project, onManual, onHome }: { project: LoadedProject; onManual: () => void; onHome: () => void }) {
  const [state, setState] = useState<AgentStudioState | null>(null);
  const [draft, setDraft] = useState<AgentStudioState["brief"] | null>(null);
  const [editing, setEditing] = useState(false);
  const [revision, setRevision] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const load = () => api.agentStudio(project.dir, "state").then((s) => { setState(s); setDraft(s.brief); }).catch((e) => setError(errorText(e)));
  useEffect(() => { void load(); }, [project.dir]); // eslint-disable-line react-hooks/exhaustive-deps
  const run = async (action: Parameters<typeof api.agentStudio>[1], data: Record<string, unknown> = {}) => {
    setBusy(true); setError("");
    try { const s = await api.agentStudio(project.dir, action, data); setState(s); setDraft(s.brief); return s; }
    catch (e) { setError(errorText(e)); return null; }
    finally { setBusy(false); }
  };
  const current = state?.stages.find((s) => s.id === state.current) ?? state?.stages[0];
  const hasPlan = !!state?.stages.some((s) => s.state !== "not_started");
  const thumbs = useMemo(() => {
    const jobs = [...(project.jobs ?? [])].filter((j) => j.state === "ready" && j.output).sort((a, b) => b.updated - a.updated).slice(0, 3);
    return jobs.map((j) => ({ id: j.id, shot: j.shot_id, src: api.mediaUrl(`${project.dir}/${j.output}`) }));
  }, [project]);
  if (!state || !draft) return <div className="agent-loading" role="status">Opening Agent Studio…</div>;

  const saveBrief = async () => { if (await run("update_brief", draft)) setEditing(false); };
  const upload = async () => {
    const f = await openDialog({ multiple: false, filters: [{ name: "Story or script", extensions: ["txt", "md", "pdf", "docx", "fountain"] }] });
    if (typeof f === "string") setError("The script is attached to the project in Manual Studio. Paste its story text here so Agent Studio can plan from it.");
  };
  return <div className="agent-shell">
    <header className="agent-header">
      <button className="agent-brand" onClick={onHome}>FilmCrafter</button><span className="agent-divider" />
      <span className="agent-project">Project: <b>{project.project.title}</b></span>
      <div className="agent-switch" role="group" aria-label="Workspace">
        <button className="on" aria-pressed="true">Agent Studio</button><button onClick={onManual}>Manual Studio</button>
      </div>
      <button className="btn ghost" disabled={busy} onClick={() => run(state.paused ? "resume" : "pause")}>{state.paused ? "▶ Resume" : "Ⅱ Pause"}</button>
      <span className="agent-saved">● Saved</span>
    </header>
    {!hasPlan ? <main className="agent-intake">
      <section>
        <p className="eyebrow">New production</p><h1>What should FilmCrafter make?</h1>
        <p className="agent-lead">Paste a story or describe the film. You will approve the plan before any production work begins.</p>
        <label htmlFor="agent-story">Story or idea</label>
        <textarea id="agent-story" value={draft.story} onChange={(e) => setDraft({ ...draft, story: e.target.value })} placeholder="A young artist discovers…" />
        <div className="agent-inline"><button className="btn ghost" onClick={upload}>Attach script</button><span>Nothing is generated or charged yet.</span></div>
      </section>
      <aside className="agent-setup" aria-label="Project preferences">
        <h2>Project preferences</h2><BriefFields brief={draft} setBrief={setDraft} />
        <button className="btn hero agent-primary" disabled={busy || draft.story.trim().length < 20} onClick={async () => { const saved = await run("update_brief", draft); if (saved) await run("create_plan"); }}>Create production plan</button>
        <p className="agent-fine">This creates a plan only. Every paid batch still shows its scope and price for confirmation.</p>
      </aside>
    </main> : <main className="agent-workspace">
      <aside className="agent-brief">
        <h2>Creative brief</h2>{editing ? <><BriefFields brief={draft} setBrief={setDraft} story /><div className="agent-inline"><button className="btn hero" onClick={saveBrief}>Save brief</button><button className="btn ghost" onClick={() => { setDraft(state.brief); setEditing(false); }}>Cancel</button></div></> : <>
          <p className="agent-story-summary">{state.brief.story || "Story already stored with this project."}</p>
          <dl><dt>Visual style</dt><dd>{state.brief.style}</dd><dt>Target length</dt><dd>{state.brief.duration}</dd><dt>Aspect ratio</dt><dd>{state.brief.aspect}</dd><dt>Check-ins</dt><dd>{state.brief.checkin_mode}</dd></dl>
          <button className="btn ghost" onClick={() => setEditing(true)}>Edit brief</button></>}
        <div className="agent-budget"><h3>Budget</h3><div><b>${state.spending.limit.toFixed(2)} limit</b><span>${state.spending.actual.toFixed(2)} spent</span></div><div><span>${state.spending.committed.toFixed(2)} committed</span><span>{state.jobs.working} running</span></div></div>
      </aside>
      <section className="agent-current">
        <p className="eyebrow">Current check-in</p><h1>{current?.state === "needs_approval" ? "Review before FilmCrafter continues" : current?.label}</h1>
        <div className="agent-progress" aria-label="Production progress">{state.stages.slice(0, 5).map((s) => <span key={s.id} className={s.state} title={`${s.label}: ${STATUS[s.state]}`} />)}</div>
        <div className="agent-review">
          <div><h2>{current?.label}</h2><p>{current?.id === "story" ? "Your brief and production sequence are ready. Approving this records the checkpoint; it does not spend money." : current?.state === "ready" ? "This stage is ready to prepare. Open Manual Studio for precise shot and asset controls, then return here to review progress." : "Review the real project assets below. Approved work is preserved when you request a change."}</p></div>
          {thumbs.length ? <div className="agent-previews">{thumbs.map((t) => <figure key={t.id}><img src={t.src} alt={`Preview for ${t.shot}`} /><figcaption>{t.shot}</figcaption></figure>)}</div> : <div className="agent-empty-preview"><b>{state.existing.shots || 0} shots in this project</b><span>{current?.id === "story" ? "The plan uses your existing project and approved work." : "Generated previews will appear here as they finish."}</span></div>}
          <div className="agent-actions">{current?.state === "needs_approval" ? <button className="btn hero" disabled={busy || state.paused} onClick={() => run("approve", { stage: current.id, asset_versions: thumbs.map((x) => x.id) })}>Approve &amp; continue</button> : <button className="btn hero" onClick={onManual}>Open in Manual Studio</button>}<button className="btn ghost" onClick={() => document.getElementById("agent-revision")?.focus()}>Request changes</button></div>
          <div className="agent-revision"><label htmlFor="agent-revision">Ask for a focused change</label><div><input id="agent-revision" value={revision} onChange={(e) => setRevision(e.target.value)} placeholder="Make the lighting warmer…" /><button aria-label="Send revision" disabled={!revision.trim() || busy} onClick={async () => { if (await run("request_changes", { stage: current?.id, note: revision, affected: [] })) setRevision(""); }}>→</button></div><small>Before paid revision work runs, FilmCrafter will show affected assets, downstream changes and price.</small></div>
        </div>
      </section>
      <aside className="agent-plan"><h2>Production plan</h2><ol>{state.stages.map((s) => <li key={s.id} className={s.id === state.current ? "current" : ""}><span className={`agent-status ${s.state}`} aria-hidden="true" /><div><b>{s.label}</b><small>{STATUS[s.state]}</small></div></li>)}</ol>
        <h3>Latest activity</h3><ul className="agent-activity">{[...state.activity].reverse().slice(0, 5).map((a) => <li key={a.id}>{a.text}</li>)}</ul>
        {state.jobs.failed > 0 && <button className="btn ghost" onClick={onManual}>Review {state.jobs.failed} failed job{state.jobs.failed === 1 ? "" : "s"}</button>}
      </aside>
    </main>}
    {error && <div className="agent-error" role="alert">{error}<button onClick={() => setError("")} aria-label="Dismiss">×</button></div>}
  </div>;
}

function BriefFields({ brief, setBrief, story = false }: { brief: AgentStudioState["brief"]; setBrief: (b: AgentStudioState["brief"]) => void; story?: boolean }) {
  return <div className="agent-fields">{story && <label>Story<textarea value={brief.story} onChange={(e) => setBrief({ ...brief, story: e.target.value })} /></label>}
    <label>Visual style<input value={brief.style} onChange={(e) => setBrief({ ...brief, style: e.target.value })} /></label>
    <label>Target length<select value={brief.duration} onChange={(e) => setBrief({ ...brief, duration: e.target.value })}><option>30–60 seconds</option><option>1–2 minutes</option><option>3–4 minutes</option><option>5–8 minutes</option></select></label>
    <label>Aspect ratio<select value={brief.aspect} onChange={(e) => setBrief({ ...brief, aspect: e.target.value })}>{["2.39:1", "21:9", "16:9", "4:3", "1:1", "4:5", "9:16"].map((x) => <option key={x}>{x}</option>)}</select></label>
    <label>Budget limit ($)<input type="number" min="0" step="1" value={brief.budget_limit} onChange={(e) => setBrief({ ...brief, budget_limit: Number(e.target.value) })} /></label>
    <label>Check-ins<select value={brief.checkin_mode} onChange={(e) => setBrief({ ...brief, checkin_mode: e.target.value as typeof brief.checkin_mode })}><option value="guided">Guided — every stage</option><option value="balanced">Balanced — key milestones</option><option value="custom">Custom</option></select></label>
  </div>;
}
