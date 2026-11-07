import { useCallback, useEffect, useState } from "react";
import { Sheet } from "./Sheet";
import { api, errorText } from "./api";
import * as I from "./icons";
import { PanelHead } from "./Dock";

type Block = { side: "left" | "center" | "right"; facing: "left" | "right" | "camera" | "away" };
type CShot = { id: string; performers: string[]; framing: string; continuous: boolean };
type CScene = { number: number; heading: string; enabled?: boolean; blocking?: Record<string, Block>; wardrobe?: string; light?: string; shots: CShot[] };
export type CIssue = { shot: string; kind: string; detail: string; fix: string; severity: "warning" | "info"; source: "rules" | "ai" };
type CData = { scenes: CScene[]; review: { issues?: CIssue[]; ai_at?: number } };

const SIDE_LABEL = { left: "Screen left", center: "Middle", right: "Screen right" };
const FACE_LABEL = { left: "Facing left", right: "Facing right", camera: "Facing camera", away: "Facing away" };

/** Continuity Director: per-scene blocking (180° line, eyelines), wardrobe and light; cross-shot review. */
export function ContinuitySheet({ dir, onClose, onSelectShot }: { dir: string; onClose: () => void; onSelectShot: (id: string) => void }) {
  const [c, setC] = useState<CData | null>(null);
  const [issues, setIssues] = useState<CIssue[] | null>(null);
  const [scene, setScene] = useState<number | null>(null);
  const [busy, setBusy] = useState("");
  const [err, setErr] = useState("");
  const load = useCallback(() => api.continuity<CData>(dir, "get").then((d) => { setC(d ?? null); setScene((s) => s ?? d?.scenes?.[0]?.number ?? null); })
    .catch((e) => setErr(errorText(e))), [dir]);
  const rules = useCallback(() => api.continuity<{ issues: CIssue[] }>(dir, "check").then((r) => setIssues(r.issues)).catch(() => {}), [dir]);
  useEffect(() => { load().then(rules); }, [load, rules]);
  const sc = c?.scenes?.find((s) => s.number === scene);
  const save = async (patch: Partial<CScene>) => {
    if (!sc) return;
    setErr("");
    try { await api.continuity(dir, "set", { scene: sc.number, ...patch }); await load(); rules(); } catch (e) { setErr(errorText(e)); }
  };
  const aiCheck = async (all: boolean) => {
    setBusy(all ? "Looking at every scene…" : "Looking at this scene…"); setErr("");
    try {
      const r = await api.continuity<{ calls: number; errors: string[] }>(dir, "ai_check", all ? {} : { scenes: [scene] });
      if (r.errors.length) setErr(r.errors.join(" "));
      await rules();
    } catch (e) { setErr(errorText(e)); } finally { setBusy(""); }
  };
  const byShot = (id: string) => (issues ?? []).filter((i) => i.shot === id);
  const sceneIssues = sc ? sc.shots.flatMap((s) => byShot(s.id)) : [];
  const count = (n: number) => (c?.scenes?.find((s) => s.number === n)?.shots ?? []).reduce((a, s) => a + byShot(s.id).filter((i) => i.severity === "warning").length, 0);

  return (
    <Sheet label="Continuity" className="cont-sheet" onDismiss={onClose}>
        <div className="vs-head"><h2>Continuity</h2><div style={{ flex: 1 }} />
          <button className="btn ghost" onClick={() => aiCheck(true)} disabled={!!busy}
                  title="One look per scene by the AI brain (OpenAI costs a few cents per scene; a local model is free)">Check all scenes with AI</button>
          <button className="icon-btn" onClick={onClose} aria-label="Close"><I.Close size={18} /></button></div>
        <p className="sub">Who stands where, which way they face and what they wear stays the same across a scene. FilmCrafter writes it into every
          keyframe and video prompt, keeps the camera on one side of the line (the 180° rule), matches eyelines, and shows the previous
          shot's keyframe to the model when making the next one.</p>
        {busy && <div className="progress indet"><i /></div>}
        {err && <div className="error-text">{err}</div>}
        {!c ? <div className="dim">Loading…</div> : <div className="cont-body">
          <nav className="cont-scenes">{(c.scenes ?? []).map((s) => (
            <button key={s.number} className={s.number === scene ? "on" : ""} onClick={() => setScene(s.number)}>
              <span className="num">{s.number}</span><span className="h" title={s.heading}>{s.heading}</span>
              {count(s.number) > 0 && <span className="cont-badge">{count(s.number)}</span>}
            </button>))}</nav>
          {sc && <div className="cont-scene">
            <label className="cont-toggle"><input type="checkbox" checked={sc.enabled !== false} onChange={(e) => save({ enabled: e.target.checked })} />
              Keep continuity in this scene's prompts</label>
            <h3>Blocking</h3>
            {Object.keys(sc.blocking ?? {}).length === 0 ? <p className="dim">No one performs in this scene.</p> :
              <div className="cont-stage">
                <div className="cont-frame" aria-hidden>
                  {(["left", "center", "right"] as const).map((side) => <div key={side} className="cont-col">
                    {Object.entries(sc.blocking ?? {}).filter(([, b]) => b.side === side).map(([n, b]) =>
                      <span key={n} className="cont-person">{b.facing === "left" ? "◀ " : ""}{n}{b.facing === "right" ? " ▶" : ""}</span>)}
                  </div>)}
                  <div className="cont-cam">camera side</div>
                </div>
                {Object.entries(sc.blocking ?? {}).map(([n, b]) => (
                  <div key={n} className="cont-row"><b>{n}</b>
                    <select value={b.side} onChange={(e) => save({ blocking: { [n]: { ...b, side: e.target.value as Block["side"] } } })}>
                      {Object.entries(SIDE_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select>
                    <select value={b.facing} onChange={(e) => save({ blocking: { [n]: { ...b, facing: e.target.value as Block["facing"] } } })}>
                      {Object.entries(FACE_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select>
                  </div>))}
              </div>}
            <SceneText label="Wardrobe and props" value={sc.wardrobe ?? ""} onSave={(v) => save({ wardrobe: v })} />
            <SceneText label="Light and time of day" value={sc.light ?? ""} onSave={(v) => save({ light: v })} />
            <div className="wiz-row" style={{ justifyContent: "space-between", marginTop: 14 }}>
              <h3 style={{ margin: 0 }}>Shots</h3>
              <button className="btn ghost small" onClick={() => aiCheck(false)} disabled={!!busy}>Check this scene with AI</button>
            </div>
            <div className="cont-shots">{sc.shots.map((s) => (
              <div key={s.id} className="cont-shot">
                <button className="link num" onClick={() => { onSelectShot(s.id); onClose(); }}>{s.id}</button>
                <span className="dim">{s.framing.slice(0, 60)}{s.performers.length ? ` · ${s.performers.join(", ")}` : ""}</span>
                <label className="cont-cont" title="This shot continues the previous one without a cut in time">
                  <input type="checkbox" checked={s.continuous} onChange={(e) => api.continuity(dir, "shot", { shot: s.id, continuous: e.target.checked }).then(load).then(rules).catch(() => load())} />
                  Continuous</label>
                {byShot(s.id).map((i, k) => <div key={k} className={`cont-issue ${i.severity}`}>
                  <b>{i.kind}</b>{i.source === "ai" && <span className="chip">AI</span>} {i.detail} <span className="dim">{i.fix}</span></div>)}
              </div>))}</div>
            {sceneIssues.length === 0 && issues && <p className="dim">No continuity problems found in this scene.</p>}
          </div>}
        </div>}
    </Sheet>
  );
}

function SceneText({ label, value, onSave }: { label: string; value: string; onSave: (v: string) => void }) {
  const [v, setV] = useState(value);
  useEffect(() => setV(value), [value]);
  return <label className="cont-text">{label}
    <textarea className="text-input" rows={2} value={v} onChange={(e) => setV(e.target.value)} onBlur={() => v !== value && onSave(v)} /></label>;
}

/** In the shot panel: start this shot from the last frame of the previous one (free). */
export function ShotContinuity({ dir, shotId, onChanged }: { dir: string; shotId: string; onChanged: () => void }) {
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState(false);
  const chain = async () => {
    setBusy(true); setMsg("");
    try { const r = await api.continuity<{ from: string }>(dir, "chain", { shot: shotId });
      setMsg(`Keyframe set from the last frame of ${r.from}.`); onChanged(); }
    catch (e) { setMsg(errorText(e)); } finally { setBusy(false); }
  };
  return (
    <section className="panel">
      <PanelHead icon={<I.Link size={18} />} title="Continuity" tag="Free" tone="free" />
      <button className="btn ghost" onClick={chain} disabled={busy}><I.Link size={14} /> Start from the end of the previous shot</button>
      {msg && <p className="dim" style={{ marginTop: 6 }}>{msg}</p>}
    </section>
  );
}
