import { useCallback, useEffect, useState } from "react";
import { api, errorText, type AudioAsset, type Motif, type MusicPlan, type MusicPrompt, type MusicSpot, type MusicSuggestion } from "./api";

export const DECISION_WORDS: Record<MusicSpot["decision"], string> = { score: "Music (score)", source: "Music in the world (a radio, a band)", silence: "Silence, on purpose" };
export const ENERGY_WORDS = ["nothing", "barely there", "quiet", "steady", "driving", "full"];

/** The state of the whole film's music plan in one sentence. */
export function planWords(p: MusicPlan): string {
  const r = p.report;
  const bits: string[] = [];
  if (r.undecided.length) bits.push(`${r.undecided.length} scene${r.undecided.length === 1 ? " has" : "s have"} no decision yet (${r.undecided.slice(0, 6).join(", ")}${r.undecided.length > 6 ? "…" : ""})`);
  const unrecorded = r.records.filter((x) => x.problems.length).length;
  if (unrecorded) bits.push(`${unrecorded} piece${unrecorded === 1 ? "" : "s"} of music in the plan ${unrecorded === 1 ? "needs" : "need"} a rights decision`);
  const idle = r.motifs.filter((m) => m.note === "Never used.").length;
  if (idle) bits.push(`${idle} motif${idle === 1 ? " is" : "s are"} not used anywhere`);
  const share = Math.round(r.music_share * 100);
  return `${bits.length ? bits.join("; ") + ". " : "Every scene has a decision. "}Music plays in about ${share}% of the film.`;
}

/** What a spot is, in a line. */
export function spotWords(s: MusicSpot): string {
  if (s.decision === "silence") return "Silence, on purpose";
  if (s.decision === "source") return "Music in the world";
  return `${s.mood || "Music"}, energy ${s.energy_in} to ${s.energy_out} (${ENERGY_WORDS[s.energy_in]} to ${ENERGY_WORDS[s.energy_out]})`;
}

const csv = (s: string): string[] => s.split(",").map((x) => x.trim()).filter(Boolean);

/**
 * The music director for the open scene and the whole film: motifs (ideas the music comes back to), spotting (music, music in the world, or silence, from which shot to which), the words to ask a music maker
 * with, and a record of who approved which music for which scenes. "Put into the film" turns approved spots that have music into ordinary cues. Free and local: nothing is generated, sent or charged here.
 */
export function MusicDirector({ dir, scene, shots, assets, onChanged }: { dir: string; scene: number; shots: { id: string; seconds: number }[]; assets: AudioAsset[]; onChanged: () => void }) {
  const [open, setOpen] = useState(false);
  const [plan, setPlan] = useState<MusicPlan | null>(null);
  const [busy, setBusy] = useState("");
  const [err, setErr] = useState("");
  const [said, setSaid] = useState("");
  const [sugg, setSugg] = useState<MusicSuggestion | null>(null);
  const [words, setWords] = useState<MusicPrompt | null>(null);
  const [found, setFound] = useState<{ id: string; rows: { id: string; name: string; why: string[] }[] } | null>(null);
  const [mo, setMo] = useState({ name: "", kind: "theme" as Motif["kind"], subject: "", mood: "", tempo: "", description: "", instruments: "" });
  const [rec, setRec] = useState<{ id: string; by: string; scenes: string; ref: string } | null>(null);

  const load = useCallback(() => api.music("get", dir).then(setPlan).catch((e) => setErr(errorText(e))), [dir]);
  useEffect(() => { if (open) void load(); }, [open, load]);
  const go = async (label: string, f: () => Promise<void>) => { setErr(""); setSaid(""); setBusy(label); try { await f(); } catch (e) { setErr(errorText(e)); } finally { setBusy(""); } };
  const save = (label: string, action: "motif_set" | "motif_remove" | "spot_set" | "spot_remove" | "record_set", data: Record<string, unknown>) => go(label, async () => { setPlan(await api.music<MusicPlan>(action, dir, data)); });

  if (!open) return <section aria-label="Music director"><h3>Music director <span className="dim">motifs, where music goes, who approved it</span></h3>
    <p className="dim">Decide for each scene whether music plays, comes from the world, or is left out on purpose; keep the musical ideas the film comes back to; record who approved which music. Free; nothing is generated or sent.</p>
    <button className="btn sm" onClick={() => setOpen(true)}>Open the music director…</button></section>;
  if (!plan) return <section aria-label="Music director"><h3>Music director</h3>{err ? <p className="ss-warn" role="alert">{err}</p> : <p className="dim">Loading…</p>}</section>;

  const mine = plan.spots.filter((s) => s.scene === scene);
  const music = assets.filter((a) => a.kind === "music");
  const ids = shots.map((s) => s.id);

  return (
    <section aria-label="Music director">
      <h3>Music director <span className="dim">scene {scene}</span></h3>
      {err && <p className="ss-warn" role="alert">{err}</p>}
      {said && <p className="dim" role="status">{said}</p>}
      <p className="dim" aria-label="State of the music plan">{planWords(plan)}</p>
      {plan.report.jumps.map((j) => <p key={`${j.from_scene}-${j.to_scene}`} className="dim">Scene {j.from_scene} ends at energy {j.from_energy}; scene {j.to_scene} starts at {j.to_energy}. {j.note}</p>)}

      <h4>Motifs <span className="dim">ideas the music comes back to</span></h4>
      {plan.motifs.length === 0 && <p className="dim">No motifs yet. A motif can belong to a character, a place or a theme.</p>}
      <ul className="ss-cues">{plan.motifs.map((m) => <li key={m.id} className="sm-row"><b>{m.name}</b> <span className="dim">{m.kind}{m.subject ? ` · ${m.subject}` : ""}{m.mood ? ` · ${m.mood}` : ""}{m.tempo ? ` · ${m.tempo}` : ""}{m.instruments.length ? ` · ${m.instruments.join(", ")}` : ""}</span>
        {m.description && <q>{m.description}</q>}
        <button className="btn sm ghost" disabled={!!busy} aria-label={`Remove motif ${m.name}`} onClick={() => void save("motif", "motif_remove", { id: m.id })}>Remove</button></li>)}</ul>
      <div className="sm-row">
        <input className="text-input" placeholder="Name, e.g. Sarah's theme" aria-label="Motif name" value={mo.name} maxLength={60} onChange={(e) => setMo({ ...mo, name: e.target.value })} />
        <select className="text-input" aria-label="Motif belongs to" value={mo.kind} onChange={(e) => setMo({ ...mo, kind: e.target.value as Motif["kind"] })}><option value="character">A character</option><option value="place">A place</option><option value="theme">A theme</option></select>
        <input className="text-input" placeholder="Who or where (name as in the Bible)" aria-label="Motif subject" value={mo.subject} onChange={(e) => setMo({ ...mo, subject: e.target.value })} />
        <input className="text-input" placeholder="Mood" aria-label="Motif mood" value={mo.mood} onChange={(e) => setMo({ ...mo, mood: e.target.value })} />
        <input className="text-input" placeholder="Tempo, e.g. slow, 60 bpm" aria-label="Motif tempo" value={mo.tempo} onChange={(e) => setMo({ ...mo, tempo: e.target.value })} />
        <input className="text-input" placeholder="Instruments, comma separated" aria-label="Motif instruments" value={mo.instruments} onChange={(e) => setMo({ ...mo, instruments: e.target.value })} />
        <input className="text-input" placeholder="In words: four rising notes…" aria-label="Motif description" value={mo.description} maxLength={300} onChange={(e) => setMo({ ...mo, description: e.target.value })} />
        <button className="btn sm" disabled={!!busy || !mo.name.trim()} onClick={() => void go("motif", async () => { setPlan(await api.music<MusicPlan>("motif_set", dir, { ...mo, instruments: csv(mo.instruments) })); setMo({ name: "", kind: "theme", subject: "", mood: "", tempo: "", description: "", instruments: "" }); })}>Add the motif</button></div>

      <h4>Spotting scene {scene} <span className="dim">music, music in the world, or silence</span></h4>
      {mine.length === 0 && <p className="dim">No decision for this scene yet.</p>}
      <ul className="ss-cues">{mine.map((s) => <SpotRow key={s.id} s={s} ids={ids} motifs={plan.motifs} music={music} busy={!!busy}
        onSave={(patch) => void save("spot", "spot_set", { id: s.id, ...patch })} onRemove={() => void save("spot", "spot_remove", { id: s.id })}
        onPrompt={() => void go("prompt", async () => setWords(await api.music<MusicPrompt>("prompt", dir, { id: s.id })))}
        onFind={() => void go("find", async () => { const r = await api.music<{ candidates: { id: string; name: string; why: string[] }[] }>("candidates", dir, { id: s.id }); setFound({ id: s.id, rows: r.candidates }); })} />)}</ul>
      {words && <div className="ss-heard"><p><b>Words to ask for this music</b> <span className="dim">about {words.duration} s, instrumental</span></p><q>{words.prompt}</q><p className="dim">{words.how}</p>
        <button className="btn sm ghost" onClick={() => void Promise.resolve(navigator.clipboard?.writeText(words.prompt)).then(() => setSaid("Copied.")).catch(() => {})}>Copy</button> <button className="btn sm ghost" onClick={() => setWords(null)}>Close</button></div>}
      {found && <div className="ss-heard"><p><b>Music already in your library</b></p>{found.rows.length === 0 ? <p className="dim">Nothing in the library fits yet.</p> :
        <ul>{found.rows.map((r) => <li key={r.id} className="sm-row">{r.name} <span className="dim">{r.why.join(", ")}</span>
          <button className="btn sm" disabled={!!busy} onClick={() => void save("spot", "spot_set", { id: found.id, asset_id: r.id }).then(() => setFound(null))}>Use this</button></li>)}</ul>}
        <button className="btn sm ghost" onClick={() => setFound(null)}>Close</button></div>}
      <div className="sm-row">
        <button className="btn sm" disabled={!!busy} onClick={() => void save("spot", "spot_set", { scene, decision: "score", start_shot: ids[0] ?? null, end_shot: ids[ids.length - 1] ?? null })}>Add a spot</button>
        <button className="btn sm ghost" disabled={!!busy} onClick={() => void go("suggest", async () => setSugg(await api.music<MusicSuggestion>("suggest", dir, { scene })))}>Suggest from the scene (free)</button>
        <button className="btn sm" disabled={!!busy || !mine.length} onClick={() => void go("cues", async () => {
          const r = await api.music<MusicPlan>("to_cues", dir, { scene }); setPlan(r); onChanged();
          setSaid(`Music in the film: ${r.made?.length ?? 0} made, ${r.updated?.length ?? 0} updated.${r.waiting?.length ? ` ${r.waiting.length} still need music.` : ""}${r.blocked?.length ? ` ${r.blocked.length} left out: the licence does not allow commercial use.` : ""}${r.silent?.length ? ` ${r.silent.length} kept quiet on purpose.` : ""}`);
        })}>Put into the film</button></div>
      {sugg && <div className="ss-heard" aria-label="Suggestion"><p><b>{DECISION_WORDS[sugg.proposal.decision]}</b>{sugg.proposal.mood ? `: ${sugg.proposal.mood}` : ""}{sugg.proposal.decision === "score" ? `, energy ${sugg.proposal.energy_in} to ${sugg.proposal.energy_out}` : ""}</p>
        {sugg.because.length > 0 ? <p className="dim">Words it acted on: {sugg.because.map((b) => `“${b.word}” (${b.shot})`).join(", ")}.</p> : <p className="dim">No word in this scene's action calls for music.</p>}
        <p className="dim">{sugg.note}</p>
        <button className="btn sm" disabled={!!busy} onClick={() => void save("spot", "spot_set", { ...sugg.proposal, scene, approval: "suggested" }).then(() => setSugg(null))}>Add it as a spot</button> <button className="btn sm ghost" onClick={() => setSugg(null)}>Not now</button></div>}

      <h4>Who approved which music <span className="dim">a record of your decisions, not a licence check</span></h4>
      {plan.report.records.length === 0 ? <p className="dim">No music is in the plan yet.</p> :
        <ul className="ss-cues">{plan.report.records.map((r) => <li key={r.id} className="sm-row"><b>{r.name}</b>
          <span className="dim">{r.status === "none" ? "no decision recorded" : `${r.status} by ${r.by}${r.scenes.length ? ` for scene${r.scenes.length === 1 ? "" : "s"} ${r.scenes.join(", ")}` : ""}`}</span>
          {r.problems.map((p) => <span key={p} className="ss-warn">{p}</span>)}
          <button className="btn sm ghost" onClick={() => setRec({ id: r.id, by: "", scenes: String(scene), ref: plan.records[r.id]?.licence_ref ?? "" })}>Record a decision…</button></li>)}</ul>}
      {rec && <div className="sm-row" aria-label="Record a decision">
        <input className="text-input" placeholder="Who is deciding" aria-label="Decided by" value={rec.by} maxLength={60} onChange={(e) => setRec({ ...rec, by: e.target.value })} />
        <input className="text-input" placeholder="Scenes, e.g. 1, 2" aria-label="For scenes" value={rec.scenes} onChange={(e) => setRec({ ...rec, scenes: e.target.value })} />
        <input className="text-input" placeholder="Licence note (where it came from, receipt…)" aria-label="Licence note" value={rec.ref} maxLength={300} onChange={(e) => setRec({ ...rec, ref: e.target.value })} />
        {(["approved", "revoked"] as const).map((st) => <button key={st} className={`btn sm ${st === "approved" ? "" : "ghost"}`} disabled={!!busy || !rec.by.trim()}
          onClick={() => void go("record", async () => { setPlan(await api.music<MusicPlan>("record_set", dir, { asset_id: rec.id, status: st, by: rec.by, scenes: csv(rec.scenes).map(Number).filter((n) => Number.isFinite(n)), licence_ref: rec.ref })); setRec(null); })}>{st === "approved" ? "Approve" : "Revoke"}</button>)}
        <button className="btn sm ghost" onClick={() => setRec(null)}>Cancel</button></div>}
      <p className="dim sm-note">Nothing here generates or buys music. The licence column comes from the music's own record in your library; a decision recorded here does not change it.</p>
    </section>
  );
}

function SpotRow({ s, ids, motifs, music, busy, onSave, onRemove, onPrompt, onFind }: { s: MusicSpot; ids: string[]; motifs: Motif[]; music: AudioAsset[]; busy: boolean; onSave: (p: Record<string, unknown>) => void; onRemove: () => void; onPrompt: () => void; onFind: () => void }) {
  return (
    <li className="sm-row" aria-label={`Spot ${s.id}`}>
      <select className="text-input" aria-label="Decision" value={s.decision} onChange={(e) => onSave({ decision: e.target.value })}>{(Object.keys(DECISION_WORDS) as MusicSpot["decision"][]).map((k) => <option key={k} value={k}>{DECISION_WORDS[k]}</option>)}</select>
      {s.decision === "score" && <>
        <select className="text-input" aria-label="From shot" value={s.start_shot ?? ""} onChange={(e) => onSave({ start_shot: e.target.value || null })}><option value="">Start of the scene</option>{ids.map((i) => <option key={i} value={i}>{i}</option>)}</select>
        <select className="text-input" aria-label="To shot" value={s.end_shot ?? ""} onChange={(e) => onSave({ end_shot: e.target.value || null })}><option value="">End of the scene</option>{ids.map((i) => <option key={i} value={i}>{i}</option>)}</select>
        <label>energy in <input className="text-input" type="number" min={0} max={5} defaultValue={s.energy_in} aria-label="Energy at the start" style={{ width: 56 }} onBlur={(e) => { const v = Number(e.target.value); if (v !== s.energy_in) onSave({ energy_in: v }); }} /></label>
        <label>out <input className="text-input" type="number" min={0} max={5} defaultValue={s.energy_out} aria-label="Energy at the end" style={{ width: 56 }} onBlur={(e) => { const v = Number(e.target.value); if (v !== s.energy_out) onSave({ energy_out: v }); }} /></label>
        <input className="text-input" placeholder="Mood" aria-label="Mood" defaultValue={s.mood} onBlur={(e) => { if (e.target.value !== s.mood) onSave({ mood: e.target.value }); }} />
        <input className="text-input" placeholder="Where it enters and why" aria-label="Where it enters" defaultValue={s.enters} onBlur={(e) => { if (e.target.value !== s.enters) onSave({ enters: e.target.value }); }} />
        {motifs.length > 0 && <span className="sm-row" role="group" aria-label="Motifs in this spot">{motifs.map((m) => <label key={m.id} className="ov-check"><input type="checkbox" checked={s.motif_ids.includes(m.id)}
          onChange={(e) => onSave({ motif_ids: e.target.checked ? [...s.motif_ids, m.id] : s.motif_ids.filter((x) => x !== m.id) })} /> {m.name}</label>)}</span>}
        <select className="text-input" aria-label="Music for this spot" value={s.asset_id ?? ""} onChange={(e) => onSave({ asset_id: e.target.value || null })}><option value="">No music chosen yet</option>{music.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}</select>
        <button className="btn sm ghost" disabled={busy} onClick={onPrompt}>Words to ask for it</button>
        <button className="btn sm ghost" disabled={busy} onClick={onFind}>Find in library</button></>}
      <select className="text-input" aria-label="Approval" value={s.approval} onChange={(e) => onSave({ approval: e.target.value })}><option value="suggested">Not approved yet</option><option value="approved">Approved</option><option value="rejected">Rejected</option></select>
      <span className="dim">{spotWords(s)}{s.cue ? " · in the film" : ""}</span>
      <button className="btn sm ghost" disabled={busy} onClick={onRemove} aria-label={`Remove spot ${s.id}`}>Remove</button>
    </li>
  );
}
