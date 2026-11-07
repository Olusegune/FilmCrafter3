import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Sheet } from "./Sheet";
import { api, errorText, type FilmAdvice, type FilmProgress, type FilmScene, type FilmStatus, type StoryKind } from "./api";
import * as I from "./icons";
import { ask } from "./ask";
import { askForHelp } from "./AssistSheet";
import { FrameShapes } from "./FrameShapes";
import { CastWorld } from "./CastWorld";
import { ShotLab } from "./ShotLab";
import { MakeFilm, type MakeTab } from "./MakeFilm";
import { FirstFilm } from "./FirstFilm";
import { FilmRail, railSteps } from "./FilmRail";
import type { StudioSheet } from "./guideSteps";
import { NextStep } from "./NextStep";
import { SpendingSheet } from "./SpendingSheet";
import { BringMaterials } from "./BringMaterials";
import { buildSteps, doneCount, guideSeen, nextStep, requiredCount } from "./guideSteps";
import { LADDER, ladderAt, minutes, neighbours, openAdvice, sceneLine, stageBadge, stageDone, stageLabel, STAGES, STORY_KINDS, storyState } from "./storyView";

/**
 * A film's story: the script as written, the scenes found in it, and what was noticed. The script is never edited here; a change is a new version,
 * and a version can be locked so the rest of the film is made from one fixed story.
 */
export function FilmView({ dir, onHome, onSettings, onStudio, initialStage }: { dir: string; onHome: () => void; onSettings: () => void; onStudio?: (renderDir: string, sheet?: StudioSheet) => void; initialStage?: string }) {
  const [f, setF] = useState<FilmStatus | null>(null);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState("");
  const [writing, setWriting] = useState(false);
  const [scene, setScene] = useState<number | null>(null);
  const [showAll, setShowAll] = useState(false);
  const [stage, setStage] = useState<"story" | "cast" | "shots" | "make">(initialStage === "studio" || initialStage === "storyboard" ? "make" : initialStage === "cast" || initialStage === "shots" ? initialStage : "story");        // the studio can bring you back to a step
  const [makeTab, setMakeTab] = useState<MakeTab>(initialStage === "storyboard" ? "storyboard" : "keyframe");
  const [progress, setProgress] = useState<FilmProgress | null>(null);
  const [suggested, setSuggested] = useState<{ text: string; kind: StoryKind } | null>(null);          // the next step the writing helper proposed: opens in the new-version sheet to edit and save
  const [helping, setHelping] = useState(false);
  const [guide, setGuide] = useState(false);                                     // "Your first film": the order a film is made in, from what this film has
  const [costs, setCosts] = useState(false);
  const [materials, setMaterials] = useState(false);
  const [goVoice, setGoVoice] = useState(false);
  const [goSound, setGoSound] = useState(false);
  const [goPlaces, setGoPlaces] = useState(false);
  const [goShot, setGoShot] = useState<string | null>(null);                    // a shot the next-step bar or the readiness list sent you to
  const MAKE_STAGE: Record<string, MakeTab> = { make: "keyframe", export: "deliver" };
  const stageOf = (id: string) => (id in MAKE_STAGE ? "make" : id);
  const activeId = stage === "make" ? (makeTab === "deliver" ? "export" : "make") : stage;
  const reader = useRef<HTMLDivElement>(null);

  const load = useCallback((version?: number) =>
    api.film<FilmStatus>("status", dir, version ? { version } : {}).then(setF).catch((e) => setErr(errorText(e))), [dir]);
  useEffect(() => { void load(); }, [load]);
  useEffect(() => { api.film("status", dir).then(() => api.filmBackup(dir, "make", "open")).catch(() => {}); }, [dir]);       // a snapshot of the film's records when it opens (only if it read cleanly; skipped when nothing changed)
  useEffect(() => { api.make<FilmProgress>("progress", dir).then(setProgress).catch(() => {}); }, [dir, stage, makeTab, f?.story.locked, f?.story.current]);
  useEffect(() => { if (progress && !guideSeen(dir) && !progress.story.locked && progress.make.keyframe === 0 && progress.make.video === 0) setGuide(true); }, [dir, progress]);   // a brand-new film opens the guide once          // the small words under each step

  const run = async (what: string, fn: () => Promise<FilmStatus>) => {
    setBusy(what); setErr("");
    try { setF(await fn()); } catch (e) { setErr(errorText(e)); } finally { setBusy(""); }
  };

  const lines = useMemo(() => (f ? f.text.split("\n") : []), [f]);
  const headingAt = useMemo(() => new Map((f?.found.scenes ?? []).filter((s) => !s.implied).map((s) => [sceneLine(s), s])), [f]);
  const goTo = (s: FilmScene) => {
    setScene(s.number);
    reader.current?.querySelector(`[data-line="${sceneLine(s)}"]`)?.scrollIntoView({ block: "start", behavior: "smooth" });
  };

  const menuRef = useRef<(id: string) => void>(() => {});
  useEffect(() => {
    const on = (e: Event) => menuRef.current((e as CustomEvent<string>).detail);
    window.addEventListener("pf-menu", on);
    return () => window.removeEventListener("pf-menu", on);
  }, []);
  if (!f) return <div className="film"><div className="film-load dim">{err || "Opening the film…"}</div></div>;
  const st = f.story;
  const goStage = (id: string) => {
    setStage(stageOf(id) as "story" | "cast" | "shots" | "make");
    if (id === "export") setMakeTab("deliver"); else if (id === "make" && makeTab === "deliver") setMakeTab("keyframe");          // Studio keeps the tab you were on; Export is the last one
  };
  const nb = neighbours(activeId, f.mode === "studio");
  menuRef.current = (id: string) => {         // the View and File menus work from here too: Export goes to the Export step, Simple and Director mode set the film's mode
    if (id === "export") goStage("export");
    else if (id === "mode_simple" || id === "mode_director") { const m = id === "mode_simple" ? "simple" : "studio"; if (f.mode !== m) { if (m === "simple" && stage === "shots") setStage("story"); void run("mode", () => api.film<FilmStatus>("set_mode", dir, { mode: m })); } }
  };
  const isScreenplay = f.kind === "screenplay";
  const studio = f.mode === "studio";
  const toStudio = async (sheet: StudioSheet) => {                         // get the film ready for the Studio (shots, then the render project), and open it with that sheet already up
    try { await api.shots("get", dir).then(async (v) => { if (!v.shots.length) await api.shots("breakdown", dir); }); const r = await api.make<{ render_dir: string }>("sync", dir); onStudio?.(r.render_dir, sheet); } catch (e) { setErr(errorText(e)); }
  };
  const advice = openAdvice(f.advice);
  const setAside = f.advice.filter((a) => a.status !== "open");
  const shownAdvice = showAll ? advice : advice.slice(0, 3);
  const mark = (a: FilmAdvice, state: "noted" | "dismissed" | "open") => run("rec", () => api.film<FilmStatus>("rec_set", dir, { version: f.version, id: a.id, state }));

  const lock = async () => {
    if (!await ask(`Lock version ${f.version} as the story?\n\nThe rest of the film will be made from this exact version. It will never be changed: if the story changes later you write a new version and lock that one.`, { ok: "Lock the story" })) return;
    await run("lock", () => api.film<FilmStatus>("lock", dir, { version: f.version }));
  };

  const hasShots = !!progress && progress.shots.count > 0;

  return (
    <div className="film-shell">
    <FilmRail steps={railSteps({ pro: studio, progress, active: activeId, go: goStage })} onHome={onHome} onSettings={onSettings} hasShots={hasShots} onTool={(id) => { if (onStudio) void toStudio(id); }} />
    <div className="film">
      <header className="film-top">
        <button className="btn ghost sm" onClick={onHome}>‹ Home</button>
        <h1 className="film-title" title={f.title}>{f.title}</h1>
        <ol className="film-stages" aria-label="The stages of making a film">
          {STAGES.filter((s) => studio || s.id !== "shots").map((s) => { const badge = stageBadge(s.id, progress), done = stageDone(s.id, progress); return (
            <li key={s.id} className={`${s.id === activeId ? "on" : s.ready ? "ready" : ""} ${done ? "done" : ""}`} title={s.ready ? undefined : "Coming in a later update"} aria-current={s.id === activeId ? "step" : undefined}>
              {s.ready ? <button onClick={() => goStage(s.id)}>{s.label}{badge && <small>{badge}</small>}</button> : s.label}</li>); })}
        </ol>
        {onStudio && <div className="mode-toggle film-view" role="group" aria-label="How to see the film" title="The same film two ways. Cards: the story-first workspace. Timeline: the full editing studio with layers, lighting, colour match, supervisor and more.">
          <button className="on" aria-pressed="true">Cards</button>
          <button aria-pressed="false" disabled={f.kind !== "screenplay" || !!busy}
            onClick={async () => { try { await api.shots("get", dir).then(async (v) => { if (!v.shots.length) await api.shots("breakdown", dir); }); const r = await api.make<{ render_dir: string }>("sync", dir); onStudio(r.render_dir); } catch (e) { setErr(errorText(e)); } }}>Timeline</button></div>}
        <div className="mode-toggle film-mode" role="group" aria-label="Mode" title="Simple hides the detailed workspaces. It is the same film either way.">
          {(["simple", "studio"] as const).map((m) => <button key={m} className={f.mode === m ? "on" : ""} aria-pressed={f.mode === m}
            onClick={() => { if (f.mode !== m) { if (m === "simple" && stage === "shots") setStage("story"); void run("mode", () => api.film<FilmStatus>("set_mode", dir, { mode: m })); } }}>{m === "simple" ? "Simple" : "Pro"}</button>)}</div>
        <button className="btn ghost sm ff-open" onClick={() => setMaterials(true)} title="Bring a storyboard, character, pose and expression sheets, a shot list or notes" aria-label="Materials: bring a storyboard, sheets, a shot list or notes">Materials</button>
        <button className="btn ghost sm ff-open" onClick={() => setCosts(true)} title="What this film has cost so far" aria-label="Costs: what this film has cost so far">Costs</button>
        <button className="btn ghost sm ff-open" onClick={() => setGuide(true)} title="The order a film is made in, and what each step costs">
          <I.Rocket size={13} /> Guide{progress && (() => { const st = buildSteps({ progress, voices: null, sound: null, pro: f.mode === "studio", exported: false }); const n = nextStep(st); return n ? <small className="ff-badge">{doneCount(st)}/{requiredCount(st)}</small> : null; })()}</button>
        <button className="icon-btn" onClick={onSettings} title="Settings" aria-label="Settings"><I.Gear /></button>
      </header>
      <NextStep dir={dir} onPolish={onStudio ? () => void toStudio("polish") : undefined} refresh={`${stage}-${makeTab}-${progress?.make.keyframe}-${progress?.make.video}-${progress?.shots.count}-${f.story.current}`} onGo={(it) => {
        setGoVoice(it.go === "voice"); setGoSound(false); setGoPlaces(false); setGoShot(it.shot);
        goStage(it.go === "voice" ? "make" : it.go === "shots" && !studio ? "make" : it.go === "soundplan" ? "shots" : it.go);
      }} />

      {stage === "cast" ? <CastWorld key={`${dir}-${goSound}-${goPlaces}`} dir={dir} initialTab={goSound ? "sound" : goPlaces ? "environment" : undefined} /> : stage === "shots" ? <ShotLab key={`${dir}-${goShot}`} dir={dir} initial={goShot} /> : stage === "make" ? <MakeFilm key={`${dir}-${goVoice}`} dir={dir} tab={makeTab} onTab={setMakeTab} autoBreakdown={!studio} openVoice={goVoice} onOpenPlaces={() => { setGoPlaces(true); setGoSound(false); goStage("cast"); }} /> : <div className="film-body">
        <nav className="film-scenes" aria-label="Scenes">
          <h2>Scenes <span className="dim">{f.found.scenes.filter((s) => !s.implied).length || ""}</span></h2>
          {f.found.scenes.length === 0 && <p className="dim">{isScreenplay ? "No scenes found yet." : "Scenes appear once the story is a screenplay or an outline."}</p>}
          <ol>
            {f.found.scenes.map((s) => (
              <li key={s.number}>
                <button className={scene === s.number ? "on" : ""} onClick={() => goTo(s)} disabled={s.implied && f.found.scenes.length === 1}>
                  <span className="n num">{s.number}</span>
                  <span className="h" title={s.heading || "Scene"}>{s.heading || "Scene"}</span>
                  {s.seconds > 0 && <span className="dim t">{Math.round(s.seconds)}s</span>}
                </button>
              </li>))}
          </ol>
        </nav>

        <main className="film-main">
          <div className="film-readhead">
            <label className="film-version"><span className="dim">Version</span>
              <select className="text-input" value={f.version} onChange={(e) => void load(Number(e.target.value))} aria-label="Which version of the story to read">
                {f.versions.map((v) => <option key={v.version} value={v.version}>{`${v.version}${v.locked ? " · locked" : ""} · ${v.note || "—"}`}</option>)}</select></label>
            {f.version !== st.current && <button className="link" onClick={() => run("cur", () => api.film<FilmStatus>("set_current", dir, { version: f.version }))}>Make this the current version</button>}
            <div style={{ flex: 1 }} />
            <span className="dim">{f.found.words.toLocaleString()} words{f.found.seconds > 0 ? ` · ${minutes(f.found.seconds)}` : ""}</span>
          </div>
          {f.looks_broken && f.original && <p className="cw-note film-broken" role="status">This text was read one word to a line, so it can't be broken into scenes properly. Reading <b>{f.original}</b> again usually fixes it.
            <button className="btn sm" disabled={!!busy} onClick={() => run("reread", () => api.film<FilmStatus>("reread", dir, {}))}>Read the file again</button>
            <span className="dim"> The version you have stays as it is; this makes a new one.</span></p>}
          <div className={`film-script ${isScreenplay ? "sp" : "prose"}`} ref={reader} tabIndex={0} aria-label="The story, as written">
            {lines.map((l, i) => {
              const h = headingAt.get(i);
              return <div key={i} data-line={i} className={`ln ${h ? "heading" : ""} ${h && h.number === scene ? "cur" : ""}`}>{l || " "}</div>;
            })}
          </div>
        </main>

        <aside className="film-side" aria-label="The story">
          <section className={`film-state ${st.locked !== null ? "locked" : ""}`}>
            <h2>{st.locked !== null ? <><I.Check size={15} /> Story locked</> : "The story"}</h2>
            <p className="film-state-text">{storyState({ kind: f.kind, locked: st.locked, as_is: st.as_is, current: st.current })}</p>
            {isScreenplay ? <div className="film-actions">
              {st.as_is !== f.version && st.locked === null && <button className="btn" disabled={!!busy} onClick={() => run("asis", () => api.film<FilmStatus>("as_is", dir, { version: f.version }))}
                title="Set every suggestion aside. The script stays exactly as it is.">Use story as it is</button>}
              {!f.locked_here && <button className="btn primary" disabled={!!busy} onClick={lock}>Lock this version</button>}
            </div> : <Ladder kind={f.kind} onWrite={() => { setSuggested(null); setWriting(true); }} helping={helping}
              onHelp={async () => { setErr(""); setHelping(true); try { const p = await askForHelp(dir, "story", null, "the next step of your story"); if (p && typeof p.text === "string") { setSuggested({ text: p.text, kind: p.kind as StoryKind }); setWriting(true); } } catch (e) { setErr(errorText(e)); } finally { setHelping(false); } }} />}
          </section>

          <section className="film-frame">
            <h2>Frame shape</h2>
            <FrameShapes value={f.aspect_ratio} disabled={!!busy} onChange={(v) => run("aspect", () => api.film<FilmStatus>("set_aspect", dir, { aspect_ratio: v }))} />
            <p className="dim">Pictures and video are asked for in this shape from now on. What is already made stays as it was.</p>
          </section>

          {advice.length > 0 && <section className="film-advice">
            <h2>What I noticed <span className="dim">{advice.length}</span></h2>
            <p className="dim">Suggestions only. Nothing changes your story.</p>
            <ul>
              {shownAdvice.map((a) => (
                <li key={a.id}>
                  <span className="topic">{a.topic}</span>
                  <p>{a.text}</p>
                  <div className="row">
                    <button className="link" onClick={() => mark(a, "noted")}>I'll deal with it</button>
                    <button className="link" onClick={() => mark(a, "dismissed")}>Dismiss</button>
                    {a.scene && <button className="link" onClick={() => { const s = f.found.scenes.find((x) => x.number === a.scene); if (s) goTo(s); }}>Go to scene {a.scene}</button>}
                  </div>
                </li>))}
            </ul>
            {advice.length > 3 && <button className="link" onClick={() => setShowAll((v) => !v)}>{showAll ? "Show fewer" : `Show all ${advice.length}`}</button>}
          </section>}
          {setAside.length > 0 && <details className="film-aside"><summary>{setAside.length} set aside</summary>
            <ul>{setAside.map((a) => <li key={a.id}><span className="dim">{a.status === "noted" ? "To deal with" : "Dismissed"}:</span> {a.text} <button className="link" onClick={() => mark(a, "open")}>Bring back</button></li>)}</ul></details>}

          {(f.found.characters.length > 0 || f.found.locations.length > 0) && <section className="film-cast">
            {f.found.characters.length > 0 && <><h2>Characters <span className="dim">{f.found.characters.length}</span></h2>
              <div className="chips">{f.found.characters.map((c) => <span key={c.name} className="chip" title={`In ${c.scene_count} scene${c.scene_count === 1 ? "" : "s"}`}>{c.name}<i>{c.scene_count}</i></span>)}</div></>}
            {f.found.locations.length > 0 && <><h2>Places <span className="dim">{f.found.locations.length}</span></h2>
              <div className="chips">{f.found.locations.map((c) => <span key={c.name} className="chip" title={`In ${c.scenes.length} scene${c.scenes.length === 1 ? "" : "s"}`}>{c.name}<i>{c.scenes.length}</i></span>)}</div></>}
          </section>}

          <section className="film-versions">
            <h2>Versions <span className="dim">{f.versions.length}</span></h2>
            <ul>
              {[...f.versions].reverse().map((v) => (
                <li key={v.version} className={v.version === f.version ? "on" : ""}>
                  <button className="link" onClick={() => void load(v.version)}>Version {v.version}</button>
                  {v.locked && <span className="badge">locked</span>}{v.version === st.current && <span className="badge dim">current</span>}
                  <span className="dim">{v.note || v.origin} · {v.words.toLocaleString()} words</span>
                </li>))}
            </ul>
            <button className="btn ghost sm" onClick={() => setWriting(true)}>Write a new version…</button>
          </section>

          <section className="film-next"><h3>Next</h3>
            <p className="dim">Next: Cast &amp; World, Shots, then the storyboard and making the film (above). Lock the story when it is final.</p></section>
          {err && <p className="error-text" role="alert">{err}</p>}
        </aside>
      </div>}
      <footer className="film-foot">
        {nb.prev ? <button className="btn ghost sm" onClick={() => goStage(nb.prev!)}>‹ {stageLabel(nb.prev)}</button> : <span />}
        <span className="film-hint dim">{nb.hint}</span>
        {nb.next ? <button className="btn sel sm" onClick={() => goStage(nb.next!)}>{stageLabel(nb.next)} ›</button> : <span />}
      </footer>
      {materials && <BringMaterials dir={dir} onClose={() => setMaterials(false)} onDone={() => { api.make<FilmProgress>("progress", dir).then(setProgress).catch(() => {}); }} />}
      {costs && <SpendingSheet dir={dir} onClose={() => setCosts(false)} />}
      {guide && <FirstFilm dir={dir} progress={progress} pro={studio} onClose={() => setGuide(false)} onGo={(where) => {
        if (where === "materials") { setMaterials(true); return; }
        if (where.startsWith("studio:")) {                                  // a Studio sheet (presets, the Smart Editor, colour, titles): get the film ready for it, then open the Studio with that sheet already up
          void toStudio(where.slice(7) as StudioSheet);
          return;
        }
        setGoVoice(where === "voice"); setGoSound(where === "sound"); setGoPlaces(false);
        goStage(where === "voice" ? "make" : where === "sound" ? "cast" : where);
      }} />}
      {writing && <NewVersion from={f} initial={suggested} onClose={() => { setWriting(false); setSuggested(null); }} onSaved={(s) => { setF(s); setWriting(false); setScene(null); }} dir={dir} />}
    </div>
    </div>
  );
}

/** Where a story that is not a screenplay yet stands on the way to one. */
function Ladder({ kind, onWrite, onHelp, helping }: { kind: StoryKind; onWrite: () => void; onHelp: () => void; helping: boolean }) {
  const at = ladderAt(kind === "idea" ? "logline" : kind);
  return (
    <div className="film-ladder">
      <ol aria-label="From a spark to a screenplay">{LADDER.map((r, i) => <li key={r} className={i < at ? "done" : i === at ? "now" : ""} aria-current={i === at ? "step" : undefined}>{r}</li>)}</ol>
      <p className="dim">Write or paste the next step as a new version. When the screenplay is written, lock it.</p>
      <div className="film-actions"><button className="btn" onClick={onWrite}>Add the next step…</button>
        <button className="btn ghost" onClick={onHelp} disabled={helping} title="Optional: the writing helper drafts the next step from your story. You read it and edit it before it is saved as a new version."><I.Sparkle size={13} /> {helping ? "Writing…" : "Write it for me"}</button></div>
    </div>
  );
}

/** A change to the story is a new version; this is where it is written. */
function NewVersion({ dir, from, initial, onClose, onSaved }: { dir: string; from: FilmStatus; initial?: { text: string; kind: StoryKind } | null; onClose: () => void; onSaved: (s: FilmStatus) => void }) {
  const [text, setText] = useState(initial?.text ?? from.text);
  const [note, setNote] = useState(initial ? "Written with the writing helper, then edited" : "");
  const [kind, setKind] = useState<StoryKind>(initial?.kind ?? from.kind);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const save = async () => {
    setBusy(true); setErr("");
    try { onSaved(await api.film<FilmStatus>("add_version", dir, { text, note: note.trim(), kind })); } catch (e) { setErr(errorText(e)); setBusy(false); }
  };
  return (
    <Sheet label="New version" className="nf-sheet" onDismiss={busy ? undefined : onClose}>
        <div className="vs-head"><h2>New version</h2><div style={{ flex: 1 }} />
          <button className="icon-btn" onClick={onClose} aria-label="Close"><I.Close size={18} /></button></div>
        <p className="sub">The version you started from stays exactly as it is. This becomes version {from.versions.length + 1}.</p>
        <div className="nf-kind-row"><span className="dim">This is</span>
          <select className="text-input" value={kind} onChange={(e) => setKind(e.target.value as StoryKind)} aria-label="What kind of story this is">
            {STORY_KINDS.map((k) => <option key={k.id} value={k.id}>{k.label.toLowerCase()}</option>)}</select></div>
        <label className="field"><span>What changed (optional)</span><input className="text-input" value={note} onChange={(e) => setNote(e.target.value)} placeholder="e.g. Sharper ending" maxLength={300} /></label>
        <label className="field"><span>The story</span><textarea className="text-input nf-text" rows={14} value={text} onChange={(e) => setText(e.target.value)} spellCheck={false} /></label>
        {err && <p className="error-text" role="alert">{err}</p>}
        <div className="sheet-actions"><button className="btn ghost" onClick={onClose} disabled={busy}>Cancel</button>
          <button className="btn primary" onClick={save} disabled={busy || !text.trim() || text === from.text && kind === from.kind}>{busy ? "Saving…" : "Save as a new version"}</button></div>
    </Sheet>
  );
}
