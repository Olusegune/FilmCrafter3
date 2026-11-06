import { useState } from "react";
import { revealItemInDir } from "@tauri-apps/plugin-opener";
import { api, errorText, type ProAudioPlan, type ProAudioResult, type ProAudioSpec } from "./api";

export const STEM_LABEL: Record<string, string> = { dialogue: "Dialogue", foley: "Foley", sfx: "Effects", ambience: "Ambience", music: "Music" };
const STEMS = Object.keys(STEM_LABEL);
const TARGETS: [string, string][] = [["", "Leave as it is"], ["-23", "Broadcast (-23 LUFS)"], ["-24", "US broadcast (-24 LUFS)"], ["-16", "Online video (-16 LUFS)"], ["-14", "Streaming (-14 LUFS)"]];

export const DEFAULT_SPEC: ProAudioSpec = { rate: 48000, bits: 24, bwf: true, stems: [...STEMS], mixes: ["final", "me"], target_lufs: null, peak_db: -1, start_tc: "00:00:00:00", media: true };

/** A size in plain words. */
export const sizeWords = (bytes: number): string => (bytes >= 1e9 ? `${(bytes / 1e9).toFixed(1)} GB` : `${Math.max(1, Math.round(bytes / 1e6))} MB`);

/** What a plan says it would make, in one sentence. */
export const planWords = (p: ProAudioPlan): string => {
  const empty = Object.entries(p.lanes).filter(([, v]) => v !== "yes").map(([k, v]) => `${STEM_LABEL[k]} (${v})`);
  return `${p.files} file${p.files === 1 ? "" : "s"}, about ${sizeWords(p.estimated_bytes)}, each ${p.seconds.toFixed(0)} s long.${empty.length ? ` No stem for: ${empty.join(", ")}.` : ""}`;
};

/**
 * Audio for a sound editor: every lane as its own file, a FINAL mix and an M&E mix (no dialogue), as Broadcast WAV with the start timecode, plus a cue sheet and an editable timeline. The stems are the film's
 * mix before the master stage; each mix is the sum of its stems times one steady gain. Free and local. Positions follow the film's shot list; nothing is claimed about any editor until it has been tried there.
 */
export function ProAudio({ dir }: { dir: string }) {
  const [spec, setSpec] = useState<ProAudioSpec>(DEFAULT_SPEC);
  const [plan, setPlan] = useState<ProAudioPlan | null>(null);
  const [res, setRes] = useState<ProAudioResult | null>(null);
  const [busy, setBusy] = useState("");
  const [err, setErr] = useState("");
  const [open, setOpen] = useState(false);

  const run = async (label: string, f: () => Promise<void>) => { setErr(""); setBusy(label); try { await f(); } catch (e) { setErr(errorText(e)); } finally { setBusy(""); } };
  const set = (patch: Partial<ProAudioSpec>) => { setSpec({ ...spec, ...patch }); setPlan(null); };
  const toggle = (k: "stems" | "mixes", v: string) => set({ [k]: spec[k].includes(v) ? spec[k].filter((x) => x !== v) : [...spec[k], v] } as Partial<ProAudioSpec>);

  if (!open) return <section aria-label="Audio for a sound editor"><h3>Audio for a sound editor <span className="dim">stems, mixes, cue sheet</span></h3>
    <p className="dim">Every lane as its own file, a FINAL mix and an M&amp;E mix, as Broadcast WAV with timecode, a cue sheet and an editable timeline. Free; nothing is sent anywhere.</p>
    <button className="btn sm" onClick={() => setOpen(true)}>Open audio export…</button></section>;

  return (
    <section aria-label="Audio for a sound editor" className="pa">
      <h3>Audio for a sound editor</h3>
      <div className="cw-fields">
        <label className="field"><span>Sample rate</span><select value={spec.rate} onChange={(e) => set({ rate: Number(e.target.value) })}><option value={44100}>44.1 kHz</option><option value={48000}>48 kHz (film)</option><option value={96000}>96 kHz</option></select></label>
        <label className="field"><span>Bit depth</span><select value={spec.bits} onChange={(e) => set({ bits: Number(e.target.value) })}><option value={16}>16-bit</option><option value={24}>24-bit</option><option value={32}>32-bit float</option></select></label>
        <label className="field"><span>Start timecode</span><select value={spec.start_tc} onChange={(e) => set({ start_tc: e.target.value })}><option value="00:00:00:00">00:00:00:00</option><option value="01:00:00:00">01:00:00:00 (film reel)</option></select></label>
        <label className="field"><span>Loudness of the FINAL and M&amp;E mixes</span><select value={spec.target_lufs === null ? "" : String(spec.target_lufs)} onChange={(e) => set({ target_lufs: e.target.value === "" ? null : Number(e.target.value) })}>{TARGETS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select></label>
        <label className="field"><span>Never louder than</span><select value={spec.peak_db} onChange={(e) => set({ peak_db: Number(e.target.value) })}><option value={-1}>-1 dBFS</option><option value={-2}>-2 dBFS</option><option value={-3}>-3 dBFS</option><option value={-6}>-6 dBFS</option></select></label>
      </div>
      <div className="sm-row" role="group" aria-label="Stems"><span className="dim">Stems:</span>{STEMS.map((k) => <label key={k} className="ov-check"><input type="checkbox" checked={spec.stems.includes(k)} onChange={() => toggle("stems", k)} /> {STEM_LABEL[k]}</label>)}</div>
      <div className="sm-row" role="group" aria-label="Mixes"><span className="dim">Mixes:</span>
        <label className="ov-check"><input type="checkbox" checked={spec.mixes.includes("final")} onChange={() => toggle("mixes", "final")} /> FINAL</label>
        <label className="ov-check"><input type="checkbox" checked={spec.mixes.includes("me")} onChange={() => toggle("mixes", "me")} /> M&amp;E (no dialogue)</label></div>
      <div className="sm-row">
        <label className="ov-check"><input type="checkbox" checked={spec.bwf} onChange={(e) => set({ bwf: e.target.checked })} /> Broadcast WAV (timecode and loudness in the file)</label>
        <label className="ov-check"><input type="checkbox" checked={spec.media} onChange={(e) => set({ media: e.target.checked })} /> Timeline with copies of the original sounds</label></div>

      <div className="sm-row">
        <button className="btn ghost" disabled={!!busy || (!spec.stems.length && !spec.mixes.length)} onClick={() => void run("plan", async () => setPlan(await api.proAudio<ProAudioPlan>("plan", dir, spec)))}>{busy === "plan" ? "Looking…" : "What would be made"}</button>
        <button className="btn primary" disabled={!!busy || (!spec.stems.length && !spec.mixes.length)} onClick={() => void run("export", async () => { setRes(await api.proAudio<ProAudioResult>("export", dir, spec)); })}>{busy === "export" ? "Writing the files…" : "Export the audio"}</button>
      </div>
      {plan && <div aria-label="Plan"><p>{planWords(plan)}</p><p className="dim">{plan.positions}</p></div>}
      {res && <div aria-label="Export result">
        <p role="status">{res.ok ? `Done: ${res.files} files in ${res.relative}. Every file was read back and checked.` : "The files were written, but reading them back found problems:"}</p>
        {res.problems.length > 0 && <ul className="error-text">{res.problems.map((p) => <li key={p}>{p}</li>)}</ul>}
        {res.mixes.map((m) => <p key={m.file} className="dim">{m.file.split("/").pop()}: {m.lufs !== null ? `${m.lufs} LUFS, ` : ""}{m.true_peak_db !== null ? `true peak ${m.true_peak_db} dBFS, ` : ""}master gain {m.master_gain_db > 0 ? "+" : ""}{m.master_gain_db} dB.{m.note ? ` ${m.note}` : ""}</p>)}
        {Object.keys(res.lanes_without_sound).length > 0 && <p className="dim">No stem for: {Object.entries(res.lanes_without_sound).map(([k, v]) => `${STEM_LABEL[k] ?? k} (${v})`).join("; ")}</p>}
        <button className="btn sm" onClick={() => void Promise.resolve(revealItemInDir(res.folder)).catch(() => {})}>Show the folder</button>
        <details><summary>What was not checked</summary><ul>{res.not_checked.map((n) => <li key={n}>{n}</li>)}</ul></details>
      </div>}
      {err && <p className="error-text" role="alert">{err}</p>}
    </section>
  );
}
