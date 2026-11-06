import { useCallback, useEffect, useState } from "react";
import { open } from "@tauri-apps/plugin-dialog";
import { api, errorText, type CastTake, type RevoicePerson, type RevoiceResult, type RevoiceStatus } from "./api";
import { ask } from "./ask";
import { VoiceRecorder } from "./VoiceRecorder";
import { notifyVoice } from "./voiceHooks";
import { FILTERS } from "./voiceLogic";
import * as I from "./icons";

/** How a reference voice came to be, in plain words. */
export const referenceWords = (p: RevoicePerson): string => {
  if (p.revoked) return "Permission was taken back, so this voice can't be used.";
  if (p.source === "film_take") return "A take in this film's cast voice (no real person's voice is copied).";
  return `${p.holder}'s voice, for: ${p.scope}.`;
};

/** What the Install button tells the person before anything is downloaded. */
export const installWords = (m: RevoiceStatus["runtime"]["model"]): string =>
  `Install ${m.name}?\n\nBy ${m.by}, licence ${m.licence}. ${m.size_note}\n\n${m.needs}\n\nIt is downloaded once onto this computer, in one folder you can delete. It is marked ${m.status}: it has not been checked on every computer. Nothing is uploaded when you use it.`;

/**
 * Perform a line yourself, hear it in the character's voice. Local and free: your recording is changed into the voice, keeping your timing and feeling as far as the model can, and kept as a
 * new take beside the spoken ones. Nothing is attached to the shot until you choose it. A real person's voice as the reference needs their permission, which is recorded and can be taken back.
 */
export function Revoice({ dir, shotId, who, takes, onChanged }: { dir: string; shotId: string; who: string; takes: CastTake[]; onChanged: () => void }) {
  const [st, setSt] = useState<RevoiceStatus | null>(null);
  const [busy, setBusy] = useState("");
  const [err, setErr] = useState("");
  const [perf, setPerf] = useState<{ path: string; name: string } | null>(null);
  const [recording, setRecording] = useState(false);
  const [result, setResult] = useState<RevoiceResult | null>(null);
  const [choosing, setChoosing] = useState(false);
  const [holder, setHolder] = useState("");
  const [scope, setScope] = useState("");
  const [agreed, setAgreed] = useState(false);
  const [used, setUsed] = useState(false);

  const load = useCallback(() => api.revoice("status", dir).then(setSt).catch((e) => setErr(errorText(e))), [dir]);
  useEffect(() => { void load(); }, [load]);

  const run = async (label: string, f: () => Promise<void>) => { setErr(""); setBusy(label); try { await f(); } catch (e) { setErr(errorText(e)); } finally { setBusy(""); } };

  const mine = st?.people.find((p) => p.person.toLowerCase() === who.toLowerCase() || p.key === who.toLowerCase().replace(/[^a-z0-9]+/g, "-"));
  const usable = !!mine && !mine.revoked && !!mine.file;
  const spoken = takes.filter((t) => t.kind !== "revoice");

  const install = () => run("install", async () => {
    if (!st || !(await ask(installWords(st.runtime.model), { ok: "Install" }))) return;
    await api.revoice("install", dir, { confirmed: true });
    await load();
  });
  const setRef = (file: string, consent: boolean) => run("reference", async () => {
    await api.revoice("reference", dir, { person: who, file, consent, holder, scope });
    setChoosing(false); setAgreed(false); setHolder(""); setScope("");
    await load();
  });
  const chooseVoiceFile = () => run("reference", async () => {
    const r = await open({ multiple: false, filters: FILTERS });
    const f = Array.isArray(r) ? r[0] : r;
    if (f) await setRef(f, agreed);
  });
  const takeBack = () => run("revoke", async () => {
    if (!(await ask(`Take back the permission for ${who}'s reference voice?\n\nIt will not be used again. The record of it is kept.`, { ok: "Take it back" }))) return;
    await api.revoice("revoke", dir, { person: who });
    await load();
  });
  const choosePerformance = () => run("file", async () => {
    const r = await open({ multiple: false, filters: FILTERS });
    const f = Array.isArray(r) ? r[0] : r;
    if (f) { setPerf({ path: f, name: f.split(/[\\/]/).pop() ?? f }); setResult(null); setUsed(false); }
  });
  const convert = () => run("convert", async () => {
    if (!perf) return;
    setResult(await api.revoice<RevoiceResult>("convert", dir, { shot: shotId, speaker: who, recording: perf.path }));
    setUsed(false);
    await load(); onChanged();
  });
  const useIt = () => run("use", async () => {
    if (!result) return;
    await api.castVoice("use_take", dir, { shot: shotId, speaker: who, file: result.take });
    setUsed(true); notifyVoice(); onChanged();
  });

  const url = (rel: string) => api.mediaUrl(`${dir}/${rel}`);
  if (!st) return <section className="ls-sec" aria-label="Perform it yourself"><h3>Perform it yourself</h3>{err ? <p className="error-text" role="alert">{err}</p> : <p className="dim">Looking…</p>}</section>;

  return (
    <section className="ls-sec" aria-label="Perform it yourself">
      <h3>Perform it yourself</h3>
      <p className="dim ls-gap">Act the line in your own voice. FilmCrafter changes only the voice, on this computer, free; your timing and feeling are kept as far as the model can. It becomes a take you choose.</p>

      {!st.runtime.installed && <div className="ls-voice" aria-label="Install voice conversion">
        <p><b>{st.runtime.model.name}</b> is not installed. {st.runtime.model.size_note} <span className="dim">Licence {st.runtime.model.licence}. Nothing is downloaded until you press Install.</span></p>
        <div className="ls-btns"><button className="btn sm" disabled={!!busy} onClick={() => void install()}>{busy === "install" ? "Installing… this can take a long time" : "Install…"}</button></div>
      </div>}

      {st.runtime.installed && <>
        <div className="ls-voice" aria-label="Reference voice">
          <I.Mic size={13} /> <b>Sound like</b>
          {usable && mine ? <span> {referenceWords(mine)} <button className="link" disabled={!!busy} onClick={() => setChoosing(true)}>Choose another…</button> {mine.source !== "film_take" && <button className="link" disabled={!!busy} onClick={() => void takeBack()}>Take permission back</button>}</span>
            : <span className="dim"> {mine?.revoked ? referenceWords(mine) : `Choose the voice ${who} should sound like.`} <button className="link" onClick={() => setChoosing(true)}>Choose…</button></span>}
        </div>
        {choosing && <div className="ls-dir" aria-label="Choose a reference voice">
          <div><span className="dim">A take already in {who}'s voice (needs no permission)</span>
            {spoken.length === 0 && <span className="dim"> none yet in this shot: have it spoken first.</span>}
            {spoken.map((t) => <button key={t.file} className="ls-chip" disabled={!!busy} onClick={() => void setRef(t.file, false)}>{t.text.slice(0, 28) || "a take"}</button>)}</div>
          <div><span className="dim">Or a recording of a real voice (3 to 60 seconds)</span>
            <label className="cv-model">Whose voice <input value={holder} onChange={(e) => setHolder(e.target.value)} maxLength={80} placeholder="me, or the person's name" /></label>
            <label className="cv-model">What it may be used for <input value={scope} onChange={(e) => setScope(e.target.value)} maxLength={200} placeholder="this film only" /></label>
            <label className="cv-model"><input type="checkbox" checked={agreed} onChange={(e) => setAgreed(e.target.checked)} /> The owner of this voice agrees to this use.</label>
            <button className="btn sm" disabled={!!busy || !agreed || !holder.trim() || !scope.trim()} onClick={() => void chooseVoiceFile()}>Choose the recording…</button>
            <button className="link" onClick={() => setChoosing(false)}>Cancel</button></div>
        </div>}

        <div className="ls-btns">
          <button className="btn sm" disabled={!!busy || !usable} onClick={() => setRecording(true)}><I.Mic size={13} /> Record your performance</button>
          <button className="btn sm" disabled={!!busy || !usable} onClick={() => void choosePerformance()}><I.Upload size={13} /> Choose a recording…</button>
          {perf && <span className="dim">Ready: {perf.name}</span>}
        </div>
        <div className="ls-btns">
          <button className="btn primary" disabled={!!busy || !usable || !perf} onClick={() => void convert()}><I.Sparkle size={14} /> {busy === "convert" ? "Changing the voice… about a minute" : `Change it into ${who}'s voice`}</button>
          <span className="dim">Free. Nothing is uploaded.</span>
        </div>
        {result && <div className="ls-takes" aria-label="Compare">
          <h4>Compare {result.cached ? <span className="dim">(made before; nothing was run again)</span> : null}</h4>
          <div className="ls-take"><span>Your performance</span><audio controls src={url(result.performance)} aria-label="Your performance" /></div>
          <div className="ls-take"><span>In {who}'s voice</span><audio controls src={url(result.take)} aria-label={`In ${who}'s voice`} /></div>
          <div className="ls-btns">{used ? <span className="ls-cur">in the film</span> : <button className="btn sm" disabled={!!busy} onClick={() => void useIt()}>Use this take for {shotId}</button>}
            <span className="dim">Marked as synthetic audio. Your recording is kept unchanged.</span></div>
        </div>}
      </>}
      {err && <p className="error-text" role="alert">{err}</p>}
      {recording && <VoiceRecorder dir={dir} shotId={shotId} speaker={who} onClose={() => setRecording(false)} onTake={(path) => { setPerf({ path, name: "your recording" }); setResult(null); setUsed(false); }} />}
    </section>);
}
