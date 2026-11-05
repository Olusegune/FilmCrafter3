import { useEffect, useState } from "react";
import { Sheet } from "./Sheet";
import { api, errorText, type FidelityCheck, type FidelityItem, type FidelityReport } from "./api";
import * as I from "./icons";

export const openFidelity = (shot: string) => window.dispatchEvent(new CustomEvent("pf-open-fidelity", { detail: shot }));

const STRENGTHS = [{ v: 0.3, label: "Gentle" }, { v: 0.5, label: "Balanced" }, { v: 0.8, label: "Strong" }];
const WARN = new Set(["Soft", "High", "Moderate", "Dark", "Bright", "Low", "Smooth"]);

/** The measurements of one picture, in words, each with how sure the measurement is. Pure display. */
export function FidelityReportView({ report }: { report: FidelityReport }) {
  return (
    <div>
      <p className="dim" style={{ margin: "4px 0" }}>{report.width} × {report.height} · {report.aspect}{report.format ? ` · ${report.format}` : ""}{report.reduced ? ` · measured on a reduced copy (${report.analysed_at})` : ""}</p>
      <div className="fid-rows" role="list">
        {report.rows.map((r) => (
          <div className="fid-row" role="listitem" key={r.id}>
            <b>{r.label}</b>
            <span className={`lvl ${r.id !== "texture" && r.id !== "contrast" && WARN.has(r.level) && r.level !== "Low" ? "warn" : ""}`}>{r.level}{r.confidence !== "high" ? <small> ({r.confidence} confidence)</small> : null}</span>
            <small>{r.note}</small>
          </div>))}
      </div>
      <div className={`fid-verdict ${report.verdict}`} role="status"><b>{report.action}</b></div>
      <p className="dim" style={{ fontSize: 12 }}>Not assessed: {report.not_assessed.join("; ")}.</p>
    </div>
  );
}

/** Drag to compare the original (left) and the cleaned picture (right), or look at either one at 100%. Both are the real files. */
export function BeforeAfter({ before, after, w, h }: { before: string; after: string; w: number; h: number }) {
  const [pos, setPos] = useState(50);
  const [full, setFull] = useState<"off" | "before" | "after">("off");
  if (full !== "off") return (
    <div>
      <div className="fid-compare full" aria-label={`${full === "before" ? "Original" : "Cleaned"} at 100%`}><img src={full === "before" ? before : after} width={w} height={h} alt={full === "before" ? "Original at 100%" : "Cleaned at 100%"} /></div>
      <div className="wiz-row" style={{ marginTop: 8 }}>
        <button className="btn small ghost" onClick={() => setFull(full === "before" ? "after" : "before")}>Show {full === "before" ? "cleaned" : "original"}</button>
        <button className="btn small ghost" onClick={() => setFull("off")}>Back to the slider</button>
        <span className="dim">Showing the {full === "before" ? "original" : "cleaned picture"} at 100%. Scroll to look around.</span>
      </div>
    </div>);
  return (
    <div>
      <div className="fid-compare">
        <img src={before} alt="Original" />
        <div className="after" style={{ clipPath: `inset(0 0 0 ${pos}%)` }}><img src={after} alt="Cleaned" /></div>
        <span className="tag" style={{ left: 8 }}>Original</span><span className="tag" style={{ right: 8 }}>Cleaned</span>
      </div>
      <input className="fid-range" type="range" min={0} max={100} value={pos} onChange={(e) => setPos(Number(e.target.value))} aria-label="Compare original and cleaned: drag to move the divider" />
      <div className="wiz-row"><button className="btn small ghost" onClick={() => setFull("before")}>Original at 100%</button><button className="btn small ghost" onClick={() => setFull("after")}>Cleaned at 100%</button></div>
    </div>);
}

/** Check a shot's keyframe, tidy it for free (Clean Enhance), compare, and choose. The original file is never changed. */
export function FidelitySheet({ dir, shot, onClose, onChanged }: { dir: string; shot: string; onClose: () => void; onChanged: () => void }) {
  const [check, setCheck] = useState<FidelityCheck | null>(null);
  const [item, setItem] = useState<FidelityItem | null>(null);
  const [strength, setStrength] = useState(0.5);
  const [busy, setBusy] = useState("");
  const [err, setErr] = useState("");
  const [applied, setApplied] = useState(false);
  useEffect(() => {
    setBusy("Measuring…");
    api.fidelity<FidelityCheck>(dir, "check", { shot }).then(setCheck).catch((e) => setErr(errorText(e))).finally(() => setBusy(""));
  }, [dir, shot]);
  const clean = async () => {
    setBusy("Cleaning…"); setErr(""); setItem(null);
    try { setItem(await api.fidelity<FidelityItem>(dir, "enhance", { shot, strength })); } catch (e) { setErr(errorText(e)); } finally { setBusy(""); }
  };
  const use = async () => {
    if (!item) return;
    setBusy("Saving…"); setErr("");
    try { await api.fidelity(dir, "apply", { id: item.id }); setApplied(true); onChanged(); } catch (e) { setErr(errorText(e)); } finally { setBusy(""); }
  };
  const undo = async () => {
    setBusy("Undoing…"); setErr("");
    try { await api.fidelity(dir, "revert", { shot }); setApplied(false); onChanged(); } catch (e) { setErr(errorText(e)); } finally { setBusy(""); }
  };
  const diff = (id: string) => {
    const b = item?.before_report?.rows.find((r) => r.id === id), a = item?.after_report?.rows.find((r) => r.id === id);
    return b && a ? `${b.level} → ${a.level}` : "";
  };
  return (
    <Sheet label="Picture quality" className="fid-sheet" onDismiss={() => !busy && onClose()}>
      <div className="vs-head"><h2><I.Sparkle size={18} /> Picture quality · {shot}</h2><div style={{ flex: 1 }} />
        <button className="icon-btn" onClick={onClose} aria-label="Close" disabled={!!busy}><I.Close size={18} /></button></div>
      <p className="sub">Measured on this computer, free. Clean Enhance tidies noise and compression and sharpens what is already there. It cannot add detail that is not in the picture, and it never changes your original.</p>
      {!check && !err && <p className="dim" role="status">{busy || "Measuring…"}</p>}
      {check && <FidelityReportView report={check.report} />}
      {check && (
        <div className="wiz-row" style={{ marginTop: 8 }}>
          <div role="radiogroup" aria-label="How strong" style={{ display: "flex", gap: 6 }}>
            {STRENGTHS.map((s) => <button key={s.v} role="radio" aria-checked={s.v === strength} disabled={!!busy} className={`btn small ${s.v === strength ? "primary" : "ghost"}`} onClick={() => setStrength(s.v)}>{s.label}</button>)}
          </div>
          <button className="btn primary" onClick={clean} disabled={!!busy}>{busy === "Cleaning…" ? busy : item ? "Clean again" : "Clean up (free)"}</button>
        </div>)}
      {item && item.source_path && item.output_path && (
        <div style={{ marginTop: 12 }}>
          <BeforeAfter before={api.mediaUrl(item.source_path)} after={api.mediaUrl(item.output_path)} w={item.size[0]} h={item.size[1]} />
          <p className="dim" style={{ marginTop: 6 }}>Measured again: sharpness {diff("sharpness")} · noise {diff("noise")} · compression blocks {diff("blocking")}. Look at the picture too: numbers cannot see halos or changed faces.</p>
          <div className="wiz-row" style={{ marginTop: 8 }}>
            {!applied ? <button className="btn primary" onClick={use} disabled={!!busy}>Use the cleaned picture</button> : <button className="btn ghost" onClick={undo} disabled={!!busy}>Go back to the original</button>}
            <button className="btn ghost" onClick={onClose} disabled={!!busy}>{applied ? "Done" : "Keep the original"}</button>
          </div>
          {applied && <div className="note ok" role="status"><I.Check size={14} /> The cleaned picture is now this shot's keyframe. The original is kept.</div>}
        </div>)}
      {err && <div className="error-text" role="alert" style={{ marginTop: 8 }}>{err}</div>}
    </Sheet>
  );
}
