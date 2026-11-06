import { useCallback, useEffect, useRef, useState } from "react";
import { Sheet } from "./Sheet";
import { open } from "@tauri-apps/plugin-dialog";
import { api, errorText, type AiPrice, type CastEstimate, type CastTake, type NaturalSuggestion, type SpokenVersion } from "./api";
import { ask } from "./ask";
import { priceWords, VoiceMaker } from "./CastVoices";
import { VoiceRecorder } from "./VoiceRecorder";
import { Revoice } from "./Revoice";
import { PerformancePlanner } from "./PerformancePlanner";
import { TimingAdr } from "./TimingAdr";
import { Waveform } from "./Waveform";
import { notifyVoice, useCast, useVoiceStatus } from "./voiceHooks";
import { aiAskWords } from "./soundWords";
import { confirmWords } from "./voiceUsage";
import { FILTERS, lineFor } from "./voiceLogic";
import * as I from "./icons";

/** Feelings go at the start of a line (they carry through it); reactions go where they happen. */
const FEELINGS = ["warm", "tender", "sad", "angry", "furious", "nervous", "excited", "sarcastic", "whispering", "shouting", "tired", "amused"];
const REACTIONS = ["laughs", "chuckles", "sighs", "gasps", "sobs", "clears throat", "pauses"];

/**
 * Direct one line: hear what is there, record it, add a file, or have it spoken in the person's ElevenLabs voice with the feeling you choose. Every version spoken is kept as a take you can hear
 * and switch between at no cost. The words you type here are only what is spoken: the shot's written dialogue (and so every picture and video prompt) is never changed.
 * `LineEditor` is the body, to sit inside a panel; `LineStudio` (below) wraps it in a sheet.
 */
export function LineEditor({ dir, shotId, who }: { dir: string; shotId: string; who: string }) {
  const { st } = useVoiceStatus(dir);
  const { cast } = useCast(dir);
  const shot = st?.shots.find((s) => s.id === shotId);
  const person = shot?.people.find((p) => p.name === who);
  const voice = cast?.people[person?.key ?? ""];
  const [text, setText] = useState("");
  const [seeded, setSeeded] = useState(false);
  const [spoken, setSpoken] = useState<SpokenVersion | null>(null);
  const [ideas, setIdeas] = useState<NaturalSuggestion[] | null>(null);
  const [takes, setTakes] = useState<CastTake[]>([]);
  const [est, setEst] = useState<CastEstimate | null>(null);
  const [busy, setBusy] = useState("");
  const [err, setErr] = useState("");
  const [recording, setRecording] = useState(false);
  const [making, setMaking] = useState(false);
  const [playing, setPlaying] = useState<string | null>(null);
  const box = useRef<HTMLTextAreaElement | null>(null);
  const audio = useRef<HTMLAudioElement | null>(null);

  const loadSpoken = useCallback(() => api.voiceDirect<{ lines: SpokenVersion[] }>("performance", dir).then((r) => {
    const mine = r.lines.find((l) => l.shot === shotId && l.speaker.toLowerCase() === who.toLowerCase()) ?? null;
    setSpoken(mine);
    return mine;
  }).catch(() => null), [dir, shotId, who]);
  useEffect(() => {
    if (!shot || seeded) return;
    setSeeded(true);
    void loadSpoken().then((m) => setText(m?.text || lineFor(shot, who)));                       // the person's own spoken version when they made one, else the written line
  }, [shot, seeded, who, loadSpoken]);
  const written = shot ? lineFor(shot, who) : "";
  useEffect(() => () => { audio.current?.pause(); }, []);

  const loadTakes = useCallback(() => {
    api.castVoice<{ takes: CastTake[] }>("takes", dir, { shot: shotId, speaker: who }).then((r) => setTakes(r.takes)).catch(() => setTakes([]));
  }, [dir, shotId, who]);
  useEffect(() => { loadTakes(); }, [loadTakes, st]);

  useEffect(() => {
    if (!voice || !text.trim()) { setEst(null); return; }
    const t = setTimeout(() => {
      api.castVoice<CastEstimate>("estimate", dir, { items: [{ shot: shotId, speaker: who, text }] }).then(setEst).catch(() => setEst(null));
    }, 350);
    return () => clearTimeout(t);
  }, [dir, shotId, who, text, voice]);

  const run = async (label: string, f: () => Promise<void>) => { setErr(""); setBusy(label); try { await f(); } catch (e) { setErr(errorText(e)); } finally { setBusy(""); } };

  const play = (src: string) => {
    audio.current?.pause();
    if (playing === src) { setPlaying(null); return; }
    const a = new Audio(api.mediaUrl(`${dir}/${src}`));
    a.onended = () => setPlaying(null);
    audio.current = a; setPlaying(src);
    void a.play().catch(() => setPlaying(null));
  };

  const addFile = () => run("file", async () => {
    const r = await open({ multiple: false, filters: FILTERS });
    const f = Array.isArray(r) ? r[0] : r;
    if (!f) return;
    await api.voice("import", dir, { items: [{ file: f, shot: shotId, speaker: who }] });
    notifyVoice();
  });
  const remove = () => run("remove", async () => { await api.voice("remove", dir, { shot: shotId, speaker: who }); notifyVoice(); });

  const insert = (tag: string, atStart: boolean) => {
    const el = box.current;
    const at = atStart || !el ? 0 : el.selectionStart ?? text.length;
    const piece = `[${tag}] `;
    const next = atStart ? piece + text.replace(/^\[[^\]]+\]\s*/, "") : text.slice(0, at) + piece + text.slice(at);
    setText(next);
    requestAnimationFrame(() => { el?.focus(); const pos = atStart ? piece.length : at + piece.length; el?.setSelectionRange(pos, pos); });
  };

  const speak = () => run("speak", async () => {
    const e = est ?? await api.castVoice<CastEstimate>("estimate", dir, { items: [{ shot: shotId, speaker: who, text }] });
    const row = e.rows[0];
    if (!row.ok) throw new Error(row.why);
    if (!row.cached && !(await ask(`Speak ${shotId} as ${who}?\n\n“${text}”\n\n${priceWords(e)}`, { ok: "Speak it" }))) return;
    await api.castVoice("speak", dir, { shot: shotId, speaker: who, text, confirmed: true });
    notifyVoice(); loadTakes();
  });
  const saveSpoken = () => run("spoken", async () => { await api.voiceDirect("performance_set", dir, { shot: shotId, speaker: who, text }); await loadSpoken(); });
  const backToWritten = () => run("spoken", async () => { await api.voiceDirect("performance_clear", dir, { shot: shotId, speaker: who }); setSpoken(null); setText(written); });
  const natural = () => run("natural", async () => {
    const est = await api.voiceDirect<AiPrice>("natural_estimate", dir, { shot: shotId, speaker: who });
    if (!(await ask(aiAskWords(`Suggest more natural ways to say ${who}'s line in ${shotId}?`, est.sends, est), { ok: "Suggest" }))) return;
    setIdeas((await api.voiceDirect<{ suggestions: NaturalSuggestion[] }>("natural_suggest", dir, { shot: shotId, speaker: who })).suggestions);
  });
  const anotherTake = () => run("another", async () => {
    const e = await api.castVoice<CastEstimate>("estimate", dir, { items: [{ shot: shotId, speaker: who, text, new_take: true }] });
    const row = e.rows[0];
    if (!row.ok) throw new Error(row.why);
    if (!(await ask(confirmWords({ action: `Make another take of ${shotId} as ${who}?\n\n“${text}”\n\nSame words, a different performance. Your other takes are kept.`, provider: "ElevenLabs", cost: priceWords({ characters: row.characters, credits: row.credits }) }), { ok: "Make another take" }))) return;
    await api.castVoice("speak", dir, { shot: shotId, speaker: who, text, new_take: true, confirmed: true });
    notifyVoice(); loadTakes();
  });
  const useTake = (t: CastTake) => run("take", async () => { await api.castVoice("use_take", dir, { shot: shotId, speaker: who, file: t.file }); notifyVoice(); loadTakes(); });
  const changeModel = (model: string) => run("model", async () => {
    if (!voice) return;
    await api.castVoice("set", dir, { person: who, voice: { ...voice, model } });
    notifyVoice();
  });

  const tagged = voice ? !!cast?.models.find((m) => m.id === voice.model)?.tagged : false;       // which models read [tags] as direction comes from the engine (one list, cast_voice.TAGGED)
  const rec = person?.recording;
  const price = est && est.rows[0]?.ok ? priceWords(est) : "";

  return (
    <div className="ls-body">
        <section className="ls-sec" aria-label="The recording now">
          <h3>Now in the film</h3>
          {rec ? <div className="ls-now">
            <button className="vchip-play" onClick={() => play(rec.file)} aria-label={`${playing === rec.file ? "Stop" : "Play"} the current recording`}>{playing === rec.file ? <I.Pause size={12} /> : <I.Play size={12} />}<span className="num">{rec.seconds.toFixed(1)}s</span></button>
            <div className="vo-wave has ls-wave"><Waveform src={api.mediaUrl(`${dir}/${rec.file}`)} /></div>
            <span className="dim">{rec.source === "elevenlabs" ? "spoken by ElevenLabs" : "your recording"}</span>
          </div> : <p className="dim ls-gap">No voice yet. {person?.lines.length ? <>The line: “{person.lines.join(" ")}”</> : "Nothing is written for this person here."}</p>}
          <div className="ls-btns">
            <button className="btn sm" disabled={!!busy} onClick={() => setRecording(true)}><I.Mic size={13} /> {rec ? "Re-record" : "Record"}</button>
            <button className="btn sm" disabled={!!busy} onClick={() => void addFile()}><I.Upload size={13} /> {rec ? "Replace with a file…" : "Add a file…"}</button>
            {rec && <button className="link" disabled={!!busy} onClick={() => void remove()}>Remove</button>}
            <span className="dim">or drop a file on this person's clip on the timeline</span>
          </div>
        </section>

        <section className="ls-sec" aria-label="Have it spoken">
          <h3>Have it spoken</h3>
          {!cast?.key && <p className="dim">Add your ElevenLabs key in <b>Settings</b> to have lines spoken in a voice you choose.</p>}
          {cast?.key && !voice && <p className="dim">{who} has no voice yet. <button className="link" onClick={() => setMaking(true)}>Choose, design or clone one…</button></p>}
          {voice && <>
            <div className="ls-voice"><I.Mic size={13} /> <b>{voice.voice_name || "A voice"}</b>
              <label className="cv-model">Model <select value={voice.model} disabled={!!busy} onChange={(e) => void changeModel(e.target.value)}>{cast!.models.map((m) => <option key={m.id} value={m.id}>{m.label}</option>)}</select></label>
              <button className="link" onClick={() => setMaking(true)}>Change voice…</button></div>
            <textarea ref={box} className="ls-text" rows={3} value={text} onChange={(e) => setText(e.target.value)} aria-label="What is spoken" placeholder="What they say…" />
            <div className="ls-spoken">
              {spoken?.written_changed && <p className="error-text">The written line has changed since you made this spoken version. The written line now reads: “{written}”</p>}
              {spoken ? <span className="dim">This is your spoken version{spoken.source === "assistant" ? " (from a suggestion you accepted)" : ""}. The written line stays: “{written}”.</span>
                : <span className="dim">This is the written line. Change it here and save it as your spoken version; the film's written dialogue is never changed.</span>}
              <div className="ls-btns">
                <button className="btn sm" disabled={!!busy || !text.trim() || text.trim() === (spoken?.text ?? written).trim()} onClick={() => void saveSpoken()}>Save as the spoken version</button>
                {spoken && <button className="link" disabled={!!busy} onClick={() => void backToWritten()}>Go back to the written line</button>}
                <button className="btn sm ghost" disabled={!!busy || !text.trim()} onClick={() => void natural()}>{busy === "natural" ? "Listening…" : "Make this sound more natural…"}</button>
              </div>
              {ideas && <div className="ls-ideas" aria-label="Suggestions">
                {ideas.length === 0 && <p className="dim">Nothing better to suggest for this line. It already reads naturally.</p>}
                {ideas.map((s) => <div key={s.text} className="ls-idea"><q>{s.text}</q><span className="dim">{s.why} {s.keeps_meaning_check}</span>
                  <button className="btn sm" onClick={() => { setText(s.text); setIdeas(null); }}>Try this</button></div>)}
                {ideas.length > 0 && <button className="link" onClick={() => setIdeas(null)}>Not now</button>}
              </div>}
            </div>
            {tagged ? <div className="ls-dir" aria-label="Direction">
              <div><span className="dim">Feeling (starts the line)</span>{FEELINGS.map((f) => <button key={f} className="ls-chip" onClick={() => insert(f, true)}>{f}</button>)}</div>
              <div><span className="dim">Reaction (where the cursor is)</span>{REACTIONS.map((f) => <button key={f} className="ls-chip" onClick={() => insert(f, false)}>{f}</button>)}</div>
              <p className="dim ls-tip">Any feeling works in plain words: type <b>[tired but trying to smile]</b>. “…” slows a line, “—” cuts it off, “!” adds force. The film's written dialogue is not changed.</p>
            </div> : <p className="dim ls-tip">This model speaks the words as written. Choose <b>Eleven v4</b> above to direct feeling and reactions with [tags].</p>}
            <div className="ls-btns"><button className="btn primary" disabled={!!busy || !text.trim()} onClick={() => void speak()}><I.Sparkle size={14} /> {busy === "speak" ? "Speaking…" : "Speak this"}</button>
              {takes.some((t) => t.text === text.trim()) && <button className="btn" disabled={!!busy} onClick={() => void anotherTake()}>{busy === "another" ? "Making…" : "Make another take"}</button>}
              <span className="dim">{price || "The price is shown first."}</span></div>
          </>}
          {takes.length > 0 && <div className="ls-takes"><h4>Takes <span className="dim">({takes.length}) · switching between them is free</span></h4>
            {takes.map((t) => (
              <div key={t.file} className={`ls-take ${t.current ? "cur" : ""}`}>
                <button className="vchip-play" onClick={() => play(t.file)} aria-label={`${playing === t.file ? "Stop" : "Hear"} this take`}>{playing === t.file ? <I.Pause size={12} /> : <I.Play size={12} />}</button>
                {t.kind === "revoice" ? <><q>Performed by {t.performed_by || "a person"}, in {who}'s voice</q><span className="dim ls-model">re-voiced on this computer · synthetic</span></>
                  : t.kind === "adr" ? <><q>ADR retake{t.performed_by ? ` by ${t.performed_by}` : ""}</q><span className="dim ls-model">{t.note || "a new recording of the line"}</span></>
                  : t.kind === "dubfit" ? <><q>Fitted to the shot</q><span className="dim ls-model">{t.note || "tempo changed, pitch kept"}</span></>
                  : <><q>{t.text}</q><span className="dim ls-model">{t.model?.replace("eleven_", "").replace("_", " ")}{t.another_take ? " · another take" : ""}</span></>}
                {t.current ? <span className="ls-cur">in the film</span> : <button className="btn sm" disabled={!!busy} onClick={() => void useTake(t)}>Use this take</button>}
              </div>))}
          </div>}
        </section>
        <PerformancePlanner dir={dir} shotId={shotId} who={who} onChanged={() => { void loadSpoken().then((m) => { if (m) setText(m.text); }); }} />
        <TimingAdr dir={dir} shotId={shotId} who={who} onChanged={() => { loadTakes(); notifyVoice(); }} />
        <Revoice dir={dir} shotId={shotId} who={who} takes={takes} onChanged={loadTakes} />
        {err && <p className="error-text" role="alert">{err}</p>}
        <p className="dim vr-hint">Nothing is deleted: a take or recording you replace is kept in the film's voice/_removed folder.</p>
      {recording && <VoiceRecorder dir={dir} shotId={shotId} speaker={who} onClose={() => setRecording(false)} />}
      {making && cast && <VoiceMaker dir={dir} person={who} cast={cast} plan={null} onClose={() => setMaking(false)} onDone={() => { setMaking(false); notifyVoice(); }} />}
    </div>);
}

/** The line editor in a sheet of its own (opened from a clip on the timeline). */
export function LineStudio({ dir, shotId, who, onClose }: { dir: string; shotId: string; who: string; onClose: () => void }) {
  const { st } = useVoiceStatus(dir);
  const shot = st?.shots.find((x) => x.id === shotId);
  useEffect(() => {
    const k = (e: KeyboardEvent) => { if (e.key === "Escape" && !document.querySelector(".vr, .cv-sheet")) { e.stopImmediatePropagation(); onClose(); } };      // not while the recorder or the voice chooser is open over it
    window.addEventListener("keydown", k, true);
    return () => window.removeEventListener("keydown", k, true);
  }, [onClose]);
  return (
    <Sheet label={`${who} in ${shotId}`} className="ls" onDismiss={onClose}>
        <div className="vs-head"><h2><span className="num">{shotId}</span> · {who}</h2><span className="dim">{shot ? `${shot.seconds}s shot` : ""}</span>
          <div style={{ flex: 1 }} /><button className="icon-btn" onClick={onClose} aria-label="Close"><I.Close size={18} /></button></div>
        <LineEditor dir={dir} shotId={shotId} who={who} />
    </Sheet>);
}
