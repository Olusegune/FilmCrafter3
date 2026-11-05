import { useEffect, useState } from "react";
import { revealItemInDir } from "@tauri-apps/plugin-opener";
import { api, errorText, type FinishPresets, type FinishVideo, type FlickerReport, type RestoreItem, type FinishItem } from "./api";

/** Check a finished video for flicker, make a calmer copy, and make a delivery copy with a finishing look and an encoding profile. Free and local; originals are never changed. */
export function FinishPanel({ dir }: { dir: string }) {
  const [videos, setVideos] = useState<FinishVideo[]>([]);
  const [presets, setPresets] = useState<FinishPresets | null>(null);
  const [ref, setRef] = useState("");
  const [look, setLook] = useState("none");
  const [profile, setProfile] = useState("web");
  const [strength, setStrength] = useState("balanced");
  const [flick, setFlick] = useState<{ ref: string; report: FlickerReport; limits: string } | null>(null);
  const [rest, setRest] = useState<RestoreItem | null>(null);
  const [done, setDone] = useState<FinishItem | null>(null);
  const [busy, setBusy] = useState("");
  const [err, setErr] = useState("");
  useEffect(() => {
    api.videoFinish<{ videos: FinishVideo[] }>(dir, "videos").then((r) => { setVideos(r.videos); setRef((c) => c || r.videos[0]?.ref || ""); }).catch(() => {});
    api.videoFinish<FinishPresets>(dir, "presets").then(setPresets).catch(() => {});
  }, [dir]);
  const go = async (what: string, fn: () => Promise<void>) => { setBusy(what); setErr(""); try { await fn(); } catch (e) { setErr(errorText(e)); } finally { setBusy(""); } };
  const size = (b: number) => b > 1e9 ? `${(b / 1e9).toFixed(1)} GB` : `${Math.max(1, Math.round(b / 1e6))} MB`;
  if (!videos.length) return <details className="fin-panel"><summary>Finish and deliver</summary><p className="dim">Export a film first; then you can check it for flicker and make delivery copies here.</p></details>;
  return (
    <details className="fin-panel">
      <summary>Finish and deliver (free, on this computer)</summary>
      <label className="dim" htmlFor="fin-video">Video</label>
      <select id="fin-video" value={ref} onChange={(e) => { setRef(e.target.value); setFlick(null); setRest(null); setDone(null); }} disabled={!!busy}>
        {videos.map((v) => <option key={v.ref} value={v.ref}>{v.name} · {size(v.bytes)}</option>)}
      </select>
      <div className="wiz-row" style={{ marginTop: 8 }}>
        <button className="btn small" disabled={!!busy || !ref} onClick={() => go("Measuring…", async () => setFlick(await api.videoFinish(dir, "flicker", { ref })))}>{busy === "Measuring…" ? busy : "Check for flicker"}</button>
        <select aria-label="Restore strength" value={strength} onChange={(e) => setStrength(e.target.value)} disabled={!!busy}>{(presets?.strengths ?? ["gentle", "balanced", "strong"]).map((s) => <option key={s}>{s}</option>)}</select>
        <button className="btn small" disabled={!!busy || !ref} onClick={() => go("Calming…", async () => setRest(await api.videoFinish(dir, "restore", { ref, strength })))}>{busy === "Calming…" ? "Calming… (a few minutes)" : "Make a calmer copy"}</button>
      </div>
      {flick && <p role="status">Flicker: <b>{flick.report.level}</b>{flick.report.confidence !== "high" ? ` (${flick.report.confidence} confidence)` : ""}. {flick.report.note} <span className="dim">{flick.limits}</span></p>}
      {rest && <div role="status"><p>Flicker {rest.before.level} ({rest.before.score ?? "?"}) → {rest.after.level} ({rest.after.score ?? "?"}). {rest.note}</p>
        <button className="btn small ghost" onClick={() => revealItemInDir(rest.output_path).catch(() => {})}>Show the calmer copy</button></div>}
      <hr />
      <div className="wiz-row">
        <label>Look <select value={look} onChange={(e) => setLook(e.target.value)} disabled={!!busy}>{(presets?.looks ?? []).map((l) => <option key={l.id} value={l.id}>{l.label}</option>)}</select></label>
        <label>Profile <select value={profile} onChange={(e) => setProfile(e.target.value)} disabled={!!busy}>{(presets?.profiles ?? []).map((p) => <option key={p.id} value={p.id}>{p.label}</option>)}</select></label>
        <button className="btn small primary" disabled={!!busy || !ref} onClick={() => go("Encoding…", async () => setDone(await api.videoFinish(dir, "finish", { ref, look, profile })))}>{busy === "Encoding…" ? "Encoding… (a few minutes)" : "Make the delivery copy"}</button>
      </div>
      <p className="dim" style={{ fontSize: 12 }}>{presets?.looks.find((l) => l.id === look)?.note} {presets?.profiles.find((p) => p.id === profile)?.note}</p>
      {done && <div role="status"><p>Made {size(done.bytes)} from {size(videos.find((v) => v.ref === done.source)?.bytes ?? done.bytes)}.</p>
        <button className="btn small ghost" onClick={() => revealItemInDir(done.output_path).catch(() => {})}>Show the file</button></div>}
      {err && <div className="error-text" role="alert">{err}</div>}
    </details>
  );
}
