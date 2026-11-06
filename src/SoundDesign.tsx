import { useCallback, useEffect, useState } from "react";
import { api, errorText, type AudioAsset, type FoleyEvent, type FoleyProposal, type SoundDesignScene, type SoundProfile } from "./api";
import { ask } from "./ask";

/** Distance and side in plain words, as the mixer will treat them: a level and a stereo balance, nothing more. */
export const placementWords = (p: { gain_db: number; pan: number }): string => {
  const side = p.pan < -0.05 ? "to the left" : p.pan > 0.05 ? "to the right" : "in the centre";
  return `${p.gain_db > 0 ? "+" : ""}${p.gain_db} dB, ${side}`;
};

/** What is still missing in a scene, in one sentence. */
export const coverageWords = (c: SoundDesignScene["coverage"]): string => {
  const bits: string[] = [];
  if (!c.has_profile) bits.push(c.environment ? "this place has no soundscape yet" : "this scene has no place in the Bible");
  if (c.layers_without_sound.length) bits.push(`${c.layers_without_sound.length} ambience layer${c.layers_without_sound.length === 1 ? "" : "s"} still need a sound`);
  if (c.without_sound.length) bits.push(`${c.without_sound.length} sound${c.without_sound.length === 1 ? "" : "s"} still need a sound from the library`);
  return bits.length ? `Still to do: ${bits.join("; ")}.` : "Nothing is waiting for a sound.";
};

const csv = (s: string): string[] => s.split(",").map((x) => x.trim()).filter(Boolean);
const blank = (): SoundProfile => ({ interior: null, weather: "", time_of_day: "", room_size: "", materials: [], surfaces: [], reverb: "", layers: [], recurring: "", notes: "" });

/**
 * Sound design for one scene: the soundscape of the place (its ambience layers, each at a distance) and the few Foley sounds a shot's action really names. Both are plans; "Put into the film" turns
 * the approved ones that have a sound into ordinary cues, so the mixer, ducking and loudness work as for any cue. Distance and side become a level and a stereo balance, not a room simulation.
 */
export function SoundDesign({ dir, scene, assets, onChanged }: { dir: string; scene: number; assets: AudioAsset[]; onChanged: () => void }) {
  const [v, setV] = useState<SoundDesignScene | null>(null);
  const [p, setP] = useState<SoundProfile>(blank());
  const [busy, setBusy] = useState("");
  const [err, setErr] = useState("");
  const [open, setOpen] = useState(false);
  const [props, setProps] = useState<{ shot: string; items: FoleyProposal[]; note: string } | null>(null);
  const [found, setFound] = useState<{ id: string; rows: { id: string; name: string; why: string[] }[] } | null>(null);
  const [said, setSaid] = useState("");

  const load = useCallback(() => api.soundDesign("scene", dir, { scene }).then((r) => { setV(r); setP(r.profile ?? blank()); }).catch((e) => setErr(errorText(e))), [dir, scene]);
  useEffect(() => { if (open) void load(); }, [open, load]);
  const go = async (label: string, f: () => Promise<void>) => { setErr(""); setBusy(label); try { await f(); } catch (e) { setErr(errorText(e)); } finally { setBusy(""); } };
  const after = (r: SoundDesignScene) => { setV(r); setP(r.profile ?? p); };

  if (!open) return <section aria-label="Sound design"><h3>Sound design <span className="dim">the place's soundscape and the few sounds a shot names</span></h3>
    <p className="dim">Describe how this place always sounds, and let FilmCrafter propose the sounds each shot's action really names. Free; nothing is heard until you put it into the film.</p>
    <button className="btn sm" onClick={() => setOpen(true)}>Open sound design…</button></section>;
  if (!v) return <section aria-label="Sound design"><h3>Sound design</h3>{err ? <p className="error-text" role="alert">{err}</p> : <p className="dim">Looking…</p>}</section>;

  const set = (patch: Partial<SoundProfile>) => setP({ ...p, ...patch });
  const setLayer = (i: number, patch: Partial<SoundProfile["layers"][number]>) => set({ layers: p.layers.map((l, j) => (j === i ? { ...l, ...patch } : l)) });
  const dirty = JSON.stringify(p) !== JSON.stringify(v.profile ?? blank());
  const saveProfile = () => go("profile", async () => { if (!v.environment) return; after(await api.soundDesign("profile_set", dir, { environment: v.environment.id, profile: p })); });
  const suggest = (shot: string) => go("suggest", async () => { const r = await api.soundDesign<{ proposals: FoleyProposal[]; note: string }>("suggest", dir, { shot }); setProps({ shot, items: r.proposals, note: r.note }); });
  const addProposal = (shot: string, x: FoleyProposal) => go("add", async () => { after(await api.soundDesign("event_add", dir, { shot, ...x, source: "derived" })); setProps((q) => (q ? { ...q, items: q.items.filter((y) => y !== x) } : q)); });
  const addBlank = (shot: string) => go("add", async () => after(await api.soundDesign("event_add", dir, { shot, action: "sound", start: 0 })));
  const upd = (e: FoleyEvent, patch: Record<string, unknown>) => go("save", async () => after(await api.soundDesign("event_update", dir, { id: e.id, ...patch })));
  const remove = (e: FoleyEvent) => go("remove", async () => {
    if (!(await ask(`Take “${e.action}${e.source_object ? `: ${e.source_object}` : ""}” out of the plan?\n\nIt is kept aside, and its cue is taken out of the plan. The sound stays in your library.`, { ok: "Take it out" }))) return;
    after(await api.soundDesign("event_remove", dir, { id: e.id }));
  });
  const find = (e: FoleyEvent) => go("find", async () => { const r = await api.soundDesign<{ candidates: { id: string; name: string; why: string[] }[] }>("candidates", dir, { id: e.id }); setFound({ id: e.id, rows: r.candidates }); });
  const toCues = () => go("cues", async () => {
    const r = await api.soundDesign("to_cues", dir, { scene });
    after(r); onChanged();
    setSaid(`${r.made?.length ?? 0} made, ${r.updated?.length ?? 0} brought up to date${r.waiting?.length ? `, ${r.waiting.length} waiting for a sound` : ""}.`);
  });

  return (
    <section aria-label="Sound design" className="sd">
      <h3>Sound design <span className="dim">{v.environment ? v.environment.name : "no place in the Bible for this scene"}</span></h3>
      <p className="dim">{coverageWords(v.coverage)}</p>

      {v.environment && <>
        <h4>How this place sounds</h4>
        <div className="cw-fields">
          <label className="field"><span>Inside or outside</span><select value={p.interior === null ? "" : p.interior ? "in" : "out"} onChange={(e) => set({ interior: e.target.value === "" ? null : e.target.value === "in" })}>
            <option value="">not said</option><option value="in">inside</option><option value="out">outside</option></select></label>
          <label className="field"><span>Weather</span><input className="text-input" value={p.weather} maxLength={60} onChange={(e) => set({ weather: e.target.value })} placeholder="Heavy rain." /></label>
          <label className="field"><span>Time of day</span><input className="text-input" value={p.time_of_day} maxLength={40} onChange={(e) => set({ time_of_day: e.target.value })} placeholder="Night." /></label>
          <label className="field"><span>Room</span><select value={p.room_size} onChange={(e) => set({ room_size: e.target.value })}>{["", "small", "medium", "large", "open"].map((r) => <option key={r} value={r}>{r || "not said"}</option>)}</select></label>
          <label className="field"><span>Materials (commas)</span><input className="text-input" value={p.materials.join(", ")} onChange={(e) => set({ materials: csv(e.target.value) })} placeholder="tin, wood, stone" /></label>
          <label className="field"><span>Surfaces underfoot (commas)</span><input className="text-input" value={p.surfaces.join(", ")} onChange={(e) => set({ surfaces: csv(e.target.value) })} placeholder="wet pavement" /></label>
          <label className="field"><span>Reverb (a note)</span><select value={p.reverb} onChange={(e) => set({ reverb: e.target.value })}>{["", "dry", "room", "hall", "street", "outdoor"].map((r) => <option key={r} value={r}>{r || "not said"}</option>)}</select></label>
          <label className="field"><span>Sounds that come back</span><input className="text-input" value={p.recurring} maxLength={300} onChange={(e) => set({ recurring: e.target.value })} placeholder="The generator coughs now and then." /></label>
        </div>
        <p className="dim sm-note">Reverb is a note for you and for making sounds; the mixer does not add reverb yet.</p>

        <h4>Ambience layers <span className="dim">the same in every shot of the scene</span></h4>
        {p.layers.map((l, i) => <div key={l.id} className="ls-btns pp-row">
          <label>Layer <input className="text-input" value={l.name} maxLength={60} onChange={(e) => setLayer(i, { name: e.target.value })} aria-label={`Layer ${i + 1} name`} /></label>
          <label>Distance <select value={l.distance} onChange={(e) => setLayer(i, { distance: e.target.value as "near" | "mid" | "far" })} aria-label={`Layer ${i + 1} distance`}><option value="near">near</option><option value="mid">middle</option><option value="far">far</option></select></label>
          <label>Level <input type="range" min={-30} max={0} step={1} value={l.level_db} onChange={(e) => setLayer(i, { level_db: Number(e.target.value) })} aria-label={`Layer ${i + 1} level`} /></label>
          <label>Sound <select value={l.asset_id ?? ""} onChange={(e) => setLayer(i, { asset_id: e.target.value || null })} aria-label={`Layer ${i + 1} sound`}><option value="">none yet</option>{assets.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}</select></label>
          <button className="link" onClick={() => set({ layers: p.layers.filter((_, j) => j !== i) })} aria-label={`Remove layer ${i + 1}`}>Remove</button></div>)}
        <div className="ls-btns">
          <button className="btn sm ghost" disabled={p.layers.length >= 12} onClick={() => set({ layers: [...p.layers, { id: "", name: "New layer", distance: "mid", level_db: -6, asset_id: null, loop: true, description: "", cue_id: null }] })}>Add a layer</button>
          <button className="btn sm" disabled={!!busy || !dirty} onClick={() => void saveProfile()}>Save how this place sounds</button>
        </div>
      </>}

      <h4>Foley <span className="dim">only sounds a shot's action names</span></h4>
      {v.shots.map((s) => <div key={s.id} className="ls-btns">
        <span className="num">{s.id}</span>
        <button className="btn sm ghost" disabled={!!busy} onClick={() => void suggest(s.id)} aria-label={`Suggest sounds for ${s.id}`}>Suggest sounds</button>
        <button className="btn sm ghost" disabled={!!busy} onClick={() => void addBlank(s.id)} aria-label={`Add a sound to ${s.id}`}>Add one myself</button></div>)}
      {props && <div aria-label="Suggestions"><p className="dim">{props.items.length ? `For ${props.shot}: ` : `Nothing in ${props.shot}'s action names a sound. `}{props.note}</p>
        <ul className="vid-rows">{props.items.map((x, i) => <li key={i}><b>{x.action}</b>: {x.source_object}{x.by ? ` (${x.by})` : ""} <span className="dim">{[x.material, x.surface].filter(Boolean).join(", ")} · about {x.start} s · because “…{x.motivated_by}…”</span>
          <button className="btn sm" disabled={!!busy} onClick={() => void addProposal(props.shot, x)}>Add to the plan</button></li>)}</ul>
        <button className="link" onClick={() => setProps(null)}>Close suggestions</button></div>}

      <ul className="vid-rows" aria-label="Foley sounds">{v.events.map((e) => <li key={e.id}>
        <div><b>{e.action}</b>{e.source_object ? `: ${e.source_object}` : ""} <span className="dim">{e.shot} · {placementWords(e.placement)}{e.cue ? " · in the film" : ""}</span></div>
        <div className="ls-btns pp-row">
          <label>Action <input className="text-input" maxLength={60} onBlur={(ev) => { if (ev.target.value !== e.action) void upd(e, { action: ev.target.value }); }} onChange={() => {}} defaultValue={e.action} aria-label={`Action of ${e.id}`} /></label>
          <label>At (s) <input type="number" min={0} step={0.1} defaultValue={e.start} onBlur={(ev) => { if (Number(ev.target.value) !== e.start) void upd(e, { start: Number(ev.target.value) }); }} aria-label={`Start of ${e.id}`} /></label>
          <label>Distance <select value={e.distance} onChange={(ev) => void upd(e, { distance: ev.target.value })} aria-label={`Distance of ${e.id}`}><option value="near">near</option><option value="mid">middle</option><option value="far">far</option></select></label>
          <label>Side <select value={e.side} onChange={(ev) => void upd(e, { side: ev.target.value })} aria-label={`Side of ${e.id}`}><option value="left">left</option><option value="centre">centre</option><option value="right">right</option></select></label>
          <label>Sound <select value={e.asset_id ?? ""} onChange={(ev) => void upd(e, { asset_id: ev.target.value || null })} aria-label={`Sound of ${e.id}`}><option value="">none yet</option>{assets.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}</select></label>
          <button className="btn sm ghost" disabled={!!busy} onClick={() => void find(e)}>Find in my library</button>
          <label className="ov-check"><input type="checkbox" checked={e.approval === "approved"} onChange={(ev) => void upd(e, { approval: ev.target.checked ? "approved" : "suggested" })} aria-label={`Approve ${e.id}`} /> Approved</label>
          <button className="link" onClick={() => void remove(e)} aria-label={`Remove ${e.id}`}>Remove</button></div>
        {found?.id === e.id && <div className="dim">{found.rows.length ? <>In your library: {found.rows.map((r) => <button key={r.id} className="ls-chip" onClick={() => { void upd(e, { asset_id: r.id }); setFound(null); }}>{r.name}</button>)}</> : "Nothing in your library fits. Import or make one in Sound effects."}</div>}
      </li>)}</ul>

      <div className="ls-btns">
        <button className="btn primary" disabled={!!busy} onClick={() => void toCues()}>{busy === "cues" ? "Putting it in…" : "Put into the film"}</button>
        <span className="dim">Makes or updates ordinary cues for the approved layers and sounds that have a sound. {said}</span>
      </div>
      {v.waiting?.length ? <p className="dim" aria-label="Waiting">Waiting for a sound: {v.waiting.map((w) => w.name).join(", ")}.</p> : null}
      {err && <p className="error-text" role="alert">{err}</p>}
    </section>
  );
}
