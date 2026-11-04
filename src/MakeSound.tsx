import { useCallback, useEffect, useState } from "react";
import { Sheet } from "./Sheet";
import { api, errorText, type AudioAsset, type GenEstimate, type GenProvider, type GenResult } from "./api";
import { ask } from "./ask";
import * as I from "./icons";
import { confirmWords } from "./voiceUsage";
import { audioFacts } from "./soundWords";

const EXAMPLES: Record<"sfx" | "music", string[]> = {
  sfx: ["A kettle clicking off in a quiet kitchen", "Footsteps on wet gravel, slow", "Rain on a tin roof, steady", "A wooden door creaking open"],
  music: ["A gentle music box theme, tender and slightly sad", "Slow solo piano, hopeful, no drums", "Low tense strings, building quietly"],
};

/**
 * Make a sound effect or music with an AI provider. The price (or that it is unknown) and the state of the rights are shown first; nothing is sent until you tick what must be ticked and say yes
 * in the question that follows. What is made is saved in your library with how it was made and waits for your approval; asking for the same thing again is free.
 */
export function MakeSound({ dir, kind, onClose, onMade }: { dir: string; kind: "sfx" | "music"; onClose: () => void; onMade: () => void }) {
  const [providers, setProviders] = useState<GenProvider[]>([]);
  const [pid, setPid] = useState<string>("");
  const [prompt, setPrompt] = useState("");
  const [duration, setDuration] = useState("");
  const [loop, setLoop] = useState(false);
  const [influence, setInfluence] = useState("");
  const [instrumental, setInstrumental] = useState(true);
  const [variation, setVariation] = useState(0);
  const [est, setEst] = useState<GenEstimate | null>(null);
  const [rights, setRights] = useState(false);
  const [unknown, setUnknown] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [made, setMade] = useState<AudioAsset[]>([]);
  const [note, setNote] = useState("");
  const [pending, setPending] = useState<{ task: string; prompt: string }[]>([]);

  useEffect(() => {
    api.audioGen<{ providers: GenProvider[] }>("providers", dir).then((r) => { const mine = (r?.providers ?? []).filter((p) => p.kind === kind); setProviders(mine); setPid((x) => x || mine.find((p) => p.has_key)?.id || mine[0]?.id || ""); }).catch((e) => setErr(errorText(e)));
  }, [dir, kind]);
  const loadPending = useCallback(() => api.audioGen<{ tasks: { task: string; prompt: string }[] }>("pending", dir).then((r) => setPending(r.tasks)).catch(() => {}), [dir]);
  useEffect(() => { void loadPending(); }, [loadPending]);
  useEffect(() => {
    const k = (e: KeyboardEvent) => { if (e.key === "Escape" && !document.querySelector(".ask, [role=alertdialog]")) { e.stopImmediatePropagation(); onClose(); } };
    window.addEventListener("keydown", k, true);
    return () => window.removeEventListener("keydown", k, true);
  }, [onClose]);

  const p = providers.find((x) => x.id === pid);
  const params = useCallback(() => ({ provider: pid, prompt, duration: duration || null, ...(p?.loop ? { loop } : {}), ...(influence !== "" ? { influence: Number(influence) } : {}), ...(p?.instrumental ? { instrumental } : {}), variation }),
    [pid, prompt, duration, loop, influence, instrumental, variation, p]);
  useEffect(() => {
    setEst(null);
    if (!pid || prompt.trim().length < 3) return;
    const t = setTimeout(() => { api.audioGen<GenEstimate>("estimate", dir, params()).then(setEst).catch(() => setEst(null)); }, 400);
    return () => clearTimeout(t);
  }, [dir, pid, prompt, duration, loop, influence, instrumental, variation, params]);

  const free = !!est?.cached;
  const ready = !!est && !!p?.has_key && (free || (rights && (!est.needs_unknown_cost_accepted || unknown)));
  const make = async () => {
    if (!est || !p) return;
    setErr(""); setBusy(true); setNote("");
    try {
      if (!free && !(await ask(confirmWords({ action: `Make ${kind === "sfx" ? "this sound" : "this music"} with ${p.label}?\n\n“${prompt.trim()}”`, provider: p.label.replace(/ sound effects$/, ""),
        cost: est.cost_known ? `${est.basis}` : `${est.basis}. You accepted that the price is unknown.`, note: `It is saved in your library as "commercial use: not known". It is never retried by itself if the answer is unclear.` }), { ok: kind === "sfx" ? "Make the sound" : "Make the music" }))) return;
      const r = await api.audioGen<GenResult>("generate", dir, { ...params(), confirmed: true, rights_ack: free ? false : rights, unknown_cost_accepted: unknown });
      setNote(r.note);
      if (r.pending) void loadPending();
      const got = r.assets ?? (r.asset ? [r.asset] : []);
      if (got.length) { setMade(got); onMade(); }
    } catch (e) { setErr(errorText(e)); } finally { setBusy(false); }
  };
  const check = (task: string) => { setErr(""); setBusy(true); api.audioGen<GenResult>("check", dir, { task }).then((r) => { setNote(r.note); const got = r.assets ?? (r.asset ? [r.asset] : []); if (got.length) { setMade(got); onMade(); } void loadPending(); })
    .catch((e) => setErr(errorText(e))).finally(() => setBusy(false)); };

  return (
    <Sheet label={kind === "sfx" ? "Make a sound effect" : "Make music"} className="vsc ms" onDismiss={onClose}>
        <div className="vs-head"><h2>{kind === "sfx" ? "Make a sound effect" : "Make music"}</h2><div style={{ flex: 1 }} /><button className="icon-btn" onClick={onClose} aria-label="Close"><I.Close size={18} /></button></div>
        <div className="vsc-body">
          <div className="vr-who" role="tablist" aria-label="Who makes it">
            {providers.map((x) => <button key={x.id} role="tab" aria-selected={pid === x.id} className={pid === x.id ? "on" : ""} onClick={() => { setPid(x.id); setUnknown(false); }}>{x.label}</button>)}
          </div>
          {p && <p className="dim ms-cost">{p.cost_words}.{!p.has_key && <> <b>Add the {p.label.includes("Kie") ? "Kie.ai" : "ElevenLabs"} key in Settings first.</b></>}</p>}
          <label className="field"><span>What should it sound like?</span>
            <textarea className="text-input" rows={3} value={prompt} onChange={(e) => { setPrompt(e.target.value); setVariation(0); }} placeholder={EXAMPLES[kind][0]} aria-label="Description" /></label>
          <div className="cv-ex">{EXAMPLES[kind].map((x) => <button key={x} className="link" onClick={() => { setPrompt(x); setVariation(0); }}>{x.split(",")[0]}</button>)}</div>
          <div className="cw-fields">
            {p?.duration !== null && <label className="field"><span>Length in seconds (empty: the AI decides)</span>
              <input className="text-input" inputMode="decimal" value={duration} placeholder={p ? `${p.duration?.[0]} to ${p.duration?.[1]}` : ""} onChange={(e) => { setDuration(e.target.value); setVariation(0); }} /></label>}
            {p?.loop && <label className="ov-check"><input type="checkbox" checked={loop} onChange={(e) => { setLoop(e.target.checked); setVariation(0); }} /> A smooth loop (for ambience)</label>}
            {p?.instrumental && <label className="ov-check"><input type="checkbox" checked={instrumental} onChange={(e) => { setInstrumental(e.target.checked); setVariation(0); }} /> No singing (instrumental)</label>}
          </div>
          {kind === "sfx" && <details className="cw-spatial"><summary>More</summary><label className="field"><span>How closely to follow the description (0 to 1)</span>
            <input className="text-input" inputMode="decimal" value={influence} placeholder="0.3" onChange={(e) => { setInfluence(e.target.value); setVariation(0); }} /></label></details>}

          {est && <section className="ms-price" aria-label="Price">
            <p><b>{free ? "Already in your library: free." : est.cost_known ? `About ${(est.expected ?? est.amount)?.toLocaleString()} credits (an estimate).` : "The price is not published."}</b> <span className="dim">{est.basis}</span></p>
            {!free && <>
              {est.needs_unknown_cost_accepted && <label className="ov-check"><input type="checkbox" checked={unknown} onChange={(e) => setUnknown(e.target.checked)} /> I accept that the price is unknown until the provider reports it.</label>}
              <label className="ov-check ms-rights"><input type="checkbox" checked={rights} onChange={(e) => setRights(e.target.checked)} /> <span>{est.rights_note} I understand it is saved as “commercial use: not known”.</span></label>
            </>}
          </section>}
          <div className="cv-actions"><button className="btn primary" disabled={busy || !ready} onClick={() => void make()}><I.Sparkle size={14} /> {busy ? "Making…" : free ? "Use the one I have" : "Make it…"}</button>
            <span className="dim">{free ? "Nothing is sent." : "You are asked once more, with the price, before anything is sent."}</span></div>

          {note && <p role="status" className="dim">{note}</p>}
          {pending.length > 0 && <section><h3>Still being made <span className="dim">already paid for</span></h3>
            <ul className="vsc-people">{pending.map((t) => <li key={t.task}>{t.prompt.slice(0, 60)} <button className="link" disabled={busy} onClick={() => check(t.task)}>Check again</button></li>)}</ul></section>}
          {made.length > 0 && <section aria-label="What was made"><h3>Made <span className="dim">saved in your library, waiting for your approval</span></h3>
            <ul className="vsc-people">{made.map((a) => <li key={a.id}><b>{a.name}</b> <span className="dim">{audioFacts(a)}</span><br /><audio controls preload="none" src={api.mediaUrl(`${dir}/${a.file}`)} aria-label={`Hear ${a.name}`} /></li>)}</ul>
            <button className="btn sm" onClick={() => { setVariation((v) => v + 1); setMade([]); setNote("Ready for another version: it is a new request, so it is priced and asked about again."); }}>Make a variation</button></section>}
          {err && <p className="error-text" role="alert">{err}</p>}
        </div>
    </Sheet>
  );
}
