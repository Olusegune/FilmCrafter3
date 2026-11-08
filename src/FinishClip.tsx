import { useEffect, useState } from "react";
import { api, errorText, type PlPlan, type PlPresets, type PlRun } from "./api";

const MARK: Record<string, string> = { done: "✓", failed: "✗", running: "…", pending: "·" };

/**
 * Finish a clip made from a set: the stretch from the set render to the delivered file, as one run you can resume. The stages are the ones FilmCrafter already has (the Fidelity analyser and enhancer, the flicker
 * calmer, the finishing looks and delivery profiles) plus a check of the delivered file. Free and local; the clip itself is never changed.
 */
export function FinishClip({ dir, clip, set }: { dir: string; clip: string; set?: string }) {
  const [presets, setPresets] = useState<PlPresets | null>(null);
  const [plan, setPlan] = useState<PlPlan | null>(null);
  const [run, setRun] = useState<PlRun | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [o, setO] = useState({ look: "none", profile: "web", enhance: false, strength: 0.5, calm: "auto" });
  useEffect(() => { api.setPipeline<PlPresets>("presets", dir).then(setPresets).catch(() => {}); }, [dir]);
  useEffect(() => { setRun(null); setPlan(null); api.setPipeline<PlPlan>("plan", dir, { ref: clip, set, options: o }).then((p) => { if (p?.info) setPlan(p); }).catch((e) => setErr(errorText(e))); }, [dir, clip, set, o.enhance, o.look, o.profile, o.calm]); // eslint-disable-line react-hooks/exhaustive-deps
  const go = async (resume?: string) => {
    setErr(""); setBusy(true);
    try {
      const id = resume ?? (await api.setPipeline<PlRun>("start", dir, { ref: clip, set, options: o })).id;
      setRun(await api.setPipeline<PlRun>("get", dir, { run: id, set }));
      setRun(await api.setPipeline<PlRun>("run", dir, { run: id, set }));
    } catch (e) {
      setErr(errorText(e));
      try { const r = run ?? undefined; if (r) setRun(await api.setPipeline<PlRun>("get", dir, { run: r.id, set })); } catch { /* the record is shown when it can be read */ }
    } finally { setBusy(false); }
  };
  const failed = run && Object.values(run.stages).some((s) => s.status === "failed");
  return (
    <section aria-label="Finish this clip" className="cw-set">
      <h4>Finish this clip <span className="dim">free and local; the clip is never changed</span></h4>
      <p className="dim">Measures the clip, checks the set's continuity, calms flicker if it is noticeable, optionally enhances every frame, then makes a delivery copy and checks it. If it is interrupted, press Resume: what is done is kept.</p>
      <div className="sm-row">
        <label>Look <select className="text-input" aria-label="Finishing look" value={o.look} onChange={(e) => setO({ ...o, look: e.target.value })}>{(presets?.looks ?? [{ id: "none", label: "No look", note: "" }]).map((l) => <option key={l.id} value={l.id} title={l.note}>{l.label}</option>)}</select></label>
        <label>Deliver as <select className="text-input" aria-label="Delivery profile" value={o.profile} onChange={(e) => setO({ ...o, profile: e.target.value })}>{(presets?.profiles ?? [{ id: "web", label: "Web (H.264)", note: "", ext: "mp4" }]).map((p) => <option key={p.id} value={p.id} title={p.note}>{p.label}</option>)}</select></label>
        <label>Flicker <select className="text-input" aria-label="Calm flicker" value={o.calm} onChange={(e) => setO({ ...o, calm: e.target.value })}><option value="auto">Only if noticeable</option><option value="off">Leave it</option><option value="gentle">Gently</option><option value="strong">Strongly</option></select></label>
        <label className="ov-check"><input type="checkbox" checked={o.enhance} onChange={(e) => setO({ ...o, enhance: e.target.checked })} /> Enhance every frame (Fidelity)</label>
        {o.enhance && <label>Strength <input type="range" min={0} max={1} step={0.05} aria-label="Enhance strength" value={o.strength} onChange={(e) => setO({ ...o, strength: Number(e.target.value) })} /> {Math.round(o.strength * 100)}%</label>}
      </div>
      {plan && <p className="dim" role="status" aria-label="Plan">{plan.info.width}×{plan.info.height} · {plan.info.frames} frames · {plan.info.seconds} s{plan.info.audio ? " · with sound" : ""}. Roughly {Math.max(1, Math.round(plan.seconds_estimate))} s on a typical computer (the real times are kept in the run).</p>}
      <div className="sm-row"><button className="btn sm" disabled={busy || !plan} onClick={() => void go()}>{busy ? "Working…" : "Finish this clip"}</button>
        {failed && run && <button className="btn sm" disabled={busy} onClick={() => void go(run.id)}>Resume</button>}</div>
      {err && <p className="ss-warn" role="alert">{err}</p>}
      {run && <ul className="ss-cues" aria-label="Stages">{Object.entries(run.stages).map(([id, s]) => <li key={id} className="sm-row" aria-label={`Stage ${id}`}>
        <b aria-hidden>{MARK[s.status]}</b><span>{run.labels[id] ?? id}</span><span className="dim">{s.status === "done" ? `${s.seconds ?? 0} s` : s.status}</span>
        <span className={s.status === "failed" ? "ss-warn" : "dim"}>{s.status === "failed" ? s.error : s.result?.skipped ?? s.result?.note ?? s.result?.advice ?? ""}</span></li>)}</ul>}
      {run?.done && run.delivered && <div aria-label="Delivered">
        <p role="status">{run.valid ? "Delivered and checked." : "Delivered, but a check failed. Read it below before using the file."} <span className="dim">{run.total_seconds} s in all.</span></p>
        <video controls src={api.mediaUrl(`${dir}/${run.delivered.replace(/^project:/, "")}`)} style={{ maxWidth: 480, borderRadius: 6 }} />
        <ul aria-label="Checks">{(run.stages.validate.result?.checks ?? []).map((c) => <li key={c.check} className={c.ok ? "dim" : "ss-warn"}>{c.ok ? "✓" : "✗"} {c.check}: {c.detail}</li>)}</ul>
        <p className="dim">The file is in the film's finish folder: {run.delivered.replace(/^project:/, "")}</p></div>}
    </section>
  );
}
