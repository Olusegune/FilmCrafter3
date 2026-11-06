import { useState } from "react";
import { open } from "@tauri-apps/plugin-dialog";
import { api, errorText, type AudioQaReport, type QaFinding } from "./api";

const ORDER: QaFinding["severity"][] = ["fix", "look", "note"];
const LABEL: Record<QaFinding["severity"], string> = { fix: "To fix", look: "Worth a listen", note: "For information" };

/** Every finding of a report, most serious first, each with where it is. */
export const allFindings = (r: AudioQaReport): QaFinding[] => [...r.items.flatMap((i) => i.findings), ...r.consistency].sort((a, b) => ORDER.indexOf(a.severity) - ORDER.indexOf(b.severity));

/** What was checked, in one sentence. */
export const checkedWords = (r: AudioQaReport): string => `${r.summary.files} sound file${r.summary.files === 1 ? "" : "s"} checked.`;

/**
 * The audio quality inspector: measurements of the film's recordings, the sounds in its cues and, if you choose one, a finished film file, reported as things to listen to. It reads files and
 * writes nothing. It says what it did not measure and gives no quality score: the numbers show where to listen, not what is right.
 */
export function AudioCheck({ dir }: { dir: string }) {
  const [r, setR] = useState<AudioQaReport | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [file, setFile] = useState<string | null>(null);

  const run = async (f: string | null) => {
    setErr(""); setBusy(true);
    try { setR(await api.audioQa<AudioQaReport>("film", dir, f ? { file: f } : {})); } catch (e) { setErr(errorText(e)); } finally { setBusy(false); }
  };
  const choose = async () => {
    const pick = await open({ multiple: false, filters: [{ name: "Finished film or sound", extensions: ["mp4", "mov", "mkv", "webm", "wav", "mp3", "m4a", "flac"] }] });
    const f = Array.isArray(pick) ? pick[0] : pick;
    if (f) { setFile(f); void run(f); }
  };
  const list = r ? allFindings(r) : [];

  return (
    <section aria-label="Check the sound">
      <h3>Check the sound <span className="dim">measurements, not a score</span></h3>
      <p className="dim">Looks at your recordings, the sounds in your cues and, if you choose one, a finished film. It reads files and changes nothing.</p>
      <div className="sm-row">
        <button className="btn" disabled={busy} onClick={() => void run(file)}>{busy ? "Measuring…" : "Check the sound"}</button>
        <button className="btn ghost" disabled={busy} onClick={() => void choose()}>Also check a finished film…</button>
        {file && <span className="dim">Including {file.split(/[\\/]/).pop()}. <button className="link" onClick={() => { setFile(null); }}>Leave it out</button></span>}
      </div>
      {r && <div aria-label="Sound check result">
        <p role="status">{r.says} <span className="dim">{checkedWords(r)}</span></p>
        {ORDER.map((sev) => {
          const rows = list.filter((f) => f.severity === sev);
          return rows.length ? <div key={sev}><h4>{LABEL[sev]} <span className="dim">{rows.length}</span></h4>
            <ul className="vid-rows">{rows.map((f, i) => <li key={`${f.code}-${f.where}-${i}`}><b>{f.where}</b> <span className="dim">{f.code.replace(/_/g, " ")}{f.confidence ? ` · ${f.confidence} confidence` : ""}</span><div>{f.what}</div></li>)}</ul></div> : null;
        })}
        {r.items.filter((i) => !i.ok).map((i) => <p key={i.where} className="error-text">{i.where}: {i.why}</p>)}
        {r.notes.map((n) => <p key={n} className="dim">{n}</p>)}
        <details><summary>What this does not measure</summary><ul>{r.not_measured.map((n) => <li key={n}>{n}</li>)}</ul>
          <p className="dim">The limits are plain numbers chosen for this tool, not an industry standard.</p></details>
      </div>}
      {err && <p className="error-text" role="alert">{err}</p>}
    </section>
  );
}
