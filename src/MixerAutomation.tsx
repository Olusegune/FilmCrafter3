import { useCallback, useEffect, useState } from "react";
import { api, errorText, type AutoPoint, type Crossfaded, type Cue, type MixSettings } from "./api";

export const LANES: [string, string][] = [["master", "Whole film"], ["dialogue", "Voices"], ["foley", "Foley"], ["sfx", "Effects"], ["ambience", "Ambience"], ["music", "Music"]];
export const SHAPES: [AutoPoint["curve"], string][] = [["linear", "Straight"], ["smooth", "Eased"], ["hold", "Step"]];
export const DB_MIN = -60, DB_MAX = 12;

/** The level in words, e.g. "-6 dB" or "unchanged". */
export const dbWords = (db: number): string => (db === 0 ? "unchanged" : `${db > 0 ? "+" : ""}${db} dB`);

/** The points of a curve as an SVG path (time across, level up). The same rule as the mixer: held before the first point and after the last; "hold" steps at the next point. */
export function curvePath(points: AutoPoint[], seconds: number, w = 300, h = 70): string {
  if (!points.length || seconds <= 0) return "";
  const x = (t: number) => Math.min(w, Math.max(0, (t / seconds) * w));
  const y = (db: number) => h - ((Math.min(DB_MAX, Math.max(DB_MIN, db)) - DB_MIN) / (DB_MAX - DB_MIN)) * h;
  let d = `M0 ${y(points[0].db).toFixed(1)}`;
  points.forEach((p, i) => {
    const next = points[i + 1];
    d += ` L${x(p.t).toFixed(1)} ${y(p.db).toFixed(1)}`;
    if (!next) return;
    if (p.curve === "hold") d += ` L${x(next.t).toFixed(1)} ${y(p.db).toFixed(1)}`;
    else if (p.curve === "smooth") for (let k = 1; k < 8; k++) { const u = k / 8, e = u * u * (3 - 2 * u); d += ` L${x(p.t + (next.t - p.t) * u).toFixed(1)} ${y(p.db + (next.db - p.db) * e).toFixed(1)}`; }
  });
  return `${d} L${w} ${y(points[points.length - 1].db).toFixed(1)}`;
}

/**
 * Volume curves for the whole film (voices, each sound lane, or everything), named groups of cues with one level and one mute, markers on the timeline, and a crossfade between two sounds.
 * Free and local; curves are in the film's own time and snap to frames. A curve changes how loud, never what plays. Nothing is deleted: clearing a curve returns the level to what the cues say.
 */
export function MixerAutomation({ dir, cues, onChanged }: { dir: string; cues: Cue[]; onChanged?: () => void }) {
  const [mix, setMix] = useState<MixSettings | null>(null);
  const [lane, setLane] = useState("music");
  const [busy, setBusy] = useState("");
  const [err, setErr] = useState("");
  const [note, setNote] = useState("");
  const [gname, setGname] = useState("");
  const [mt, setMt] = useState("");
  const [mname, setMname] = useState("");
  const [xa, setXa] = useState("");
  const [xb, setXb] = useState("");
  const [xs, setXs] = useState("1");

  const load = useCallback(() => { api.audioMix<MixSettings>("settings", dir).then(setMix).catch((e) => setErr(errorText(e))); }, [dir]);
  useEffect(() => { load(); }, [load]);

  const run = async (label: string, f: () => Promise<void>): Promise<boolean> => { setErr(""); setNote(""); setBusy(label); try { await f(); return true; } catch (e) { setErr(errorText(e)); return false; } finally { setBusy(""); } };
  const save = (action: "automation_set" | "group_set" | "group_remove" | "marker_add" | "marker_remove", data: Record<string, unknown>, label: string) => run(label, async () => { setMix(await api.audioMix<MixSettings>(action, dir, data)); onChanged?.(); });

  if (!mix) return <section aria-label="Volume curves and groups"><h3>Volume curves and groups</h3>{err ? <p className="ss-warn" role="alert">{err}</p> : <p className="dim">Loading…</p>}</section>;
  const points = mix.automation?.[lane] ?? [];
  const groups = Object.entries(mix.groups ?? {});
  const markers = mix.markers ?? [];
  const seconds = Math.max(10, ...Object.values(mix.automation ?? {}).flat().map((p) => p.t + 2), ...markers.map((m) => m.t + 2));
  const setPoints = (next: AutoPoint[]) => save("automation_set", { lane, points: next }, "curve");
  const edit = (i: number, patch: Partial<AutoPoint>) => setPoints(points.map((p, k) => (k === i ? { ...p, ...patch } : p)));
  const sounds = cues.filter((c) => c.kind !== "dialogue" && !c.needs_sound);
  const zero = 70 - ((0 - DB_MIN) / (DB_MAX - DB_MIN)) * 70;

  return (
    <section aria-label="Volume curves and groups">
      <h3>Volume curves and groups <span className="dim">level over time, group faders, markers, crossfades</span></h3>
      {err && <p className="ss-warn" role="alert">{err}</p>}
      {note && <p className="dim" role="status">{note}</p>}

      <div className="field"><span>Volume curve for</span>
        <div className="sm-row">{LANES.map(([k, label]) => <button key={k} className={`btn sm ${lane === k ? "" : "ghost"}`} aria-pressed={lane === k} onClick={() => setLane(k)}>{label}{(mix.automation?.[k]?.length ?? 0) > 0 ? " •" : ""}</button>)}</div></div>
      {points.length > 0 && <svg viewBox="0 0 300 70" className="ss-curve" role="img" aria-label={`${points.length} point curve`} style={{ width: "100%", maxWidth: 420, height: 70 }}>
        <line x1="0" x2="300" y1={zero} y2={zero} stroke="currentColor" strokeOpacity="0.25" strokeDasharray="3 3" />
        <path d={curvePath(points, seconds)} fill="none" stroke="currentColor" strokeWidth="1.6" /></svg>}
      {points.length === 0 ? <p className="dim">No curve: this lane stays at the level its cues give it.</p> :
        <ul className="ss-cues">{points.map((p, i) => <li key={`${p.t}-${p.db}-${p.curve}-${i}`} className="sm-row">
          <label>at <input className="text-input" type="number" step={0.04} min={0} defaultValue={p.t} aria-label={`Point ${i + 1} time in seconds`} onBlur={(e) => { const v = Number(e.target.value); if (v !== p.t && Number.isFinite(v)) void edit(i, { t: v }); }} style={{ width: 80 }} /> s</label>
          <label><input className="text-input" type="number" step={1} min={DB_MIN} max={DB_MAX} defaultValue={p.db} aria-label={`Point ${i + 1} level in dB`} onBlur={(e) => { const v = Number(e.target.value); if (v !== p.db && Number.isFinite(v)) void edit(i, { db: v }); }} style={{ width: 70 }} /> dB <span className="dim">({dbWords(p.db)})</span></label>
          <select className="text-input" value={p.curve} aria-label={`Point ${i + 1} shape`} onChange={(e) => void edit(i, { curve: e.target.value as AutoPoint["curve"] })}>{SHAPES.map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select>
          <button className="btn sm ghost" disabled={!!busy} onClick={() => void setPoints(points.filter((_, k) => k !== i))} aria-label={`Remove point ${i + 1}`}>Remove</button></li>)}</ul>}
      <div className="sm-row">
        <button className="btn sm" disabled={!!busy} onClick={() => void setPoints([...points, { t: points.length ? points[points.length - 1].t + 2 : 0, db: points.length ? points[points.length - 1].db : -6, curve: "linear" }])}>Add a point</button>
        {points.length > 0 && <button className="btn sm ghost" disabled={!!busy} onClick={() => void setPoints([])}>Clear this curve</button>}
        <span className="dim">Each point says how loud from then on; between points the level moves the way the earlier point's shape says. Times snap to frames.</span></div>

      <h4>Groups <span className="dim">give several cues one fader and one mute</span></h4>
      {groups.length === 0 && <p className="dim">No groups yet. Make one, then choose it on a cue.</p>}
      <ul className="ss-cues">{groups.map(([name, g]) => <li key={name} className="sm-row"><b>{name}</b>
        <label>level <input className="text-input" type="number" step={1} min={DB_MIN} max={DB_MAX} defaultValue={g.gain_db} aria-label={`${name} level in dB`} onBlur={(e) => { const v = Number(e.target.value); if (v !== g.gain_db && Number.isFinite(v)) void save("group_set", { name, gain_db: v }, "group"); }} style={{ width: 70 }} /> dB</label>
        <label className="ov-check"><input type="checkbox" checked={g.muted} onChange={(e) => void save("group_set", { name, muted: e.target.checked }, "group")} /> Muted</label>
        <span className="dim">{cues.filter((c) => c.group === name).length} cue(s)</span>
        <button className="btn sm ghost" disabled={!!busy} onClick={() => void save("group_remove", { name }, "group")} aria-label={`Remove group ${name}`}>Remove group</button></li>)}</ul>
      <div className="sm-row"><input className="text-input" value={gname} onChange={(e) => setGname(e.target.value)} placeholder="Group name, e.g. Rain bed" aria-label="New group name" maxLength={40} />
        <button className="btn sm" disabled={!!busy || !gname.trim()} onClick={() => void save("group_set", { name: gname, gain_db: 0 }, "group").then((ok) => { if (ok) setGname(""); })}>Make a group</button></div>
      {cues.length > 0 && groups.length > 0 && <div className="sm-row"><span className="dim">Put a cue in {groups[0][0]}:</span>
        <select className="text-input" aria-label="Cue to group" value="" onChange={(e) => { const id = e.target.value; if (id) void run("assign", async () => { await api.filmCues("update", dir, { id, group: groups[0][0] }); onChanged?.(); setNote(`That cue is now in ${groups[0][0]}.`); }); }}>
          <option value="">Choose a cue…</option>{cues.map((c) => <option key={c.id} value={c.id}>{c.asset_name ?? c.plan?.description ?? c.id}{c.group ? ` (${c.group})` : ""}</option>)}</select></div>}

      <h4>Markers <span className="dim">named points on the film's timeline; they go into the cue sheet and the timeline file</span></h4>
      <ul className="ss-cues">{markers.map((m, i) => <li key={`${m.t}-${i}`} className="sm-row"><b>{m.name}</b> <span className="dim">{m.t.toFixed(2)} s</span>
        <button className="btn sm ghost" disabled={!!busy} onClick={() => void save("marker_remove", { index: i }, "marker")} aria-label={`Remove marker ${m.name}`}>Remove</button></li>)}</ul>
      <div className="sm-row"><input className="text-input" type="number" step={0.04} min={0} value={mt} onChange={(e) => setMt(e.target.value)} placeholder="seconds" aria-label="Marker time in seconds" style={{ width: 90 }} />
        <input className="text-input" value={mname} onChange={(e) => setMname(e.target.value)} placeholder="Name, e.g. Door slam" aria-label="Marker name" maxLength={60} />
        <button className="btn sm" disabled={!!busy || mt === "" || !mname.trim()} onClick={() => void save("marker_add", { t: Number(mt), name: mname }, "marker").then((ok) => { if (ok) { setMt(""); setMname(""); } })}>Add a marker</button></div>

      <h4>Crossfade <span className="dim">overlap one sound into the next</span></h4>
      {sounds.length < 2 ? <p className="dim">Needs two planned sounds with a file, in the same shot or scene.</p> :
        <div className="sm-row">
          <select className="text-input" aria-label="First sound" value={xa} onChange={(e) => setXa(e.target.value)}><option value="">First sound…</option>{sounds.map((c) => <option key={c.id} value={c.id}>{c.asset_name ?? c.id}</option>)}</select>
          <select className="text-input" aria-label="Second sound" value={xb} onChange={(e) => setXb(e.target.value)}><option value="">Second sound…</option>{sounds.filter((c) => c.id !== xa).map((c) => <option key={c.id} value={c.id}>{c.asset_name ?? c.id}</option>)}</select>
          <label><input className="text-input" type="number" step={0.25} min={0.1} max={10} value={xs} onChange={(e) => setXs(e.target.value)} aria-label="Crossfade seconds" style={{ width: 70 }} /> s</label>
          <button className="btn sm" disabled={!!busy || !xa || !xb} onClick={() => void run("fade", async () => { const r = await api.audioMix<Crossfaded>("crossfade", dir, { a: xa, b: xb, seconds: Number(xs) }); setNote(`Done: the second sound now starts at ${r.b_starts} s and the two overlap for ${r.seconds} s.`); onChanged?.(); })}>Crossfade</button></div>}
      <p className="dim sm-note">Curves change loudness only; the cues, files and takes are untouched. A stem in the audio export is the mix before the whole-film curve.</p>
    </section>
  );
}
