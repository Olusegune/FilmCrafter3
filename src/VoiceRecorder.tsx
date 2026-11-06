import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Sheet } from "./Sheet";
import { api, errorText, type VoiceShot } from "./api";
import { encodeWav, lineFor, nextUnvoiced, peaksOf, trimSilence } from "./voiceLogic";
import { notifyVoice, useVoiceStatus } from "./voiceHooks";
import { WaveBars } from "./Waveform";
import * as I from "./icons";

type Take = { samples: Float32Array; rate: number; url: string; seconds: number; peaks: number[] };

const micWords = (e: unknown): string => {
  const n = (e as { name?: string })?.name;
  if (n === "NotAllowedError" || n === "SecurityError") return "FilmCrafter is not allowed to use the microphone. In Windows: Settings, Privacy & security, Microphone, then allow desktop apps.";
  if (n === "NotFoundError" || n === "OverconstrainedError") return "No microphone was found. Plug one in, then press Record again.";
  if (n === "NotReadableError") return "The microphone is in use by another program. Close it, then try again.";
  return errorText(e);
};

/**
 * Record a line without leaving FilmCrafter. The line is shown large to read from; Space starts and stops; the take is trimmed of silence, you hear it, then Keep (Enter) attaches it to the person
 * and moves to the next line that has no voice yet, or Retake (R) to do it again (a kept take it replaces is stored in the film's voice/_removed, never deleted). Esc closes.
 */
export function VoiceRecorder({ dir, shotId, speaker, onClose, onTake }: { dir: string; shotId: string; speaker?: string; onClose: () => void; onTake?: (path: string) => void }) {
  const { st, reload } = useVoiceStatus(dir);
  const [cur, setCur] = useState(shotId);
  const [who, setWho] = useState(speaker ?? "");
  const [mode, setMode] = useState<"idle" | "recording" | "review" | "saving">("idle");
  const [take, setTake] = useState<Take | null>(null);
  const [err, setErr] = useState("");
  const [said, setSaid] = useState("");
  const [secs, setSecs] = useState(0);
  const level = useRef<HTMLDivElement | null>(null);
  const stop = useRef<(() => void) | null>(null);
  const live = useRef(true);

  const shots = st?.shots ?? [];
  const shot: VoiceShot | undefined = shots.find((s) => s.id === cur);
  const people = shot?.people ?? [];
  const person = people.find((p) => p.name === who) ?? people.find((p) => !p.recording) ?? people[0];
  const line = lineFor(shot, person?.name ?? "");

  useEffect(() => { if (person && person.name !== who) setWho(person.name); }, [person, who]);
  useEffect(() => { live.current = true; return () => { live.current = false; stop.current?.(); }; }, []);
  useEffect(() => () => { if (take) URL.revokeObjectURL(take.url); }, [take]);

  const start = useCallback(async () => {
    setErr(""); setSaid("");
    let stream: MediaStream;
    try { stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: false, noiseSuppression: false, autoGainControl: false } }); }
    catch (e) { setErr(micWords(e)); return; }
    const ctx = new AudioContext();
    const an = ctx.createAnalyser(); an.fftSize = 1024;
    ctx.createMediaStreamSource(stream).connect(an);
    const rec = new MediaRecorder(stream);
    const chunks: Blob[] = [];
    const t0 = performance.now();
    let raf = 0;
    const buf = new Float32Array(an.fftSize);
    const tick = () => {
      an.getFloatTimeDomainData(buf);
      let m = 0; for (const v of buf) m = Math.max(m, Math.abs(v));
      if (level.current) level.current.style.width = `${Math.min(100, Math.round(Math.sqrt(m) * 100))}%`;
      setSecs((performance.now() - t0) / 1000);
      raf = requestAnimationFrame(tick);
    };
    rec.ondataavailable = (e) => { if (e.data.size) chunks.push(e.data); };
    rec.onstop = async () => {
      cancelAnimationFrame(raf);
      stream.getTracks().forEach((t) => t.stop());
      if (level.current) level.current.style.width = "0%";
      stop.current = null;
      try {
        const audio = await ctx.decodeAudioData(await new Blob(chunks).arrayBuffer());
        void ctx.close().catch(() => {});
        const raw = audio.getChannelData(0);
        const cut = trimSilence(raw, audio.sampleRate);
        if (!live.current) return;
        const url = URL.createObjectURL(new Blob([encodeWav(cut, audio.sampleRate) as BlobPart], { type: "audio/wav" }));
        setTake({ samples: cut, rate: audio.sampleRate, url, seconds: cut.length / audio.sampleRate, peaks: peaksOf(cut, 96) });
        setMode("review");
      } catch (e) { if (live.current) { setErr(`That take could not be read: ${errorText(e)}`); setMode("idle"); } }
    };
    stop.current = () => { if (rec.state !== "inactive") rec.stop(); };
    rec.start();
    setMode("recording");
    raf = requestAnimationFrame(tick);
  }, []);

  const finish = () => stop.current?.();
  const retake = () => { setTake(null); setMode("idle"); setSecs(0); };
  const goNext = useCallback((after: string) => {
    const n = nextUnvoiced(shots, after);
    setTake(null); setMode("idle"); setSecs(0);
    if (n) { setCur(n.id); setWho(""); setSaid(`Saved. Next: ${n.id}.`); } else setSaid("Saved. Every voice is recorded.");
  }, [shots]);

  const keep = useCallback(async () => {
    if (!take || !person) return;
    setMode("saving"); setErr("");
    try {
      const path = await api.saveVoiceTake(encodeWav(take.samples, take.rate));
      if (onTake) { onTake(path); onClose(); return; }          // a performance to be re-voiced: nothing is attached to the shot here
      const r = await api.voice<{ attached: unknown[]; failed: { file: string; why: string }[] }>("import", dir, { items: [{ file: path, shot: cur, speaker: person.name }] });
      if (!r.attached.length) { setErr(r.failed[0]?.why ?? "That take could not be attached."); setMode("review"); return; }
      notifyVoice(); reload();
      // someone else in this shot still has no voice: stay on the shot and move to them; otherwise the next shot that needs one
      const rest = people.find((p) => p.name !== person.name && !p.recording);
      if (rest) { setWho(rest.name); setTake(null); setMode("idle"); setSecs(0); setSaid(`Saved. Now ${rest.name}.`); } else goNext(cur);
    } catch (e) { setErr(errorText(e)); setMode("review"); }
  }, [take, person, dir, cur, people, goNext, reload, onTake, onClose]);

  useEffect(() => {
    const k = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement | null;
      if (t && /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName)) return;
      if (e.key === "Escape") { e.stopImmediatePropagation(); if (mode === "recording") finish(); else onClose(); }
      else if (e.key === " " && (mode === "idle" || mode === "recording")) { e.preventDefault(); if (mode === "idle") void start(); else finish(); }
      else if (e.key === "Enter" && mode === "review") { e.preventDefault(); void keep(); }
      else if ((e.key === "r" || e.key === "R") && mode === "review") retake();
    };
    window.addEventListener("keydown", k, true);                 // first in line, so Esc closes only the recorder when it sits over the Voiceover sheet
    return () => window.removeEventListener("keydown", k, true);
  }, [mode, start, keep, onClose]);

  const left = useMemo(() => shots.reduce((n, s) => n + (s.people ?? []).filter((p) => !p.recording).length, 0), [shots]);
  const total = useMemo(() => shots.reduce((n, s) => n + (s.people ?? []).length, 0), [shots]);
  const done = !!st && left === 0;

  return (
    <Sheet label="Record a voice" className="vr" onDismiss={() => { if (mode !== "recording") onClose(); }}>
        <div className="vs-head"><h2>Record <span className="num">{cur}</span></h2>
          <span className="dim vr-prog">{st ? `${total - left} of ${total} voices recorded` : ""}</span>
          <div style={{ flex: 1 }} /><button className="icon-btn" onClick={onClose} aria-label="Close"><I.Close size={18} /></button></div>

        {!shot && <p className="dim">{st ? "Nobody speaks in this shot." : "Getting the film's voices…"}</p>}
        {shot && people.length === 0 && <p className="dim">Nobody speaks in {cur}. {nextUnvoiced(shots, cur) ? "Skip to the next line." : ""}</p>}
        {shot && people.length > 0 && <>
          <div className="vr-who" role="tablist" aria-label="Who is speaking">
            {people.map((p) => <button key={p.key} role="tab" aria-selected={p.name === person?.name} className={p.name === person?.name ? "on" : ""} disabled={mode === "recording" || mode === "saving"}
              onClick={() => { setWho(p.name); setTake(null); setMode("idle"); }}>{p.name}{p.recording ? " ✓" : ""}</button>)}
          </div>
          <blockquote className="vr-line">{line ? line : <span className="dim">No line is written for {person?.name} in this shot. Say what you like.</span>}</blockquote>
          <div className="vr-meter" aria-hidden="true"><div ref={level} /></div>
          <div className="vr-time num">{mode === "recording" ? `${secs.toFixed(1)} s` : take ? `${take.seconds.toFixed(1)} s` : "0.0 s"} <span className="dim">of a {shot.seconds} s shot{(mode === "recording" ? secs : take?.seconds ?? 0) > shot.seconds ? " (the shot will be lengthened to hold it)" : ""}</span></div>

          {mode === "review" && take && <div className="vr-take"><div className="vo-wave has"><WaveBars peaks={take.peaks} /></div><audio controls src={take.url} aria-label="Your take" /></div>}

          <div className="vr-actions">
            {mode === "idle" && <button className="btn primary vr-rec" onClick={() => void start()}><I.Mic size={16} /> Record <kbd>Space</kbd></button>}
            {mode === "recording" && <button className="btn primary vr-rec on" onClick={finish}><span className="vr-dot" /> Stop <kbd>Space</kbd></button>}
            {(mode === "review" || mode === "saving") && <>
              <button className="btn primary" disabled={mode === "saving"} onClick={() => void keep()}>{mode === "saving" ? "Saving…" : <>Keep this take <kbd>Enter</kbd></>}</button>
              <button className="btn" disabled={mode === "saving"} onClick={retake}>Retake <kbd>R</kbd></button>
            </>}
            {mode !== "recording" && mode !== "saving" && nextUnvoiced(shots, cur) && !done && <button className="btn ghost" onClick={() => goNext(cur)}>Skip to the next line</button>}
          </div>
        </>}
        {said && <p className="vr-said" role="status">{said}</p>}
        {done && <p className="vr-said" role="status">Every voice in the film is recorded.</p>}
        {err && <p className="error-text" role="alert">{err}</p>}
        <p className="dim vr-hint">Your take is trimmed of silence before it is attached. A voice you replace is kept in the film's voice/_removed folder.</p>
    </Sheet>
  );
}
