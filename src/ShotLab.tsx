import { useCallback, useEffect, useState } from "react";
import { SoundCut } from "./SoundCut";
import { PacingSheet } from "./PacingSheet";
import { SoundPlan } from "./SoundPlan";
import { CompositionGuide } from "./CompositionGuide";
import { ProductionModePicker } from "./ProductionMode";
import { ActionChoreo } from "./ActionChoreo";
import { Sheet } from "./Sheet";
import { api, errorText, type BibleView, type ShotBeat, type ShotContract, type ShotsView, type ShotSuggestion } from "./api";
import { ask } from "./ask";
import { FilmContinuity } from "./FilmContinuity";
import { BlockingPlan } from "./BlockingPlan";
import { askForHelp } from "./AssistSheet";
import { ShotSuggestionSheet } from "./ShotSuggestionSheet";
import { VoiceoverPanel } from "./VoiceoverPanel";
import * as I from "./icons";

type Tab = "story" | "acting" | "camera" | "blocking" | "light" | "voice" | "continuity";
const TABS: { id: Tab; label: string }[] = [{ id: "story", label: "Story" }, { id: "acting", label: "Acting" }, { id: "camera", label: "Camera" }, { id: "blocking", label: "Blocking" }, { id: "light", label: "Light" }, { id: "voice", label: "Voice" }, { id: "continuity", label: "Continuity" }];
const DOF_LABEL: Record<string, string> = { "very shallow": "Very shallow (about f/1.4): only the eyes are sharp", shallow: "Shallow (about f/2.8): the subject sharp, the background soft", medium: "Medium (about f/5.6)", deep: "Deep (about f/11): everything sharp" };
const BEAT: [keyof ShotBeat, string][] = [["character", "Who"], ["what", "What we see"], ["want", "Wants"], ["need", "Needs"], ["fear", "Fears"], ["hiding", "Hiding"], ["subtext", "Subtext"], ["start", "Starts feeling"], ["turn", "Turns to"], ["end", "Ends feeling"]];
const EMPTY_BEAT: ShotBeat = { character: "", what: "", want: "", need: "", fear: "", hiding: "", subtext: "", start: "", turn: "", end: "" };

/** A nested change for the engine from a path like "camera.framing". */
const nest = (path: string, value: unknown): Record<string, unknown> => path.split(".").reduceRight<unknown>((v, k) => ({ [k]: v }), value) as Record<string, unknown>;
const get = (c: ShotContract, path: string): string => String(path.split(".").reduce<unknown>((o, k) => (o as Record<string, unknown> | undefined)?.[k], c) ?? "");
export const clock = (s: number) => `${s.toFixed(1).replace(/\.0$/, "")}s`;

/**
 * The shots: the story broken down into scenes and shots, each one a Shot Contract that says what the shot is for, who is in it and how they act, where the camera is, how it is lit and what must stay
 * the same. The first pass is a draft to change. Nothing is made from a shot until you decide.
 */
export function ShotLab({ dir, initial }: { dir: string; initial?: string | null }) {
  const [v, setV] = useState<ShotsView | null>(null);
  const [sel, setSel] = useState<string | null>(null);
  const [c, setC] = useState<ShotContract | null>(null);
  const [tab, setTab] = useState<Tab>("story");
  const [bible, setBible] = useState<BibleView | null>(null);
  const [sug, setSug] = useState<ShotSuggestion | null>(null);
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState("");
  const [err, setErr] = useState("");
  const [review, setReview] = useState(false);
  const [voices, setVoices] = useState(false);                         // every shot's recorded voices, in one place
  const [princ, setPrinc] = useState<{ screen_craft: boolean; video: { id: string; name: string; plain: string }[] } | null>(null);          // the animation principles this shot will carry
  const [helpShot, setHelpShot] = useState<Record<string, unknown> | null>(null);          // the writing helper suggestion for this shot
  const [helping, setHelping] = useState(false);
  const [action, setAction] = useState(false);
  const [pacing, setPacing] = useState(false);
  const [soundPlan, setSoundPlan] = useState(false);
  const [cmd, setCmd] = useState<{ text: string; busy: boolean; result: { understood: boolean; summary: string[]; patch: Record<string, unknown>; help?: string } | null } | null>(null);   // the Director Command              // the continuity findings instead of one shot

  const load = useCallback(async (keep?: string | null) => {
    try {
      const s = await api.shots("get", dir);
      setV(s);
      const id = keep ?? s.shots[0]?.id ?? null;
      setSel(id && s.shots.some((x) => x.id === id) ? id : s.shots[0]?.id ?? null);
    } catch (e) { setErr(errorText(e)); }
  }, [dir]);
  useEffect(() => { void load(initial); api.bible("get", dir).then(setBible).catch(() => {}); }, [load, dir]);
  useEffect(() => {
    setSug(null); setDraft({});
    if (!sel) { setC(null); return; }
    api.shots("shot", dir, { id: sel }).then((r) => setC(r.shot ?? null)).catch((e) => setErr(errorText(e)));
    api.shots<{ screen_craft: boolean; video: { id: string; name: string; plain: string }[] }>("principles", dir, { id: sel }).then(setPrinc).catch(() => setPrinc(null));
  }, [sel, dir]);

  const act = async (what: string, fn: () => Promise<ShotsView>, keep?: (r: ShotsView) => string | null) => {
    setBusy(what); setErr("");
    try { const r = await fn(); setV(r); const id = keep ? keep(r) : sel; setSel(id && r.shots.some((x) => x.id === id) ? id : r.shots[0]?.id ?? null); }
    catch (e) { setErr(errorText(e)); } finally { setBusy(""); }
  };
  const save = async (patch: Record<string, unknown>) => {
    if (!sel) return;
    setErr("");
    try { const r = await api.shots("set", dir, { id: sel, patch }); if (r.shot) setC(r.shot); setV(r); } catch (e) { setErr(errorText(e)); }
  };
  const commit = (path: string) => { if (draft[path] === undefined) return; const value = path === "generation.duration" ? Number(draft[path]) : draft[path]; void save(nest(path, value)).then(() => setDraft(({ [path]: _x, ...rest }) => rest)); };
  const text = (path: string, label: string, rows = 0, hint = "") => c && (
    <label className="field" key={path}><span>{label}</span>
      {rows ? <textarea className="text-input" rows={rows} value={draft[path] ?? get(c, path)} placeholder={hint} onChange={(e) => setDraft({ ...draft, [path]: e.target.value })} onBlur={() => commit(path)} />
        : <input className="text-input" value={draft[path] ?? get(c, path)} placeholder={hint} onChange={(e) => setDraft({ ...draft, [path]: e.target.value })} onBlur={() => commit(path)} />}</label>);
  const pick = (path: string, label: string, options: string[]) => c && (
    <label className="field" key={path}><span>{label}</span>
      <select className="text-input" value={get(c, path)} onChange={(e) => void save(nest(path, e.target.value))}><option value="">—</option>{options.map((o) => <option key={o} value={o}>{o}</option>)}</select></label>);

  useEffect(() => {                                                       // Ctrl/Cmd+K: say what you want changed in this shot
    const k = (e: KeyboardEvent) => { if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") { e.preventDefault(); setCmd((x) => (x ? null : { text: "", busy: false, result: null })); } if (e.key === "Escape") setCmd(null); };
    window.addEventListener("keydown", k);
    return () => window.removeEventListener("keydown", k);
  }, []);
  const runCmd = async () => {
    if (!cmd || !sel || !cmd.text.trim()) return;
    setCmd({ ...cmd, busy: true });
    try { const r = await api.shots<{ understood: boolean; summary: string[]; patch: Record<string, unknown>; help?: string }>("command", dir, { id: sel, text: cmd.text }); setCmd({ ...cmd, busy: false, result: r }); }
    catch (e) { setErr(errorText(e)); setCmd({ ...cmd, busy: false }); }
  };
  const applyCmd = async () => { if (cmd?.result?.understood) { await save(cmd.result.patch); setCmd(null); } };
  const helpMe = async () => {
    if (!sel) return;
    setErr(""); setHelping(true);
    try { const p = await askForHelp(dir, "shot", sel, `shot ${sel}`); if (p) setHelpShot(p); } catch (e) { setErr(errorText(e)); } finally { setHelping(false); }
  };
  const locked = !!c?.locks.storyboard;
  const suggest = async () => { if (sel) { try { setSug(await api.shots<ShotSuggestion>("suggest", dir, { id: sel })); } catch (e) { setErr(errorText(e)); } } };
  const apply = async () => { if (sug) { await save({ camera: sug.camera, lighting: { description: sug.lighting.description, why: sug.lighting.why } }); setSug(null); } };
  const del = async () => { if (sel && await ask(`Take shot ${sel} out?\n\nIt is moved aside, not deleted.`, { ok: "Take out" })) await act("del", () => api.shots("delete", dir, { id: sel })); };
  const setBeats = (beats: ShotBeat[]) => save({ performance: { beats } });

  if (!v) return <div className="sl"><div className="film-load dim">{err || "Opening the shots…"}</div></div>;
  const scenes = [...new Set(v.shots.map((s) => s.scene))];
  const charNames = (bible?.characters ?? []).map((x) => x.name);

  return (
    <div className="sl">
      <aside className="sl-list" aria-label="Shots">
        <button className="btn ghost sm sl-ck" disabled={!v.shots.length} onClick={() => setPacing(true)} title="The rhythm of the cuts, and where it works against the story">Pacing…</button>
        <button className="btn ghost sm sl-ck" disabled={!v.shots.length} onClick={() => setSoundPlan(true)} title="How each shot's voice will be made, and why. Free: nothing is made or bought">Sound plan…</button>
        <button className="btn ghost sm sl-ck" disabled={!v.shots.length} onClick={() => setAction(true)} title="Plan a fight, a chase or a sports moment as short shots">Action scene…</button>
        <button className="btn ghost sm sl-ck" onClick={() => setCmd({ text: "", busy: false, result: null })} title="Say what you want changed in this shot (Ctrl+K)">Director Command  Ctrl+K</button>
        <button className={`btn ghost sm sl-ck ${review ? "on" : ""}`} onClick={() => { setReview((x) => !x); setVoices(false); }} title="Where something may have changed between shots">Continuity check</button>
        <button className={`btn ghost sm sl-ck ${voices ? "on" : ""}`} aria-pressed={voices} onClick={() => { setVoices((x) => !x); setReview(false); }} title="Attach your own recorded voices to the people in the shots">Voiceover</button>
        <div className="sl-listhead"><h2>Shots <span className="dim">{v.shots.length}{v.seconds ? ` · ${clock(v.seconds)}` : ""}</span></h2>
          <button className="btn ghost sm" onClick={() => act("break", () => api.shots("breakdown", dir), (r) => r.made?.[0] ?? sel)} disabled={!!busy}
                  title="Draft shots for any scene that has none. Shots you have edited are never changed.">{v.shots.length ? "Break down new scenes" : "Break down the story"}</button></div>
        {v.shots.length === 0 && <p className="dim sl-empty">No shots yet. <b>Break down the story</b> drafts the shots for every scene, like a director's first pass. You change anything you like.</p>}
        {scenes.map((n) => (
          <section key={n} className="sl-scene"><h3>Scene {n} <span className="dim">{clock(v.scenes.find((x) => x.number === n)?.seconds ?? 0)}</span></h3>
            <ol>{v.shots.filter((s) => s.scene === n).map((s) => (
              <li key={s.id}><button className={sel === s.id ? "on" : ""} onClick={() => setSel(s.id)}>
                <span className="id num">{s.id.split("-")[1]}</span>
                <span className="t">{s.title || s.story_purpose || "Shot"}</span>
                <span className="fr">{s.camera.framing || "—"}</span>
                <span className="dim d">{clock(s.duration)}</span>{s.locks.storyboard && <span className="lk" title="Storyboard locked">locked</span>}</button></li>))}</ol>
            <button className="link" onClick={() => act("add", () => api.shots("add", dir, { scene: n }), (r) => r.id ?? sel)}>+ Add a shot</button></section>))}
      </aside>

      {soundPlan && <SoundPlan dir={dir} onClose={() => setSoundPlan(false)} onGo={(id) => { setSel(id); setSoundPlan(false); }} />}
      {pacing && <PacingSheet dir={dir} onClose={() => setPacing(false)} onGo={(id) => { setSel(id); setPacing(false); }} />}
      {action && <ActionChoreo dir={dir} shots={v} characters={charNames} onClose={() => setAction(false)} onAdded={() => { void act("reload", () => api.shots("get", dir)); }} />}
      {cmd && <Sheet label="Director Command" className="dc" onDismiss={() => setCmd(null)} onSubmit={(e) => { e.preventDefault(); void runCmd(); }}>
          <label className="field"><span>Director Command <span className="dim">for {sel ?? "no shot"}</span></span>
            <input className="text-input" autoFocus value={cmd.text} onChange={(e) => setCmd({ ...cmd, text: e.target.value, result: null })} placeholder="e.g. make this shot more claustrophobic" /></label>
          {cmd.result && <div className="dc-result">
            {cmd.result.understood ? <><ul>{cmd.result.summary.map((l, i) => <li key={i}>{l}</li>)}</ul>
              <div className="film-actions"><button type="button" className="btn primary" onClick={applyCmd}>Apply</button><button type="button" className="btn ghost" onClick={() => setCmd({ ...cmd, result: null })}>Change my words</button></div></>
              : <><p>I didn't understand that.</p><p className="dim">{cmd.result.help}</p></>}</div>}
          {!cmd.result && <div className="film-actions"><button className="btn primary" disabled={cmd.busy || !cmd.text.trim() || !sel}>Show me the change</button><span className="dim">Nothing changes until you press Apply.</span></div>}
        </Sheet>}
      {helpShot && c && <ShotSuggestionSheet shot={c.id} proposal={helpShot} current={c} onClose={() => setHelpShot(null)} onUse={async (patch) => { setHelpShot(null); if (Object.keys(patch).length) await save(patch); }} />}
      {voices ? <main className="sl-main"><VoiceoverPanel dir={dir} /></main>
        : review ? <main className="sl-main"><FilmContinuity dir={dir} onGo={(id) => { setSel(id); setReview(false); }} onChanged={() => { void load(sel); if (sel) api.shots("shot", dir, { id: sel }).then((r) => setC(r.shot ?? null)).catch(() => {}); }} /></main>
        : c ? <main className="sl-main">
        <div className="sl-head"><h2>{c.id} <input className="sl-title" aria-label="Shot title" value={draft.title ?? c.title} onChange={(e) => setDraft({ ...draft, title: e.target.value })} onBlur={() => commit("title")} placeholder="Name this shot" /></h2>
          <div className="sl-tools">
            <button className="link" onClick={() => act("up", () => api.shots("move", dir, { id: c.id, delta: -1 }), () => c.id)}>Move up</button>
            <button className="link" onClick={() => act("down", () => api.shots("move", dir, { id: c.id, delta: 1 }), () => c.id)}>Move down</button>
            <button className="link" onClick={() => act("dup", () => api.shots("duplicate", dir, { id: c.id }), (r) => r.id ?? sel)}>Duplicate</button>
            <button className="link" onClick={() => act("split", () => api.shots("split", dir, { id: c.id }), () => c.id)}>Split</button>
            <button className="link" onClick={() => act("merge", () => api.shots("merge", dir, { id: c.id }), () => c.id)}>Join with next</button>
            <button className="link" onClick={del}>Take out</button></div></div>
        <div className="cw-tabs sl-tabs" role="tablist">{TABS.map((t) => <button key={t.id} role="tab" aria-selected={tab === t.id} className={tab === t.id ? "on" : ""} onClick={() => setTab(t.id)}>{t.label}</button>)}</div>
        {err && <p className="error-text" role="alert">{err}</p>}
        {locked && <p className="cw-note">This shot's storyboard is locked, so its framing, people and place are fixed. Unlock it to change them.</p>}

        <div className="sl-fields">
          {tab === "story" && <>
            {text("story_purpose", "What this shot is for", 2, "The one thing it must do for the story")}
            {text("action", "What happens", 3)}
            <div className="field"><span>Dialogue</span>
              <ul className="sl-dlg">{c.dialogue.map((d, i) => (
                <li key={i}><b>{d.speaker}</b>{d.paren && <i> ({d.paren})</i>} {d.line}
                  <button className="link" onClick={() => save({ dialogue: c.dialogue.filter((_, k) => k !== i) })}>remove</button></li>))}</ul>
              {c.dialogue.length === 0 && <p className="dim">No dialogue in this shot.</p>}</div>
            <div className="field"><span>In the shot</span>
              <div className="chips">{c.characters.map((p) => <span key={p.name} className="chip">{p.name}{p.character_id ? "" : " (not in the Bible)"}
                <button className="link" onClick={() => save({ characters: c.characters.filter((x) => x.name !== p.name) })} aria-label={`Remove ${p.name}`}>×</button></span>)}
                {charNames.filter((n) => !c.characters.some((x) => x.name.toLowerCase() === n.toLowerCase())).length > 0 &&
                  <select className="text-input sl-add" value="" aria-label="Add a character" onChange={(e) => { const n = e.target.value; if (!n) return; const b = bible?.characters.find((x) => x.name === n);
                    void save({ characters: [...c.characters, { name: n, character_id: b?.id ?? null, state_id: b?.states[0]?.id ?? null, wardrobe_id: null }] }); }}>
                    <option value="">+ Add someone…</option>{charNames.filter((n) => !c.characters.some((x) => x.name.toLowerCase() === n.toLowerCase())).map((n) => <option key={n} value={n}>{n}</option>)}</select>}</div></div>
            <div className="sl-two">
              {text("environment.name", "Where")}
              {text("generation.duration", "Length (seconds)")}</div>
          </>}

          {(tab === "acting" || tab === "camera") && <div className="sl-help"><span className="dim">Optional: a writing helper can suggest the acting, camera and light for this shot from your story.</span>
            <button className="btn ghost sm" onClick={helpMe} disabled={helping}><I.Sparkle size={13} /> {helping ? "Writing…" : "Help me write this shot"}</button></div>}
          {tab === "acting" && princ && princ.video.length > 0 && <div className="sl-princ"><span className="dim">{princ.screen_craft ? "Screen craft in this shot" : "Animation principles in this shot"}</span>
            {princ.video.map((p) => <span key={p.id} className="sl-pchip" title={p.plain}>{p.name}</span>)}
            <span className="dim">chosen from what happens here and the film's look; change them in Cast &amp; World, Rules &amp; style</span></div>}
          {tab === "acting" && <>
            {text("performance.emotional_intention", "What the audience should feel", 2, "e.g. Held-back dread")}
            <div className="field"><span>Acting beats <span className="dim">what each person wants, needs, fears and hides, and how it shows</span></span>
              {c.performance.beats.map((b, i) => (
                <fieldset key={i} className="sl-beat"><legend>Beat {i + 1}</legend>
                  <div className="cw-grid2">{BEAT.map(([k, n]) => <label key={k} className="field"><span>{n}</span>
                    <input className="text-input" defaultValue={b[k]} onBlur={(e) => { if (e.target.value !== b[k]) void setBeats(c.performance.beats.map((x, j) => j === i ? { ...x, [k]: e.target.value } : x)); }} /></label>)}</div>
                  <button className="link" onClick={() => setBeats(c.performance.beats.filter((_, j) => j !== i))}>Remove this beat</button></fieldset>))}
              <button className="btn ghost sm" onClick={() => setBeats([...c.performance.beats, { ...EMPTY_BEAT, character: c.characters[0]?.name ?? "" }])}>+ Add a beat</button></div>
            {text("performance.micro_animation", "Small living motion", 2, "Breath, a blink, a swallow before she speaks. Only what comes from the feeling.")}
          </>}

          {tab === "camera" && <>
            {c && <ProductionModePicker value={c.production} locked={locked} onChange={(p) => void save({ production: p })} />}
            <div className="sl-sug"><button className="btn ghost sm" onClick={suggest}>Suggest from the feeling</button>
              {sug && <div className="sl-sugcard"><p><b>Suggested</b> <span className="dim">from {sug.from}</span></p>
                <p className="dim">{sug.camera.framing}, {sug.camera.angle}, {sug.camera.movement}, {sug.camera.lens}, {sug.camera.focus} focus.</p><p>{sug.camera.why}</p>
                <p className="dim">Light: {sug.lighting.description}</p><p>{sug.lighting.why}</p>
                <div className="film-actions"><button className="btn primary sm" onClick={apply}>Use this</button><button className="btn ghost sm" onClick={() => setSug(null)}>No thanks</button></div></div>}</div>
            {c && <label className="field sl-dof"><span>Depth of field <span className="dim">how much is in focus, like the aperture</span></span>
              <select className="text-input" value={c.camera.dof ?? ""} onChange={(e) => void save({ camera: { dof: e.target.value } })} aria-label="Depth of field"><option value="">Automatic (soft behind people, left alone in wide shots)</option>{(v.enums.dof ?? []).map((k) => <option key={k} value={k}>{DOF_LABEL[k] ?? k}</option>)}</select></label>}
            {c && <CompositionGuide dir={dir} shot={c.id} version={`${c.camera?.framing}|${c.camera?.angle}|${JSON.stringify(c.plan ?? null)}|${c.blocking}`} />}
            <div className="cw-grid2">{pick("camera.framing", "Framing", v.enums.framing)}{pick("camera.angle", "Angle", v.enums.angle)}{pick("camera.lens", "Lens", v.enums.lens)}{pick("camera.movement", "Movement", v.enums.movement)}{pick("camera.focus", "Focus", v.enums.focus)}</div>
            {text("camera.position", "Where the camera is", 2, "e.g. Behind Sarah's left shoulder, at the sink")}
            {text("camera.why", "Why", 2, "What this choice does for the story")}
          </>}

          {tab === "voice" && <>{c.dialogue.length > 0 && <SoundCut lead={c.sound_cut?.lead ?? 0} tail={c.sound_cut?.tail ?? 0} max={v.cut_max ?? 2} onChange={(x) => void save({ sound_cut: x })} />}<VoiceoverPanel dir={dir} only={c.id} /></>}
          {tab === "blocking" && c && <BlockingPlan dir={dir} shot={c.id} locked={locked} plan={c.plan ?? null} onSaved={save} />}
          {tab === "light" && <>
            {text("lighting.description", "The light", 3, "Where it comes from, how hard or soft, what colour")}
            {text("lighting.time", "Time of day")}
            {text("lighting.why", "Why", 2, "What the audience should feel")}
            <div className="sl-sug"><button className="btn ghost sm" onClick={suggest}>Suggest from the feeling</button>
              {sug && <p className="dim">See the suggestion on the Camera tab.</p>}</div>
          </>}

          {tab === "continuity" && <>
            {text("blocking", "Blocking", 2, "Where people stand and move; where they look")}
            {text("opening_state", "How the shot begins", 2, "The state it must start in (what is held, where everyone is)")}
            {text("closing_state", "How the shot ends", 2)}
            {text("continuity", "Must stay the same", 2, "Costume, injuries, props, light, screen direction")}
            {text("sound", "Sound", 2, "Dialogue, ambience, effects, music")}
          </>}
        </div>
      </main> : <main className="sl-main"><p className="dim cw-empty">{v.shots.length ? "Choose a shot." : ""}</p></main>}
    </div>
  );
}
