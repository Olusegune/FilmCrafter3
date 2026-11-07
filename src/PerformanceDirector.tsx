import { useCallback, useEffect, useState } from "react";
import { api, errorText, type Breakdown, type CastProfiles, type EmotionalArc, type KindOptions, type NudgeState, type PField, type SceneBreakdown } from "./api";
import * as I from "./icons";

/**
 * The Performance Director's workspace, in the Acting sheet: what each scene is for and what each person wants and hides (a draft made on this computer from the film), and what a person is
 * like. Free and local. A draft is shown as a draft; only what you write or keep reaches a prompt, and your story is never changed.
 */

const SCENE_FIELDS: { id: "purpose" | "start" | "end" | "tension"; label: string; hint: string }[] = [
  { id: "purpose", label: "What this scene is for", hint: "Why the story needs it." },
  { id: "start", label: "How it begins", hint: "The feeling the scene opens on." },
  { id: "end", label: "How it ends", hint: "The feeling it leaves behind." },
  { id: "tension", label: "Tension between people", hint: "What is between them that they do not say." },
];
const PERSON_FIELDS: { id: "wants" | "obstacle" | "outward" | "inner" | "hiding"; label: string; hint: string }[] = [
  { id: "wants", label: "Wants", hint: "What they are trying to get in this scene." },
  { id: "obstacle", label: "Stands in the way", hint: "What stops them." },
  { id: "outward", label: "Shows", hint: "What anyone watching would see." },
  { id: "inner", label: "Feels", hint: "What is really going on inside." },
  { id: "hiding", label: "Hides", hint: "What they do not want seen." },
];
export const PROFILE_FIELDS: { id: string; label: string; hint: string }[] = [
  { id: "personality", label: "Core personality", hint: "Who they are, in a few words." },
  { id: "desire", label: "What they want", hint: "Their longer goal." },
  { id: "fears", label: "Fears and vulnerabilities", hint: "What could hurt them." },
  { id: "triggers", label: "What sets them off", hint: "A word, a person, a place." },
  { id: "contradictions", label: "Contradictions", hint: "Where they are not what they seem." },
  { id: "defenses", label: "How they protect themselves", hint: "Humour, silence, politeness, anger." },
  { id: "speech_rhythm", label: "How they speak", hint: "Short bursts, long pauses, trailing off." },
  { id: "carriage", label: "How they carry themselves", hint: "Upright, folded in, always moving." },
  { id: "stress", label: "Under stress", hint: "What changes when they are pressed." },
  { id: "state_now", label: "How they are right now", hint: "Where the story finds them." },
];

/** One piece of the breakdown: the words, whether they are a draft or yours, and the three things you can do. */
export function FieldRow({ id, label, hint, field, onSave, onReset, onKeep, busy }: {
  id: string; label: string; hint?: string; field: PField; onSave: (v: string) => void; onReset: () => void; onKeep: () => void; busy?: boolean;
}) {
  const [text, setText] = useState(field.value);
  useEffect(() => setText(field.value), [field.value, field.source]);
  const dirty = text !== field.value;
  const mine = field.source === "you";
  return (
    <div className={`pd-field ${mine ? "mine" : "draft"}`}>
      <div className="pd-field-head">
        <label htmlFor={`pd-${id.replace(/[^A-Za-z0-9_-]+/g, "_")}`}>{label}</label>
        <span className={`pd-badge ${mine ? "mine" : ""}`} title={mine ? "Written or kept by you: this can reach the prompts" : field.value ? `A draft${field.from ? ` from ${field.from}` : ""}: it is not used until you keep it` : "Nothing written yet"}>
          {mine ? "Yours" : field.value ? "Draft" : "Empty"}</span>
      </div>
      <textarea id={`pd-${id.replace(/[^A-Za-z0-9_-]+/g, "_")}`} rows={2} className="text-input" value={text} maxLength={400} placeholder={hint} aria-label={label} onChange={(e) => setText(e.target.value)} />
      <div className="pd-field-actions">
        {dirty && <button type="button" className="btn small primary" disabled={busy} onClick={() => onSave(text)}>Save</button>}
        {!dirty && !mine && field.value && <button type="button" className="btn small" disabled={busy} onClick={onKeep} title="Keep the draft as your own words">Keep this</button>}
        {!dirty && mine && <button type="button" className="btn small ghost" disabled={busy} onClick={onReset} title="Go back to the draft">Back to the draft</button>}
        {dirty && <button type="button" className="btn small ghost" onClick={() => setText(field.value)}>Undo</button>}
      </div>
    </div>
  );
}

const SURE = { low: "A guess", medium: "A reading", high: "Yours" } as const;

export function SceneNotes({ dir, onChanged }: { dir: string; onChanged?: () => void }) {
  const [data, setData] = useState<Breakdown | null>(null);
  const [sel, setSel] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  useEffect(() => { let live = true; api.performanceDirector<Breakdown>(dir, "breakdown_get").then((r) => { if (live) { setData(r); setSel((s) => s ?? r.scenes[0]?.number ?? null); } }).catch((e) => live && setErr(errorText(e))); return () => { live = false; }; }, [dir]);
  const act = async (action: "breakdown_set" | "breakdown_reset" | "breakdown_accept", path: string, value?: string) => {
    if (sel === null) return;
    setBusy(true); setErr("");
    try {
      const scene = await api.performanceDirector<SceneBreakdown>(dir, action, { scene: sel, path, ...(value !== undefined ? { value } : {}) });
      setData((d) => (d ? { ...d, scenes: d.scenes.map((s) => (s.number === scene.number ? scene : s)) } : d));
      onChanged?.();
    } catch (e) { setErr(errorText(e)); } finally { setBusy(false); }
  };
  if (!data) return err ? <p className="error-text" role="alert">{err}</p> : <p className="dim">Loading…</p>;
  if (!data.scenes.length) return <p className="dim">The film has no scenes to read yet. Make the shots first.</p>;
  const sc = data.scenes.find((s) => s.number === sel) ?? data.scenes[0];
  const check = (s: SceneBreakdown) => s.subtext.filter((x) => x.means.source === "auto").length;
  const row = (label: string, hint: string, field: PField, path: string) => (
    <FieldRow key={path} id={`${sc.number}-${path}`} label={label} hint={hint} field={field} busy={busy} onSave={(v) => act("breakdown_set", path, v)} onReset={() => act("breakdown_reset", path)} onKeep={() => act("breakdown_accept", path)} />);
  return (
    <div className="pd-grid">
      <nav className="pd-nav" aria-label="Scenes">
        {data.scenes.map((s) => (
          <button key={s.number} type="button" className={s.number === sc.number ? "on" : ""} aria-current={s.number === sc.number ? "true" : undefined} onClick={() => setSel(s.number)}>
            <span className="num">{s.number}</span><span className="pd-nav-t" title={s.heading}>{s.heading}</span>
            {check(s) > 0 && <span className="pd-flag" title={`${check(s)} line${check(s) === 1 ? "" : "s"} that may mean more than they say`}>{check(s)}</span>}
          </button>))}
      </nav>
      <div className="pd-body">
        <h3 className="perf-h">Scene {sc.number}: {sc.heading}</h3>
        <p className="dim pd-intro">A draft made on this computer from your shots; nothing here changes your story. Only what you write or keep is used when pictures and video are made.{!data.has_contracts && " This project has no story breakdown, so less could be read."}</p>
        {err && <p className="error-text" role="alert">{err}</p>}
        <div className="pd-scene">{SCENE_FIELDS.map((f) => row(f.label, f.hint, sc.fields[f.id], f.id))}</div>
        {sc.people.length > 0 && <h4 className="pd-h">The people in it</h4>}
        {sc.people.map((p) => (
          <section key={p.name} className="pd-person" aria-label={p.name}>
            <h5>{p.name}</h5>
            <div className="pd-person-grid">{PERSON_FIELDS.map((f) => row(f.label, f.hint, p[f.id], `people.${p.name}.${f.id}`))}</div>
          </section>))}
        {sc.subtext.length > 0 && <>
          <h4 className="pd-h">What is said, and what may be meant</h4>
          <p className="dim">The words are shown exactly as written and are never changed.</p>
          {sc.subtext.map((s) => (
            <section key={s.id} className="pd-said" aria-label={`${s.person || "Line"}: ${s.says}`}>
              <blockquote><b>{s.person}</b> “{s.says}” <span className="dim num">{s.shot}</span></blockquote>
              <p className="dim pd-why"><span className={`pd-sure ${s.confidence}`}>{SURE[s.confidence]}</span> {s.why}</p>
              {row("May mean", "In your own words, what is really being said.", s.means, `subtext.${s.id}`)}
            </section>))}
        </>}
        {(sc.turning_points.length > 0 || sc.nonverbal.length > 0 || sc.reactions.length > 0) && <h4 className="pd-h">Moments to know about</h4>}
        {sc.turning_points.length > 0 && <ul className="pd-list" aria-label="Turning points">{sc.turning_points.map((t, i) => <li key={i}><span className="num pd-shot">{t.shot}</span> <b>Turn</b> {t.person}: {t.what}</li>)}</ul>}
        {sc.nonverbal.length > 0 && <ul className="pd-list" aria-label="Moments without words">{sc.nonverbal.map((t, i) => <li key={i}><span className="num pd-shot">{t.shot}</span> <b>No words</b> {t.what}</li>)}</ul>}
        {sc.reactions.length > 0 && <ul className="pd-list" aria-label="Reactions">{sc.reactions.map((t, i) => <li key={i}><span className="num pd-shot">{t.shot}</span> <b>Reaction</b> {t.person} {t.what}</li>)}</ul>}
      </div>
    </div>
  );
}

export function PeopleProfiles({ dir, onChanged }: { dir: string; onChanged?: () => void }) {
  const [data, setData] = useState<CastProfiles | null>(null);
  const [sel, setSel] = useState<string | null>(null);
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [kinds, setKinds] = useState<KindOptions["kinds"] | null>(null);
  const apply = useCallback((r: CastProfiles) => { setData(r); setSel((s) => (s && r.people.some((p) => p.name === s) ? s : r.people[0]?.name ?? null)); setDraft({}); }, []);
  useEffect(() => { let live = true; api.performanceDirector<CastProfiles>(dir, "characters_get").then((r) => live && apply(r)).catch((e) => live && setErr(errorText(e))); return () => { live = false; }; }, [dir, apply]);
  useEffect(() => { api.performanceDirector<KindOptions>(dir, "kind_options").then((r) => setKinds(Array.isArray(r?.kinds) ? r.kinds : [])).catch(() => setKinds([])); }, [dir]);
  const call = async (action: "character_set" | "character_clear", fields?: Record<string, string>) => {
    if (!sel) return;
    setBusy(true); setErr("");
    try { apply(await api.performanceDirector<CastProfiles>(dir, action, { person: sel, ...(fields ? { fields } : {}) })); onChanged?.(); } catch (e) { setErr(errorText(e)); } finally { setBusy(false); }
  };
  if (!data) return err ? <p className="error-text" role="alert">{err}</p> : <p className="dim">Loading…</p>;
  if (!data.people.length) return <p className="dim">The film has no people yet. Add them in Cast &amp; World.</p>;
  const p = data.people.find((x) => x.name === sel) ?? data.people[0];
  const shown = (k: string) => draft[k] ?? p.profile[k] ?? "";
  const dirty = Object.keys(draft).some((k) => draft[k] !== (p.profile[k] ?? ""));
  const filled = (x: typeof p) => Object.values(x.profile).filter(Boolean).length;
  const known = Object.entries(p.known).filter(([, v]) => typeof v === "string" && v) as [string, string][];
  return (
    <div className="pd-grid">
      <nav className="pd-nav" aria-label="People">
        {data.people.map((x) => (
          <button key={x.name} type="button" className={x.name === p.name ? "on" : ""} aria-current={x.name === p.name ? "true" : undefined} onClick={() => { setSel(x.name); setDraft({}); }}>
            <span className="pd-nav-t">{x.name}</span>{filled(x) > 0 && <span className="pd-flag mine" title="Fields you have filled in">{filled(x)}</span>}
          </button>))}
      </nav>
      <div className="pd-body">
        <h3 className="perf-h">About {p.name}</h3>
        <p className="dim pd-intro">What a person wants, fears and hides colours how they are played. Everything here is optional and written only by you; a short line from it goes into the prompts of the shots they are in.</p>
        {err && <p className="error-text" role="alert">{err}</p>}
        {(known.length > 0 || p.style || p.gestures.length > 0) && (
          <section className="pd-known" aria-label={`What the cast already says about ${p.name}`}>
            <h4 className="pd-h">Already in the cast</h4>
            <dl>
              {known.map(([k, v]) => <div key={k}><dt>{k.replace("_", " ")}</dt><dd>{v}</dd></div>)}
              {p.style && <div><dt>acting style</dt><dd>{p.style} <span className="dim">(change it under Style &amp; arcs)</span></dd></div>}
              {p.gestures.length > 0 && <div><dt>signature gestures</dt><dd>{p.gestures.map((g) => `when ${g.when}: ${g.do}`).join("; ")}</dd></div>}
            </dl>
          </section>)}
        <label className="pd-pf pd-kind">
          <span>What kind of character</span>
          <select className="text-input" value={p.profile.kind ?? ""} disabled={busy} aria-label="What kind of character" onChange={(e) => call("character_set", { kind: e.target.value })}>
            <option value="">Not set (treated as a person)</option>
            {(kinds ?? []).map((k) => <option key={k.id} value={k.id}>{k.label}</option>)}
          </select>
          <span className="dim">An animal, a robot or a creature is acted with ears, posture and pace, not a human face. Only what you choose here is used.</span>
        </label>
        <div className="pd-profile">
          {PROFILE_FIELDS.map((f) => (
            <label key={f.id} className="pd-pf">
              <span>{f.label}</span>
              <textarea rows={2} className="text-input" maxLength={320} value={shown(f.id)} placeholder={f.hint} onChange={(e) => setDraft({ ...draft, [f.id]: e.target.value })} />
            </label>))}
        </div>
        <div className="pd-field-actions">
          <button type="button" className="btn small primary" disabled={busy || !dirty} onClick={() => call("character_set", Object.fromEntries(Object.keys(draft).filter((k) => draft[k] !== (p.profile[k] ?? "")).map((k) => [k, draft[k]])))}>Save {p.name}</button>
          {filled(p) > 0 && <button type="button" className="btn small ghost" disabled={busy} onClick={() => call("character_clear")}>Clear everything for {p.name}</button>}
        </div>
      </div>
    </div>
  );
}

/** In a shot's panel: the named choices that add one specific piece of direction (More restrained, Hold the reaction longer...). */
export function NudgeRow({ dir, shotId, onChanged }: { dir: string; shotId: string; onChanged?: () => void }) {
  const [st, setSt] = useState<NudgeState | null>(null);
  const [err, setErr] = useState("");
  useEffect(() => { let live = true; setSt(null); api.performanceDirector<NudgeState>(dir, "nudges_get", { shot: shotId }).then((r) => live && setSt(r)).catch((e) => live && setErr(errorText(e))); return () => { live = false; }; }, [dir, shotId]);
  const press = async (id: string, level: number, levels: number) => {
    setErr("");
    try { setSt(await api.performanceDirector<NudgeState>(dir, "nudge_set", { shot: shotId, nudge: id, level: level >= levels ? 0 : level + 1 })); onChanged?.(); } catch (e) { setErr(errorText(e)); }
  };
  if (!st) return err ? <p className="error-text" role="alert">{err}</p> : null;
  return (
    <section className="pd-nudges" aria-label="Direction for this shot">
      <div className="beats-head"><I.Sparkle size={16} /> <b>Direction for this shot</b> <span className="dim">free · adds one clear instruction each</span></div>
      <div className="pd-nudge-row" role="group" aria-label="Nudges">
        {st.nudges.map((n) => (
          <button key={n.id} type="button" className={`pd-nudge ${n.level ? "on" : ""}`} aria-pressed={n.level > 0} onClick={() => press(n.id, n.level, n.levels)}>
            {n.label}{n.levels > 1 && n.level > 0 ? ` · ${"●".repeat(n.level)}` : ""}</button>))}
      </div>
      {err && <p className="error-text" role="alert">{err}</p>}
    </section>
  );
}

const FLAG_NAME: Record<string, string> = { abrupt: "A sudden change", flat: "Stays the same", nonstop: "Full strength for long", unrested: "Drops with no step" };

/** Where each person's feeling goes from scene to scene, and the few places worth a look. Each can be dismissed; nothing is changed by looking. */
export function ArcFlags({ dir }: { dir: string }) {
  const [data, setData] = useState<EmotionalArc | null>(null);
  const [err, setErr] = useState("");
  const load = useCallback(() => api.performanceDirector<EmotionalArc>(dir, "continuity_get").then(setData).catch((e) => setErr(errorText(e))), [dir]);
  useEffect(() => { void load(); }, [load]);
  const dismiss = async (flag: string, undo = false) => { setErr(""); try { setData(await api.performanceDirector<EmotionalArc>(dir, "continuity_dismiss", { flag, undo })); } catch (e) { setErr(errorText(e)); } };
  if (!data) return err ? <p className="error-text" role="alert">{err}</p> : <p className="dim">Loading…</p>;
  const withArc = data.people.filter((p) => p.track.length > 0);
  if (!withArc.length) return <p className="dim">Write each person's feeling for at least two scenes above, and the places where it jumps, stalls or never rests are pointed out here.</p>;
  const flagged = withArc.reduce((n, p) => n + p.flags.length, 0);
  return (
    <section className="pd-arcflags" aria-label="Emotional arc check">
      <h4 className="pd-h">Worth a look {flagged > 0 ? <span className="pd-flag mine" title="Places to look at">{flagged}</span> : null}</h4>
      {err && <p className="error-text" role="alert">{err}</p>}
      {flagged === 0 && <p className="dim">Nothing stands out: no sudden jumps, long stalls or stretches at full strength. This only reads the feelings you wrote; it cannot say a performance is right.</p>}
      {withArc.map((p) => p.flags.length > 0 && (
        <div key={p.name} className="pd-flaglist"><b>{p.name}</b>
          <ul>{p.flags.map((f) => (
            <li key={f.id}><span className="pd-flagkind">{FLAG_NAME[f.kind] ?? f.kind}</span> {f.message}{" "}
              <button type="button" className="btn small ghost" aria-label={`Dismiss: ${f.message}`} onClick={() => dismiss(f.id)}>Dismiss</button></li>))}</ul></div>))}
      {data.dismissed.length > 0 && <p className="dim">{data.dismissed.length} dismissed. <button type="button" className="link" onClick={async () => { for (const id of data.dismissed) await dismiss(id, true); }}>Show them again</button></p>}
    </section>
  );
}
