import { ProAudio } from "./ProAudio";
import { AudioCheck } from "./AudioCheck";
import { SoundDesign } from "./SoundDesign";
import { useCallback, useEffect, useMemo, useState } from "react";
import { api, errorText, type AiPrice, type AudioLibrary, type CueList, type MixPreview, type MixSettings, type RightsReport, type SoundIdea, type SoundIdeas, type Cue } from "./api";
import { notifyCues } from "./CueLanes";
import { OutdatedPanel } from "./OutdatedPanel";
import { ask } from "./ask";
import { aiAskWords, audioFacts } from "./soundWords";

const KIND_WORDS: Record<string, string> = { dialogue: "Dialogue", sfx: "Sound effect", ambience: "Ambience", music: "Music" };
const FRESH_SHORT: Record<string, string> = { asset_removed: "sound taken out", asset_changed: "sound replaced", asset_missing: "file missing", shot_gone: "shot gone", timing_changed: "shot length changed", after_shot: "starts after the shot" };

/**
 * A scene's planned soundscape: the sounds and music that belong to it, where they start, how loud they are and how they fade. These are plans: nothing here makes sound or costs anything.
 * Ideas come from your own sound notes and the place (free, on this computer) or from the writing AI (price first); each idea shows what your library already has before anything new is wanted,
 * and nothing is saved until you add it. A sound you replace or a shot you resize is flagged on its cue, never changed behind your back.
 */
export function SceneSound({ dir }: { dir: string }) {
  const [list, setList] = useState<CueList | null>(null);
  const [lib, setLib] = useState<AudioLibrary | null>(null);
  const [scene, setScene] = useState<number | null>(null);
  const [ideas, setIdeas] = useState<SoundIdeas | null>(null);
  const [busy, setBusy] = useState("");
  const [err, setErr] = useState("");
  const [adding, setAdding] = useState(false);
  const [rights, setRights] = useState<RightsReport | null>(null);
  const [mix, setMix] = useState<MixSettings | null>(null);
  const [heard, setHeard] = useState<MixPreview | null>(null);
  const reload = useCallback(async () => {
    try { const [l, a] = await Promise.all([api.filmCues("list", dir), api.filmAudio("list", dir)]); setList(l); setLib(a); api.audioGen<RightsReport>("rights", dir).then(setRights).catch(() => {}); api.audioMix<MixSettings>("settings", dir).then(setMix).catch(() => {}); } catch (e) { setErr(errorText(e)); }
  }, [dir]);
  useEffect(() => { void reload(); }, [reload]);
  const scenes = useMemo(() => Object.keys(list?.scenes ?? {}).map(Number).sort((a, b) => a - b), [list]);
  useEffect(() => { if (scene === null && scenes.length) setScene(scenes[0]); }, [scene, scenes]);
  const go = async (what: string, f: () => Promise<unknown>) => { setErr(""); setBusy(what); try { await f(); } catch (e) { setErr(errorText(e)); } finally { setBusy(""); } };

  if (!list) return <p className="dim">{err || "Opening the scenes…"}</p>;
  if (!scenes.length || scene === null) return <p className="dim cw-empty">No scenes yet. Scenes appear when the story is broken into shots.</p>;
  const info = list.scenes[String(scene)];
  const cues = list.cues.filter((c) => c.scene === scene);
  const dialogue = list.dialogue.filter((x) => x.scene === scene);
  const assets = (lib?.assets ?? []).filter((a) => a.approval !== "rejected");

  const quick = () => go("quick", async () => setIdeas(await api.filmCues<SoundIdeas>("quick", dir, { scene })));
  const direct = () => go("ai", async () => {
    const est = await api.filmCues<AiPrice>("director_estimate", dir, { scene });
    if (!(await ask(aiAskWords(`Suggest a soundscape for scene ${scene}?`, est.sends, est), { ok: "Suggest" }))) return;
    setIdeas(await api.filmCues<SoundIdeas>("director_suggest", dir, { scene }));
  });
  const place = (i: SoundIdea, assetId: string | null) => go("add", async () => {
    const r = await api.filmCues("add", dir, { scene, ...(i.shot ? { shot: i.shot } : {}), kind: i.kind, ...(assetId ? { asset_id: assetId } : { plan: { description: i.what, search: i.search } }), loop: i.loop,
      source: ideas?.source === "director" ? "director" : "quick", approval: "approved" });
    void r; await reload();
  });
  const act = (what: string, f: () => Promise<unknown>) => go(what, async () => { await f(); await reload(); notifyCues(); });

  return (
    <div className="ss">
      <div className="ss-scenes" role="tablist" aria-label="Scenes">{scenes.map((n) => <button key={n} role="tab" aria-selected={n === scene} className={n === scene ? "on" : ""} onClick={() => { setScene(n); setIdeas(null); }}>Scene {n}</button>)}</div>
      <p className="dim ss-lead">{info.shots.length} shot{info.shots.length === 1 ? "" : "s"}, {info.seconds.toFixed(1)} s. {dialogue.length ? `${dialogue.length} spoken line${dialogue.length === 1 ? "" : "s"} already have a voice and stay as they are.` : "No voice recorded in this scene yet."} Plans only: nothing here makes sound or costs anything.</p>

      <OutdatedPanel dir={dir} />
      {rights && !rights.ok && <p className="ss-warn" role="status">Before you release the film: {rights.blocking.length === 1 ? "one sound in the plan has" : `${rights.blocking.length} sounds in the plan have`} rights you have not confirmed ({rights.blocking.map((r) => r.name).slice(0, 3).join(", ")}). Open it in the library and set “commercial use”.</p>}
      <section>
        <h3>The soundscape <span className="dim">{cues.length} cue{cues.length === 1 ? "" : "s"}{list.counts.needs_sound ? ` · ${list.counts.needs_sound} still need a sound` : ""}</span></h3>
        {cues.length === 0 && <p className="dim">Nothing planned for this scene yet. Ask for ideas below, or add a sound you have.</p>}
        <ul className="ss-cues">{cues.map((c) => <CueRow key={c.id} dir={dir} c={c} assets={assets} onSave={(d) => act("save", () => api.filmCues("update", dir, { id: c.id, ...d }))}
                                                     onApprove={(s) => act("approve", () => api.filmCues("approve", dir, { id: c.id, state: s }))} onRemove={() => act("remove", () => api.filmCues("remove", dir, { id: c.id }))}
                                                     onRefresh={() => act("refresh", () => api.filmCues("refresh", dir, { id: c.id }))} />)}</ul>
        <div className="sm-row">
          <button className="btn" disabled={!!busy || assets.length === 0} onClick={() => setAdding(true)}>Add a sound from the library…</button>
          {assets.length === 0 && <span className="dim">Import sounds first (Sound effects or Music).</span>}
          {list.removed.length > 0 && <details className="sm-removed"><summary>{list.removed.length} removed</summary><ul>{list.removed.map((r) => <li key={r.id}>{KIND_WORDS[r.kind] ?? r.kind} <button className="link" onClick={() => void act("restore", () => api.filmCues("restore", dir, { id: r.id }))}>Bring it back</button></li>)}</ul></details>}
        </div>
        {adding && <AddCue shots={info.shots.map((s) => s.id)} assets={assets} onCancel={() => setAdding(false)}
                           onAdd={(d) => { setAdding(false); void act("add", () => api.filmCues("add", dir, { scene, ...d })); }} />}
      </section>

      {dialogue.length > 0 && <section><h3>Dialogue <span className="dim">your voice files, shown here so you see the whole scene</span></h3>
        <ul className="ss-cues dlg">{dialogue.map((x) => <li key={x.id}><b>{x.speaker}</b> <span className="dim">{x.shot} · {x.source === "elevenlabs" ? "spoken by ElevenLabs" : "your recording"}</span> <q>{x.text}</q></li>)}</ul></section>}

      <SoundDesign dir={dir} scene={scene} assets={assets} onChanged={() => void reload()} />

      <AudioCheck dir={dir} />
      <ProAudio dir={dir} />

      <section>
        <h3>How it is mixed <span className="dim">for the whole film</span></h3>
        {mix && <div className="ss-mix">
          <label className="field"><span>Music and ambience dip under voices: {mix.ducking_db === 0 ? "not at all" : `${mix.ducking_db} dB`}</span>
            <input type="range" min={-24} max={0} step={1} value={mix.ducking_db} aria-label="How far music dips under voices" onChange={(e) => setMix({ ...mix, ducking_db: Number(e.target.value) })}
                   onMouseUp={() => void act("mix", () => api.audioMix("set_settings", dir, { ducking_db: mix.ducking_db }))} onKeyUp={() => void act("mix", () => api.audioMix("set_settings", dir, { ducking_db: mix.ducking_db }))} /></label>
          <label className="field"><span>Loudness of the finished film</span>
            <select className="text-input" value={mix.target_lufs === null ? "" : String(mix.target_lufs)} onChange={(e) => void act("mix", () => api.audioMix("set_settings", dir, { target_lufs: e.target.value === "" ? null : Number(e.target.value) }))}>
              <option value="">Leave as it is</option><option value="-23">Broadcast (-23 LUFS)</option><option value="-16">Online video (-16 LUFS)</option><option value="-14">Loud streaming (-14 LUFS)</option></select></label>
          <label className="field"><span>Never louder than</span>
            <select className="text-input" value={String(mix.peak_db)} onChange={(e) => void act("mix", () => api.audioMix("set_settings", dir, { peak_db: Number(e.target.value) }))}>
              <option value="-1">-1 dB (safe)</option><option value="-2">-2 dB</option><option value="-3">-3 dB</option><option value="-6">-6 dB</option></select></label>
          <div className="field"><span>Leave out of the film</span>
            <div className="sm-row">{(["foley", "sfx", "ambience", "music"] as const).map((k) => <label key={k} className="ov-check"><input type="checkbox" checked={mix.mute_lanes.includes(k)}
              onChange={(e) => void act("mix", () => api.audioMix("set_settings", dir, { mute_lanes: e.target.checked ? [...mix.mute_lanes, k] : mix.mute_lanes.filter((x) => x !== k) }))} /> {k === "foley" ? "Foley" : k === "sfx" ? "Effects" : k === "ambience" ? "Ambience" : "Music"}</label>)}</div></div>
        </div>}
        <div className="sm-row"><span className="dim">Hear this scene:</span>
          {([[null, "Everything"], ["dialogue", "Voices only"], ["foley", "Foley only"], ["sfx", "Effects only"], ["ambience", "Ambience only"], ["music", "Music only"]] as [string | null, string][]).map(([k, label]) =>
            <button key={label} className="btn sm ghost" disabled={!!busy} onClick={() => void go("hear", async () => setHeard(await api.audioMix<MixPreview>("preview", dir, { scene, solo: k })))}>{label}</button>)}</div>
        <div className="sm-row"><span className="dim">Hear the whole film:</span>
          {([[null, "Everything"], ["dialogue", "Voices only"], ["foley", "Foley only"], ["sfx", "Effects only"], ["ambience", "Ambience only"], ["music", "Music only"]] as [string | null, string][]).map(([k, label]) =>
            <button key={label} className="btn sm ghost" disabled={!!busy} title="Every scene's voices and approved sound, laid end to end, as the exported film will sound (without the picture and without the loudness target)"
              onClick={() => void go("hear", async () => setHeard(await api.audioMix<MixPreview>("preview", dir, { scene: "all", solo: k })))}>{label}</button>)}</div>
        {heard && <div className="ss-heard"><audio controls autoPlay src={`${api.mediaUrl(`${dir}/${heard.file}`)}?v=${Date.now()}`} aria-label={heard.whole ? "The whole film's mix" : "The scene's mix"} />
          <span className="dim">{heard.whole ? "Whole film · " : ""}{heard.cues} cue{heard.cues === 1 ? "" : "s"} · {heard.seconds.toFixed(1)} s{heard.ducked ? " · music dips under the voices" : ""}{heard.solo ? ` · ${heard.solo} only (a preview: the film is not changed)` : ""}</span>
          {heard.skipped.map((s) => <span key={s.cue} className="ss-warn">One cue was left out: {s.why}</span>)}</div>}
        <p className="dim sm-note">The finished film is mixed when you export it: approved cues only, the voices on top, a limiter so nothing clips. Muting here leaves a lane out of the film; the previews only help you listen.</p>
      </section>

      <section>
        <h3>The shots' sound notes</h3>
        <ul className="ss-notes">{info.shots.map((s) => <Note key={s.id} id={s.id} seconds={s.seconds} text={s.sound} onSave={(t) => act("note", () => api.shots("set", dir, { id: s.id, patch: { sound: t } }))} />)}</ul>
      </section>

      <section>
        <h3>Ideas <span className="dim">suggestions only: nothing is saved until you add it</span></h3>
        <div className="sm-row">
          <button className="btn ghost" disabled={!!busy} onClick={() => void quick()}>{busy === "quick" ? "Looking…" : "Quick ideas (free)"}</button>
          <button className="btn" disabled={!!busy} onClick={() => void direct()}>{busy === "ai" ? "Listening to the scene…" : "Ask the sound director…"}</button>
        </div>
        {ideas && ideas.ideas.length === 0 && <p className="dim">No ideas for this scene. Add a sound note to a shot above, or add your own sounds.</p>}
        {ideas && <ul className="ss-ideas">{ideas.ideas.map((i) => <li key={`${i.kind}-${i.what}`}><div><b>{i.what}</b> <span className="dim">{KIND_WORDS[i.kind]}{i.shot ? ` · ${i.shot}` : " · whole scene"}{i.loop ? " · loops" : ""}</span>
          <div className="dim">{i.why}</div></div>
          <div className="ss-match">{i.matches.length ? i.matches.map((m, k) => <button key={m.asset_id} className={`btn sm ${k ? "ghost" : ""}`} disabled={!!busy} onClick={() => void place(i, m.asset_id)} title={m.why.length ? `fits: ${m.why.join(", ")}` : ""}>
            Use “{m.name}” ({audioFacts({ seconds: m.seconds, approval: m.approved ? "approved" : "pending" })})</button>)
            : <span className="dim">Nothing in your library fits yet.</span>}
            <button className="link" disabled={!!busy} onClick={() => void place(i, null)}>Plan it (needs a sound)</button></div></li>)}</ul>}
      </section>
      {err && <p className="error-text" role="alert">{err}</p>}
    </div>
  );
}

function Note({ id, seconds, text, onSave }: { id: string; seconds: number; text: string; onSave: (t: string) => void }) {
  const [v, setV] = useState(text);
  useEffect(() => setV(text), [text]);
  return <li><span className="ss-id">{id} <span className="dim">{seconds.toFixed(1)} s</span></span>
    <input className="text-input" value={v} placeholder="What should be heard in this shot (a kettle clicking, distant thunder)" aria-label={`Sound note for ${id}`} onChange={(e) => setV(e.target.value)}
           onBlur={() => { if (v !== text) onSave(v); }} /></li>;
}

function CueRow({ dir, c, assets, onSave, onApprove, onRemove, onRefresh }: { dir: string; c: Cue; assets: { id: string; name: string; kind: string }[]; onSave: (d: Record<string, unknown>) => void;
  onApprove: (s: "suggested" | "approved" | "rejected") => void; onRemove: () => void; onRefresh: () => void }) {
  const [open, setOpen] = useState(false);
  const [d, setD] = useState({ start: String(c.start), duration: c.duration === null ? "" : String(c.duration), gain_db: String(c.gain_db), fade_in: String(c.fade_in), fade_out: String(c.fade_out), loop: c.loop, ducking: c.ducking, note: c.note });
  const dirty = JSON.stringify(d) !== JSON.stringify({ start: String(c.start), duration: c.duration === null ? "" : String(c.duration), gain_db: String(c.gain_db), fade_in: String(c.fade_in), fade_out: String(c.fade_out), loop: c.loop, ducking: c.ducking, note: c.note });
  const field = (k: "start" | "duration" | "gain_db" | "fade_in" | "fade_out", label: string, hint: string) => <label className="field"><span>{label}</span>
    <input className="text-input" inputMode="decimal" value={d[k]} placeholder={hint} onChange={(e) => setD({ ...d, [k]: e.target.value })} /></label>;
  return (
    <li className={`ss-cue ${c.approval}`}>
      <div className="ss-head">
        <span className={`sm-badge ${c.approval === "approved" ? "approved" : c.approval === "rejected" ? "rejected" : ""}`}>{c.approval === "approved" ? "Approved" : c.approval === "rejected" ? "Rejected" : "Suggested"}</span>
        <b>{c.asset_name ?? c.plan?.description ?? "A sound"}</b>
        <span className="dim">{KIND_WORDS[c.kind]} · {c.shot ?? "whole scene"} · from {c.start.toFixed(1)} s{c.duration ? ` for ${c.duration.toFixed(1)} s` : ""} · {c.gain_db > 0 ? "+" : ""}{c.gain_db} dB{c.loop ? " · loops" : ""}</span>
        <span style={{ flex: 1 }} />
        {c.asset_file && <audio className="ss-audio" controls preload="none" src={api.mediaUrl(`${dir}/${c.asset_file}`)} aria-label={`Hear ${c.asset_name}`} />}
        <button className="link" onClick={() => setOpen(!open)}>{open ? "Close" : "Adjust"}</button>
      </div>
      {c.needs_sound && <p className="ss-warn">This cue still needs a sound. {assets.length ? "Choose one from your library below, or import one." : "Import one in Sound effects or Music."}</p>}
      {c.fresh.length > 0 && <p className="ss-warn" role="status">May need another look: {c.fresh.map((f) => FRESH_SHORT[f.code] ?? f.code).join(", ")}. {c.fresh[0].why} <button className="link" onClick={onRefresh}>It is fine</button></p>}
      {open && <div className="ss-edit">
        {c.needs_sound && <label className="field"><span>Use this sound</span><select className="text-input" value="" onChange={(e) => e.target.value && onSave({ asset_id: e.target.value })}>
          <option value="">Choose from your library…</option>{assets.filter((a) => (c.kind === "music") === (a.kind === "music")).map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}</select></label>}
        <div className="cw-fields">{field("start", "Starts at (seconds into the shot)", "0")}{field("duration", "Lasts (seconds, empty = all of it)", "")}{field("gain_db", "Level (dB, 0 is as made)", "0")}
          {field("fade_in", "Fade in (seconds)", "0")}{field("fade_out", "Fade out (seconds)", "0")}
          <label className="field"><span>Music and ambience dip under voices</span><select className="text-input" value={d.ducking} onChange={(e) => setD({ ...d, ducking: e.target.value as "auto" | "on" | "off" })}>
            <option value="auto">Automatic</option><option value="on">Always</option><option value="off">Never</option></select></label></div>
        <label className="ov-check"><input type="checkbox" checked={d.loop} onChange={(e) => setD({ ...d, loop: e.target.checked })} /> Repeat to fill the time</label>
        <label className="field"><span>Note</span><input className="text-input" value={d.note} onChange={(e) => setD({ ...d, note: e.target.value })} /></label>
        <div className="sm-row"><button className="btn sm" disabled={!dirty} onClick={() => onSave({ start: d.start, duration: d.duration, gain_db: d.gain_db, fade_in: d.fade_in, fade_out: d.fade_out, loop: d.loop, ducking: d.ducking, note: d.note })}>Save</button>
          <button className="btn sm" disabled={c.approval === "approved"} onClick={() => onApprove("approved")}>Approve</button>
          <button className="btn sm ghost" disabled={c.approval === "rejected"} onClick={() => onApprove("rejected")}>Reject</button>
          <span style={{ flex: 1 }} /><button className="link" onClick={onRemove}>Remove from the plan</button></div>
        <p className="dim sm-note">Adjusting a cue never changes the sound file. Removing it only takes it out of the plan.</p>
      </div>}
    </li>
  );
}

function AddCue({ shots, assets, onAdd, onCancel }: { shots: string[]; assets: { id: string; name: string; kind: string }[]; onAdd: (d: Record<string, unknown>) => void; onCancel: () => void }) {
  const [asset, setAsset] = useState("");
  const [shot, setShot] = useState("");
  const [start, setStart] = useState("0");
  return (
    <div className="ss-add">
      <label className="field"><span>Sound or music</span><select className="text-input" value={asset} onChange={(e) => setAsset(e.target.value)}>
        <option value="">Choose…</option>{assets.map((a) => <option key={a.id} value={a.id}>{a.kind === "music" ? "Music: " : ""}{a.name}</option>)}</select></label>
      <label className="field"><span>Where</span><select className="text-input" value={shot} onChange={(e) => setShot(e.target.value)}>
        <option value="">The whole scene</option>{shots.map((s) => <option key={s} value={s}>Shot {s}</option>)}</select></label>
      <label className="field"><span>Starts at (seconds)</span><input className="text-input" inputMode="decimal" value={start} onChange={(e) => setStart(e.target.value)} /></label>
      <div className="sm-row"><button className="btn sm" disabled={!asset} onClick={() => onAdd({ asset_id: asset, ...(shot ? { shot } : {}), start })}>Add to the scene</button><button className="link" onClick={onCancel}>Cancel</button></div>
    </div>
  );
}
