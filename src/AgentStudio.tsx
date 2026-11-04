import { useEffect, useMemo, useState } from "react";
import { open as openDialog } from "@tauri-apps/plugin-dialog";
import { api, errorText, type AgentStudioState, type DirectorStyle, type LoadedProject } from "./api";
import { DirectorChat } from "./DirectorChat";
import "./agent-studio.css";

const STATUS: Record<string, string> = { not_started: "Not started", ready: "Ready", working: "Working", needs_approval: "Needs approval", complete: "Complete", failed: "Failed", paused: "Paused" };
const VISUAL_STYLES = [
  ["auto", "Let the agent suggest", "Best fit after reading the script"], ["cinematic", "Cinematic", "Composed, dramatic and filmic"],
  ["photoreal", "Photoreal", "Natural, grounded live action"], ["stylized-3d", "Stylized 3D", "Expressive animated characters"],
  ["2d-animation", "2D animation", "Illustrated motion and graphic shapes"], ["storybook", "Storybook", "Painterly, tactile illustration"],
  ["documentary", "Documentary", "Observational and immediate"], ["commercial", "Commercial", "Polished, clear and product-led"],
] as const;
type MediaModel = { label: string; provider: string; model: string; price_usd?: number | null };
type AudioProvider = { id: string; label: string; kind: "sfx" | "music"; cost_words: string };

export function AgentStudio({ project, onManual, onHome }: { project: LoadedProject; onManual: () => void; onHome: () => void }) {
  const [state, setState] = useState<AgentStudioState | null>(null);
  const [draft, setDraft] = useState<AgentStudioState["brief"] | null>(null);
  const [editing, setEditing] = useState(false);
  const [revision, setRevision] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [chat, setChat] = useState(false);
  const [styles, setStyles] = useState<DirectorStyle[]>([]);
  const [directorStyle, setDirectorStyle] = useState("");
  const [overnight, setOvernight] = useState<{ ready?: boolean; active?: boolean; needs_confirm?: boolean; usd?: number; label?: string } | null>(null);
  const [mediaModels, setMediaModels] = useState<{ image: MediaModel[]; video: MediaModel[] }>({ image: [], video: [] });
  const [audioProviders, setAudioProviders] = useState<AudioProvider[]>([]);
  const load = () => api.agentStudio(project.dir, "state").then((s) => { setState(s); setDraft(s.brief); }).catch((e) => setError(errorText(e)));
  useEffect(() => { void load(); }, [project.dir]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { api.directorStyle(project.dir, "list").then((r) => { setStyles(r.styles ?? []); setDirectorStyle(r.current ?? ""); }).catch(() => {}); }, [project.dir]);
  useEffect(() => { api.overnight<typeof overnight>(project.dir, "status").then(setOvernight).catch(() => {}); }, [project.dir]);
  useEffect(() => { api.routing<typeof mediaModels>(project.dir, "models").then((r) => { if (Array.isArray(r?.image) && Array.isArray(r?.video)) setMediaModels(r); }).catch(() => {}); api.audioGen<AudioProvider[]>("providers", project.dir).then((r) => { if (Array.isArray(r)) setAudioProviders(r); }).catch(() => {}); }, [project.dir]);
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
      <button className="btn ghost" onClick={() => setChat(true)}>Ask the director</button>
      <button className="btn ghost" disabled={busy} onClick={() => run(state.paused ? "resume" : "pause")}>{state.paused ? "▶ Resume" : "Ⅱ Pause"}</button>
      <span className="agent-saved">● Saved</span>
    </header>
    {!hasPlan && state.analysis?.status !== "proposed" ? <main className="agent-intake">
      <section>
        <p className="eyebrow">New production</p><h1>What should FilmCrafter make?</h1>
        <p className="agent-lead">Paste a story or describe the film. You will approve the plan before any production work begins.</p>
        <label htmlFor="agent-story">Story or idea</label>
        <textarea id="agent-story" value={draft.story} onChange={(e) => setDraft({ ...draft, story: e.target.value })} placeholder="A young artist discovers…" />
        <div className="agent-inline"><button className="btn ghost" onClick={upload}>Attach script</button><span>Nothing is generated or charged yet.</span></div>
      </section>
      <aside className="agent-setup" aria-label="Project preferences">
        <h2>Project preferences</h2><BriefFields brief={draft} setBrief={setDraft} /><ProductionModels brief={draft} setBrief={setDraft} media={mediaModels} audio={audioProviders} />
        <button className="btn hero agent-primary" disabled={busy || draft.story.trim().length < 20} onClick={async () => { const saved = await run("update_brief", draft); if (saved) await run("analyze"); }}>{busy ? "Analysing…" : "Analyse script"}</button>
        <button className="btn ghost agent-secondary" disabled={busy || draft.story.trim().length < 20} onClick={async () => { const saved = await run("update_brief", draft); if (saved) await run("create_plan"); }}>Skip analysis and create plan</button>
        <p className="agent-fine">Analysis makes optional suggestions only. Your script remains the source of truth and nothing is generated or charged.</p>
      </aside>
    </main> : !hasPlan && state.analysis?.status === "proposed" ? <main className="agent-analysis">
      <section className="analysis-main"><p className="eyebrow">Script analysis · suggestion</p><h1>{state.analysis.logline}</h1>
        <div className="analysis-tags"><span>{state.analysis.genre}</span><span>{state.analysis.tone}</span><span>{state.analysis.scenes.length} scenes</span><span>{state.analysis.characters.length} characters</span></div>
        <div className="analysis-facts"><section><h2>Character design</h2><ul>{state.analysis.characters.slice(0, 12).map((c) => <li key={c.name}><b>{c.name}</b><span>{c.role} · {c.appearance}</span><span>Wardrobe: {c.wardrobe}</span><span>Voice: {c.voice}</span></li>)}</ul></section><section><h2>Sets &amp; locations</h2><ul>{state.analysis.locations?.map((l) => <li key={l.name}><b>{l.name}</b><span>{l.design}</span><span>Light: {l.lighting}</span></li>)}</ul></section><section><h2>Scene outline</h2><ol>{state.analysis.scenes.slice(0, 10).map((s, i) => <li key={`${i}-${s.heading}`}><b>{s.heading}</b><span>{s.summary}</span></li>)}</ol></section><section><h2>Score, SFX &amp; graphics</h2><p><b>Score prompt</b><br />{state.analysis.score_prompt}</p><p><b>Sound direction</b><br />{state.analysis.sound_direction}</p><ul>{state.analysis.sfx_plan?.slice(0, 8).map((s, i) => <li key={`${i}-${s.sound}`}><b>{s.sound}</b><span>{s.scene} · {s.purpose}</span></li>)}</ul>{state.analysis.motion_graphics?.map((m, i) => <p key={`${i}-${m.text}`}><b>{m.type}:</b> “{m.text}” <span className="dim">{m.when}</span></p>)}</section></div>
        {!!state.analysis.questions.length && <div className="analysis-questions"><h2>Useful questions</h2>{state.analysis.questions.map((q) => <p key={q}>• {q}</p>)}</div>}
      </section>
      <aside className="analysis-decisions"><p className="eyebrow">You decide</p><h2>Choose a visual direction</h2><p className="dim">The agent recommends <b>{state.analysis.visual_style}</b>: {state.analysis.visual_style_reason}</p>
        <StyleCards value={draft.style === "auto" ? state.analysis.visual_style : draft.style} onChange={(style) => setDraft({ ...draft, style })} compact />
        <h2>Filmmaker craft profile <small>optional</small></h2><p className="dim">A profile influences camera, lenses, lighting, blocking and pace—not your story.</p>
        <select aria-label="Filmmaker craft profile" value={directorStyle || state.analysis.director_style_id} onChange={(e) => setDirectorStyle(e.target.value)}><option value="">No director profile</option>{styles.map((s) => <option key={s.id} value={s.id}>{s.name} · {s.region}</option>)}</select>
        {state.analysis.director_style_reason && <p className="agent-fine">Agent suggestion: {state.analysis.director_style_reason}</p>}
        <button className="btn hero agent-primary" disabled={busy} onClick={async () => { await run("update_brief", draft); if (draft.image_provider && draft.image_provider !== "auto" && draft.image_model && draft.image_model !== "auto") await api.routing(project.dir, "set", { pin: { kind: "image", provider: draft.image_provider, model: draft.image_model } }); if (draft.video_provider && draft.video_provider !== "auto" && draft.video_model && draft.video_model !== "auto") await api.routing(project.dir, "set", { pin: { kind: "video", provider: draft.video_provider, model: draft.video_model } }); await api.directorStyle(project.dir, directorStyle ? "set" : "clear", directorStyle ? { id: directorStyle } : {}); const accepted = await run("accept_analysis", { style: draft.style === "auto" ? state.analysis?.visual_style : draft.style, director_style_id: directorStyle }); if (accepted) await run("create_plan"); }}>Use choices &amp; build plan</button>
        <button className="btn ghost agent-secondary" disabled={busy} onClick={() => run("create_plan")}>Ignore suggestions &amp; build plan</button>
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
        {state.brief.checkin_mode === "autopilot" && <div className="agent-autopilot"><h3>Autopilot</h3><p>Runs unattended on ComfyUI. Cloud keyframes still show their price first.</p><button className="btn hero" disabled={busy || !overnight?.ready || overnight?.active} onClick={async () => { try { const r = await api.overnight<typeof overnight>(project.dir, "start"); setOvernight(r); if (r?.needs_confirm) setError(`Cloud keyframes need approval${r.usd != null ? ` (about $${r.usd.toFixed(2)})` : ""}. Open Manual Studio to review and confirm.`); } catch (e) { setError(errorText(e)); } }}>{overnight?.active ? "Autopilot running" : overnight?.ready ? "Start Autopilot" : "Set up ComfyUI to start"}</button></div>}
        <h3>Latest activity</h3><ul className="agent-activity">{[...state.activity].reverse().slice(0, 5).map((a) => <li key={a.id}>{a.text}</li>)}</ul>
        {state.jobs.failed > 0 && <button className="btn ghost" onClick={onManual}>Review {state.jobs.failed} failed job{state.jobs.failed === 1 ? "" : "s"}</button>}
      </aside>
    </main>}
    {error && <div className="agent-error" role="alert">{error}<button onClick={() => setError("")} aria-label="Dismiss">×</button></div>}
    {chat && <DirectorChat dir={project.dir} onClose={() => setChat(false)} onChanged={load} />}
  </div>;
}

function BriefFields({ brief, setBrief, story = false }: { brief: AgentStudioState["brief"]; setBrief: (b: AgentStudioState["brief"]) => void; story?: boolean }) {
  return <div className="agent-fields">{story && <label>Story<textarea value={brief.story} onChange={(e) => setBrief({ ...brief, story: e.target.value })} /></label>}
    <fieldset><legend>Visual style</legend><StyleCards value={brief.style} onChange={(style) => setBrief({ ...brief, style })} /></fieldset>
    <label>Target length<select value={brief.duration} onChange={(e) => setBrief({ ...brief, duration: e.target.value })}><option>30–60 seconds</option><option>1–2 minutes</option><option>3–4 minutes</option><option>5–8 minutes</option></select></label>
    <label>Aspect ratio<select value={brief.aspect} onChange={(e) => setBrief({ ...brief, aspect: e.target.value })}>{["2.39:1", "21:9", "16:9", "4:3", "1:1", "4:5", "9:16"].map((x) => <option key={x}>{x}</option>)}</select></label>
    <label>Budget limit ($)<input type="number" min="0" step="1" value={brief.budget_limit} onChange={(e) => setBrief({ ...brief, budget_limit: Number(e.target.value) })} /></label>
    <label>How should the agent work?<select value={brief.checkin_mode} onChange={(e) => setBrief({ ...brief, checkin_mode: e.target.value as typeof brief.checkin_mode })}><option value="guided">Guide me — every stage</option><option value="balanced">Collaborate — key milestones</option><option value="autopilot">Autopilot — budget and ambiguity only</option></select></label>
  </div>;
}

function StyleCards({ value, onChange, compact = false }: { value: string; onChange: (value: string) => void; compact?: boolean }) {
  return <div className={`style-cards ${compact ? "compact" : ""}`}>{VISUAL_STYLES.map(([id, title, hint]) => <button type="button" key={id} className={value === id ? "selected" : ""} aria-pressed={value === id} onClick={() => onChange(id)}><b>{title}</b><span>{hint}</span></button>)}</div>;
}

function ProductionModels({ brief, setBrief, media, audio }: { brief: AgentStudioState["brief"]; setBrief: (b: AgentStudioState["brief"]) => void; media: { image: MediaModel[]; video: MediaModel[] }; audio: AudioProvider[] }) {
  const setMedia = (kind: "image" | "video", value: string) => { const row = media[kind].find((m) => `${m.provider}|${m.model}` === value); setBrief({ ...brief, [`${kind}_provider`]: row?.provider ?? "auto", [`${kind}_model`]: row?.model ?? "auto" }); };
  const val = (kind: "image" | "video") => `${brief[`${kind}_provider` as "image_provider" | "video_provider"] ?? "auto"}|${brief[`${kind}_model` as "image_model" | "video_model"] ?? "auto"}`;
  const music = audio.filter((p) => p.kind === "music"), sfx = audio.filter((p) => p.kind === "sfx");
  return <details className="production-models" open><summary>Production models</summary><p className="agent-fine">Choose each department. “Automatic” follows Plan &amp; budget and can be changed later.</p>
    <label>Character, set &amp; keyframe images<select value={val("image")} onChange={(e) => setMedia("image", e.target.value)}><option value="auto|auto">Automatic image model</option>{media.image.map((m) => <option key={`${m.provider}|${m.model}`} value={`${m.provider}|${m.model}`}>{m.label} · {m.provider}</option>)}</select></label>
    <label>Shot video<select value={val("video")} onChange={(e) => setMedia("video", e.target.value)}><option value="auto|auto">Automatic video model</option>{media.video.map((m) => <option key={`${m.provider}|${m.model}`} value={`${m.provider}|${m.model}`}>{m.label} · {m.provider}</option>)}</select></label>
    <label>Voices<select value={brief.voice_provider ?? "elevenlabs"} onChange={(e) => setBrief({ ...brief, voice_provider: e.target.value })}><option value="elevenlabs">ElevenLabs voice design</option><option value="own">Use recorded/imported voices</option><option value="none">No dialogue generation</option></select></label>
    <label>Score / music<select value={brief.music_provider ?? "auto"} onChange={(e) => setBrief({ ...brief, music_provider: e.target.value })}><option value="auto">Automatic music model</option><option value="own">Use my music</option><option value="none">No score</option>{music.map((p) => <option key={p.id} value={p.id}>{p.label} · {p.cost_words}</option>)}</select></label>
    <label>SFX &amp; ambience<select value={brief.sfx_provider ?? "auto"} onChange={(e) => setBrief({ ...brief, sfx_provider: e.target.value })}><option value="auto">Automatic SFX model</option><option value="library">Use my sound library first</option><option value="none">No generated SFX</option>{sfx.map((p) => <option key={p.id} value={p.id}>{p.label} · {p.cost_words}</option>)}</select></label>
  </details>;
}
