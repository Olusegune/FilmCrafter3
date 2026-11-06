import { useCallback, useEffect, useState } from "react";
import { open } from "@tauri-apps/plugin-dialog";
import { api, errorText, type AlignSuggestion, type FitMade, type LineTiming } from "./api";
import { ask } from "./ask";
import { VoiceRecorder } from "./VoiceRecorder";
import { FILTERS } from "./voiceLogic";

/** A move in frames, in words. */
export const moveWords = (frames: number): string => (frames === 0 ? "in place" : `${Math.abs(frames)} frame${Math.abs(frames) === 1 ? "" : "s"} ${frames > 0 ? "later" : "earlier"}`);

/** Where the recording sits in its shot, in one sentence. */
export const placeWords = (t: LineTiming): string =>
  `Recording ${t.recording.seconds.toFixed(2)} s, ${moveWords(t.offset_frames)}: starts ${t.starts}, ends ${t.ends} (the shot ends ${t.shot_ends}, ${t.fps_label} frames a second).`;

const STEPS = [-10, -1, 1, 10];

/**
 * Timing and ADR for one line: move it by whole frames, fit it to its shot with a pitch-preserving tempo change (a new take, never a replacement), line it up with the picture's own sound, mark it for
 * ADR and add retakes. A recording is never changed; the other versions are takes you choose between. Free and local.
 */
export function TimingAdr({ dir, shotId, who, onChanged }: { dir: string; shotId: string; who: string; onChanged: () => void }) {
  const [t, setT] = useState<LineTiming | null>(null);
  const [none, setNone] = useState(false);
  const [busy, setBusy] = useState("");
  const [err, setErr] = useState("");
  const [say, setSay] = useState("");
  const [open_, setOpen] = useState(false);
  const [sug, setSug] = useState<AlignSuggestion | null>(null);
  const [reason, setReason] = useState("");
  const [recording, setRecording] = useState(false);

  const load = useCallback(() => api.adrSync("get", dir, { shot: shotId, speaker: who }).then((r) => { setT(r); setReason(r.adr.reason); setNone(false); })
    .catch((e) => { const m = errorText(e); if (/no recording/i.test(m)) { setT(null); setNone(true); } else setErr(m); }), [dir, shotId, who]);
  useEffect(() => { if (open_) void load(); }, [open_, load]);
  const go = async (label: string, f: () => Promise<void>) => { setErr(""); setSay(""); setBusy(label); try { await f(); } catch (e) { setErr(errorText(e)); } finally { setBusy(""); } };

  if (!open_) return <section className="ls-sec" aria-label="Timing and ADR"><h3>Timing and ADR</h3>
    <p className="dim ls-gap">Move a line by whole frames, fit it to its shot, line it up with the picture's sound, or add an ADR retake. Your recording is never changed; other versions are takes you choose between. Free.</p>
    <button className="btn sm" onClick={() => setOpen(true)}>Open timing and ADR…</button></section>;
  if (none) return <section className="ls-sec" aria-label="Timing and ADR"><h3>Timing and ADR</h3><p className="dim">{who} has no recording in {shotId} yet. Record or add one first, then come back.</p></section>;
  if (!t) return <section className="ls-sec" aria-label="Timing and ADR"><h3>Timing and ADR</h3>{err ? <p className="error-text" role="alert">{err}</p> : <p className="dim">Looking…</p>}</section>;

  const nudge = (frames: number) => go("nudge", async () => { setT(await api.adrSync("nudge", dir, { shot: shotId, speaker: who, frames })); setSug(null); onChanged(); });
  const reset = () => go("nudge", async () => { setT(await api.adrSync("nudge", dir, { shot: shotId, speaker: who, to_frame: 0 })); setSug(null); onChanged(); });
  const align = () => go("align", async () => setSug(await api.adrSync<AlignSuggestion>("align", dir, { shot: shotId, speaker: who })));
  const apply = () => go("nudge", async () => { if (!sug) return; setT(await api.adrSync("nudge", dir, { shot: shotId, speaker: who, to_frame: sug.move_to_frame })); setSug(null); onChanged(); });
  const fit = (extreme: boolean) => go("fit", async () => {
    if (extreme && !(await ask(`Fit ${who}'s line by ${t.fit.tempo ? Math.round(100 * (t.fit.tempo - 1)) : "?"}%?\n\nThat is more than sounds right. Listen carefully to the take before you choose it. Your recording is kept.`, { ok: "Make it anyway" }))) return;
    const r = await api.adrSync<FitMade>("fit_make", dir, { shot: shotId, speaker: who, ...(extreme ? { allow_extreme: true } : {}) });
    setSay(`A fitted take was added to the takes${r.cached ? " (it was made before)" : ""}: ${r.natural ? "" : "a big change, so "}listen to it next to the original, then choose it.`);
    onChanged();
  });
  const mark = (needs: boolean) => go("mark", async () => { setT(await api.adrSync("adr_mark", dir, { shot: shotId, speaker: who, needs, reason: needs ? reason : "" })); });
  const addTake = (file: string) => go("take", async () => {
    await api.adrSync("adr_take", dir, { shot: shotId, speaker: who, recording: file });
    setSay("The ADR retake was added to the takes. Your original is kept. Listen to them side by side, then choose one.");
    onChanged();
  });
  const chooseFile = async () => { const r = await open({ multiple: false, filters: FILTERS }); const f = Array.isArray(r) ? r[0] : r; if (f) await addTake(f); };

  return (
    <section className="ls-sec" aria-label="Timing and ADR">
      <h3>Timing and ADR</h3>
      <p aria-label="Where the line sits">{placeWords(t)}</p>
      {t.runs_past_shot && <p className="error-text" role="alert">The line runs past the end of the shot. Move it earlier, fit it, or lengthen the shot.</p>}
      {t.starts_before_shot && <p className="dim">It starts before its picture (a J cut).</p>}
      <div className="ls-btns" role="group" aria-label="Move the line">
        {STEPS.map((n) => <button key={n} className="btn sm" disabled={!!busy} onClick={() => void nudge(n)} aria-label={`Move ${moveWords(n)}`}>{n > 0 ? `+${n}` : n}</button>)}
        <button className="link" disabled={!!busy || t.offset_frames === 0} onClick={() => void reset()}>Put it back</button>
        <span className="dim">in whole frames</span>
      </div>

      <div className="ls-btns">
        <button className="btn sm ghost" disabled={!!busy} onClick={() => void align()}>{busy === "align" ? "Measuring…" : "Line up with the picture's sound"}</button>
      </div>
      {sug && <div aria-label="Line-up suggestion"><p>{sug.words}</p>
        <p className="dim">Compares loudness shapes, not words. Match {Math.round(sug.strength * 100)}%{sug.reliable ? "" : ", not confident"}.</p>
        {sug.move_by_frames !== 0 && <button className="btn sm" disabled={!!busy} onClick={() => void apply()}>Move it {moveWords(sug.move_by_frames)}</button>}</div>}

      <h4>Fit to the shot</h4>
      <p aria-label="Fit">{t.fit.words}</p>
      <div className="ls-btns">
        {(t.fit.class === "natural" || t.fit.class === "audible") && <button className="btn sm" disabled={!!busy} onClick={() => void fit(false)}>{busy === "fit" ? "Fitting…" : "Make a fitted take"}</button>}
        {t.fit.class === "too_much" && <button className="btn sm ghost" disabled={!!busy} onClick={() => void fit(true)}>Make one anyway…</button>}
        <span className="dim">Pitch is kept. The original stays; this is a new take.</span>
      </div>

      <h4>ADR</h4>
      <div className="ls-btns">
        <label className="ov-check"><input type="checkbox" checked={t.adr.needs} disabled={!!busy} onChange={(e) => void mark(e.target.checked)} /> This line needs ADR</label>
        <input className="text-input" value={reason} maxLength={300} onChange={(e) => setReason(e.target.value)} onBlur={() => { if (t.adr.needs && reason !== t.adr.reason) void mark(true); }} placeholder="Why (a dog barks, a plane passes)…" aria-label="Why it needs ADR" />
      </div>
      <div className="ls-btns">
        <button className="btn sm" disabled={!!busy} onClick={() => setRecording(true)}>Record an ADR take</button>
        <button className="btn sm" disabled={!!busy} onClick={() => void chooseFile()}>Add an ADR recording…</button>
        <span className="dim">Added as a new take beside the others; nothing is replaced.</span>
      </div>
      {say && <p role="status">{say}</p>}
      {err && <p className="error-text" role="alert">{err}</p>}
      {recording && <VoiceRecorder dir={dir} shotId={shotId} speaker={who} onClose={() => setRecording(false)} onTake={(p) => { void addTake(p); }} />}
    </section>
  );
}
