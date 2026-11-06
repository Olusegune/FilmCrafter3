import { useCallback, useEffect, useMemo, useState } from "react";
import { api, errorText, type PerformPlan, type PerformPlanView, type PlanArc, type PlanEvent, type PlanPause } from "./api";

/** Where a position falls in the line, in words a person can read. Gap 0 is before the first word. */
export const gapLabel = (words: string[], g: number): string => {
  if (g <= 0) return "before the first word";
  const w = words[g - 1] ?? "";
  return g >= words.length ? `after "${w}" (the end)` : `after "${w}"`;
};

const PAUSES = [300, 600, 1000, 1500, 2500];
const BODY: [keyof PerformPlan["physical"], string][] = [["effort", "Effort"], ["breathlessness", "Breathlessness"], ["fatigue", "Tiredness"], ["pain", "Pain"]];
const GROUPS: Record<string, string> = { breathing: "Breathing", laughter: "Laughter", effort: "Effort and pain", emotion: "Emotional sounds", other: "Other" };

/** The tag list a plan used, with the ones nobody has checked marked. */
export const tagWords = (tags: string[], unverified: string[]): string => tags.map((t) => (unverified.includes(t) ? `${t} (not checked)` : t)).join(", ");

/**
 * Direct the performance of one line: what the person wants, how the feeling changes inside the line, where the breaths, laughs and efforts fall, how the body affects the voice. The plan is yours to
 * edit and is turned into words only for the model that will speak it; what that model cannot be asked for is listed, not faked. Applying it sets the line's spoken version. It never speaks or spends.
 */
export function PerformancePlanner({ dir, shotId, who, onChanged }: { dir: string; shotId: string; who: string; onChanged: () => void }) {
  const [v, setV] = useState<PerformPlanView | null>(null);
  const [p, setP] = useState<PerformPlan | null>(null);
  const [busy, setBusy] = useState("");
  const [err, setErr] = useState("");
  const [open, setOpen] = useState(false);

  const load = useCallback(() => api.performPlan("get", dir, { shot: shotId, speaker: who }).then((r) => { setV(r); setP(r.plan); }).catch((e) => setErr(errorText(e))), [dir, shotId, who]);
  useEffect(() => { if (open && !v) void load(); }, [open, v, load]);
  const go = async (label: string, f: () => Promise<void>) => { setErr(""); setBusy(label); try { await f(); } catch (e) { setErr(errorText(e)); } finally { setBusy(""); } };
  const dirty = useMemo(() => !!v && !!p && JSON.stringify(p) !== JSON.stringify(v.plan), [v, p]);

  if (!open) return <section className="ls-sec" aria-label="Direct the performance"><h3>Direct the performance</h3>
    <p className="dim ls-gap">Plan how the feeling changes inside this line, where the breaths, laughs and efforts fall, and how the body affects the voice. Free; nothing is spoken until you press Speak.</p>
    <button className="btn sm" onClick={() => setOpen(true)}>Plan the performance…</button></section>;
  if (!v || !p) return <section className="ls-sec" aria-label="Direct the performance"><h3>Direct the performance</h3>{err ? <p className="error-text" role="alert">{err}</p> : <p className="dim">Looking…</p>}</section>;

  const n = v.words.length;
  const gaps = Array.from({ length: n + 1 }, (_, g) => g);
  const set = (patch: Partial<PerformPlan>) => setP({ ...p, ...patch });
  const setArc = (i: number, patch: Partial<PlanArc>) => set({ arc: p.arc.map((a, j) => (j === i ? { ...a, ...patch } : a)) });
  const setEv = (i: number, patch: Partial<PlanEvent>) => set({ events: p.events.map((a, j) => (j === i ? { ...a, ...patch } : a)) });
  const setPause = (i: number, patch: Partial<PlanPause>) => set({ pauses: p.pauses.map((a, j) => (j === i ? { ...a, ...patch } : a)) });
  const toggleEmphasis = (w: number) => set({ emphasis: p.emphasis.includes(w) ? p.emphasis.filter((x) => x !== w) : [...p.emphasis, w].sort((a, b) => a - b) });
  const save = () => go("save", async () => { const r = await api.performPlan("set", dir, { shot: shotId, speaker: who, plan: p }); setV(r); setP(r.plan); });
  const apply = () => go("apply", async () => { const r = await api.performPlan("apply", dir, { shot: shotId, speaker: who }); setV(r); setP(r.plan); onChanged(); });
  const forget = () => go("clear", async () => { const r = await api.performPlan("clear", dir, { shot: shotId, speaker: who }); setV(r); setP(r.plan); onChanged(); });
  const c = v.compiled;
  const byGroup = Object.entries(v.events).reduce<Record<string, string[]>>((acc, [k, e]) => { (acc[e.group] ??= []).push(k); return acc; }, {});

  return (
    <section className="ls-sec pp" aria-label="Direct the performance">
      <h3>Direct the performance</h3>
      {v.stale && <p className="error-text" role="alert">The words of this line changed after this plan was made. Its positions may no longer fall where you meant. Check them, then save again.</p>}
      {c.stripped_tags > 0 && <p className="dim">The line has {c.stripped_tags} [tag]{c.stripped_tags === 1 ? "" : "s"} typed into it. The plan works from the plain words and writes its own.</p>}

      <div className="pp-words" aria-label="The words. Press a word to stress it.">{v.words.map((w, i) =>
        <button key={`${i}-${w}`} className={`ls-chip ${p.emphasis.includes(i) ? "on" : ""}`} aria-pressed={p.emphasis.includes(i)} onClick={() => toggleEmphasis(i)} title="Stress this word">{w}</button>)}</div>

      <div className="cw-fields">
        <label className="field"><span>What they want</span><input className="text-input" value={p.objective} maxLength={400} onChange={(e) => set({ objective: e.target.value })} placeholder="To stop her leaving." /></label>
        <label className="field"><span>What is under the words</span><input className="text-input" value={p.subtext} maxLength={400} onChange={(e) => set({ subtext: e.target.value })} placeholder="He is afraid she is right." /></label>
        <label className="field"><span>Feeling shown</span><input className="text-input" value={p.outward} maxLength={80} onChange={(e) => set({ outward: e.target.value })} placeholder="Calm." /></label>
        <label className="field"><span>Feeling hidden</span><input className="text-input" value={p.concealed} maxLength={80} onChange={(e) => set({ concealed: e.target.value })} placeholder="Panic." /></label>
      </div>

      <h4>How the feeling changes</h4>
      <datalist id="pp-emotions">{Object.keys(v.emotions).map((e) => <option key={e} value={e} />)}</datalist>
      {p.arc.map((a, i) => <div key={i} className="ls-btns pp-row">
        <label>From <select value={a.at} onChange={(e) => setArc(i, { at: Number(e.target.value) })}>{gaps.map((g) => <option key={g} value={g}>{gapLabel(v.words, g)}</option>)}</select></label>
        <label>Feeling <input list="pp-emotions" className="text-input" value={a.emotion} maxLength={40} onChange={(e) => setArc(i, { emotion: e.target.value })} aria-label={`Feeling ${i + 1}`} /></label>
        <label>Strength <input type="range" min={0} max={1} step={0.05} value={a.intensity} onChange={(e) => setArc(i, { intensity: Number(e.target.value) })} aria-label={`Strength of feeling ${i + 1}`} /></label>
        <button className="link" onClick={() => set({ arc: p.arc.filter((_, j) => j !== i) })} aria-label={`Remove feeling ${i + 1}`}>Remove</button></div>)}
      <button className="btn sm ghost" disabled={p.arc.length >= 12} onClick={() => set({ arc: [...p.arc, { at: p.arc.length ? Math.min(n, p.arc[p.arc.length - 1].at + 1) : 0, emotion: "neutral", intensity: 0.5 }] })}>Add a change of feeling</button>

      <h4>Sounds</h4>
      {p.events.map((e, i) => <div key={i} className="ls-btns pp-row">
        <label>Sound <select value={e.kind} onChange={(ev) => setEv(i, { kind: ev.target.value })} aria-label={`Sound ${i + 1}`}>{Object.entries(byGroup).map(([g, ks]) =>
          <optgroup key={g} label={GROUPS[g] ?? g}>{ks.map((k) => <option key={k} value={k}>{k.replace(/_/g, " ")}{v.events[k].verified ? "" : " (not checked)"}</option>)}</optgroup>)}</select></label>
        <label>Where <select value={e.after_word} onChange={(ev) => setEv(i, { after_word: Number(ev.target.value) })} aria-label={`Where sound ${i + 1} falls`}>{gaps.map((g) => <option key={g} value={g}>{gapLabel(v.words, g)}</option>)}</select></label>
        <button className="link" onClick={() => set({ events: p.events.filter((_, j) => j !== i) })} aria-label={`Remove sound ${i + 1}`}>Remove</button></div>)}
      <button className="btn sm ghost" disabled={p.events.length >= 30} onClick={() => set({ events: [...p.events, { kind: "breath", after_word: 0, intensity: 0.5 }] })}>Add a sound</button>

      <h4>Pauses</h4>
      {p.pauses.map((q, i) => <div key={i} className="ls-btns pp-row">
        <label>Pause <select value={q.after_word} onChange={(e) => setPause(i, { after_word: Number(e.target.value) })} aria-label={`Where pause ${i + 1} falls`}>{gaps.filter((g) => g > 0).map((g) => <option key={g} value={g}>{gapLabel(v.words, g)}</option>)}</select></label>
        <label>Length <select value={q.ms} onChange={(e) => setPause(i, { ms: Number(e.target.value) })} aria-label={`Length of pause ${i + 1}`}>{PAUSES.map((m) => <option key={m} value={m}>{m / 1000} s</option>)}</select></label>
        <button className="link" onClick={() => set({ pauses: p.pauses.filter((_, j) => j !== i) })} aria-label={`Remove pause ${i + 1}`}>Remove</button></div>)}
      <button className="btn sm ghost" disabled={p.pauses.length >= 20 || n < 2} onClick={() => set({ pauses: [...p.pauses, { after_word: 1, ms: 600 }] })}>Add a pause</button>

      <h4>The body</h4>
      <div className="ls-btns pp-row">
        <label>What they are doing <select value={p.physical.activity} onChange={(e) => set({ physical: { ...p.physical, activity: e.target.value } })}>{v.activities.map((a) => <option key={a} value={a}>{a}</option>)}</select></label>
        {BODY.map(([k, label]) => <label key={k}>{label} <input type="range" min={0} max={1} step={0.05} value={p.physical[k] as number} onChange={(e) => set({ physical: { ...p.physical, [k]: Number(e.target.value) } })} aria-label={label} /></label>)}
        <label>Pace <input type="range" min={0.7} max={1.2} step={0.05} value={p.pace} onChange={(e) => set({ pace: Number(e.target.value) })} aria-label="Pace" /></label>
      </div>

      <div className="ls-btns">
        <button className="btn sm" disabled={!!busy || !dirty} onClick={() => void save()}>{busy === "save" ? "Saving…" : "Save the plan"}</button>
        <label className="ov-check"><input type="checkbox" checked={p.approved} onChange={(e) => set({ approved: e.target.checked })} /> I approve this plan</label>
        {v.saved && <button className="link" disabled={!!busy} onClick={() => void forget()}>Forget the plan</button>}
      </div>

      <div className="pp-preview" aria-label="What the model will read">
        <h4>What {v.person}'s voice will read{dirty ? " (the saved plan: save to update)" : ""}</h4>
        <p className="num pp-text">{c.text}</p>
        <p className="dim">For {c.model}{c.tagged ? ", which can be directed with [tags]." : ", which would speak [tags] aloud, so none are used."} Suggested speed {c.speed}.</p>
        {c.tags.length > 0 && <p className="dim">Directions used: {tagWords(c.tags, c.unverified)}. Ones marked "not checked" have not been confirmed to do what they say; listen and retake.</p>}
        {c.not_carried.length > 0 && <div aria-label="Not carried"><p className="dim">This model cannot carry:</p><ul>{c.not_carried.map((x, i) => <li key={i}>{x.what} <span className="dim">— {x.why}</span></li>)}</ul></div>}
        <div className="ls-btns">
          <button className="btn primary" disabled={!!busy || dirty || !v.saved || !p.approved || v.stale || v.applied} onClick={() => void apply()}>{v.applied ? "This is the spoken version" : busy === "apply" ? "Setting…" : "Use as the spoken version"}</button>
          <span className="dim">{v.applied ? "Speak it below to hear it." : "Then press Speak this. The price is shown first."}</span>
        </div>
      </div>
      {err && <p className="error-text" role="alert">{err}</p>}
    </section>
  );
}
