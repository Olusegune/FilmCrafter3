import { useCallback, useEffect, useMemo, useState } from "react";
import { api, errorText, type BibleCharacter, type BibleView, type CastLibraryEntry, type CastingCompare, type ElevenVoice, type VoiceIdPerson, type VoiceProfile } from "./api";
import { ask } from "./ask";
import { SamplePlayer } from "./CastVoices";

/** The rest of a character's voice identity (the first eight fields are in "What their voice should be like"). */
export const IDENTITY_FIELDS: [keyof VoiceProfile, string, string][] = [
  ["language", "Language", "English, with some Yoruba."],
  ["pitch_range", "Pitch range", "Low, rarely above middle."],
  ["vocal_weight", "Vocal weight", "Light, almost thin."],
  ["texture", "Texture", "Slightly rough at the edges."],
  ["breathiness", "Breathiness", "Breathy when nervous."],
  ["rhythm", "Speaking rhythm", "Short bursts, then a long pause."],
  ["articulation", "Articulation", "Clipped, precise."],
  ["mannerisms", "Vocal habits", "Clears her throat before bad news."],
  ["pronunciation", "Pronunciation notes", "Chloe = KLOH-ee"],
];

/** What the lock status means to the person, in a sentence. */
export const lockWords = (p: VoiceIdPerson): string => {
  if (!p.voice) return "No voice yet, so there is nothing to lock.";
  if (p.consistency.state === "ok") return "Locked. " + p.consistency.words;
  if (p.consistency.state === "unlocked") return p.approved ? "Approved, but not locked. If the voice is changed by mistake, nothing will say so." : "Not locked.";
  return p.consistency.words;
};

/** A cost line for auditioning one voice, with its basis (an estimate: ElevenLabs bills by its own rules). */
export const auditionWords = (credits: number): string => `Hearing it say a line would use about ${credits.toLocaleString()} credits of your ElevenLabs plan (an estimate). Its free sample costs nothing.`;

const SCORES = [1, 2, 3, 4, 5];

/**
 * A character's voice identity beyond the basic profile: the rest of the identity fields, a lock that notices when the approved voice, its model or its reference changes, what you thought of the
 * voice after listening, a side-by-side comparison of candidate voices, and a cast library to use a character again in another film. Nothing here chooses or pays for a voice by itself.
 */
export function VoiceIdentity({ dir, c, hasKey, run, onChanged }: { dir: string; c: BibleCharacter; hasKey: boolean; run: (fn: () => Promise<BibleView>) => Promise<BibleView | null>; onChanged: () => void }) {
  const [me, setMe] = useState<VoiceIdPerson | null>(null);
  const [busy, setBusy] = useState("");
  const [err, setErr] = useState("");
  const saved = useMemo(() => Object.fromEntries(IDENTITY_FIELDS.map(([k]) => [k, ((c.voice_profile ?? {}) as Record<string, string | undefined>)[k] ?? ""])) as Record<string, string>, [c.voice_profile]);
  const [p, setP] = useState(saved);
  useEffect(() => setP(saved), [saved]);
  const dirty = JSON.stringify(p) !== JSON.stringify(saved);
  const [accent, setAccent] = useState("");
  const [accentScore, setAccentScore] = useState(0);
  const [naturalScore, setNaturalScore] = useState(0);
  const [note, setNote] = useState("");
  const [cmp, setCmp] = useState<CastingCompare | null>(null);
  const [lib, setLib] = useState<CastLibraryEntry[] | null>(null);

  const load = useCallback(() => api.voiceId("overview", dir).then((o) => setMe(o.people.find((x) => x.id === c.id) ?? null)).catch((e) => setErr(errorText(e))), [dir, c.id]);
  useEffect(() => { void load(); }, [load, c.voice_profile?.approved]);
  const go = async (label: string, f: () => Promise<void>) => { setErr(""); setBusy(label); try { await f(); } catch (e) { setErr(errorText(e)); } finally { setBusy(""); } };

  const lock = () => go("lock", async () => { await api.voiceId("lock", dir, { person: c.name }); await load(); });
  const unlock = () => go("lock", async () => {
    if (!(await ask(`Stop watching ${c.name}'s voice?\n\nThe record of the lock is kept in the history.`, { ok: "Unlock" }))) return;
    await api.voiceId("unlock", dir, { person: c.name }); await load();
  });
  const rate = () => go("rate", async () => {
    if (!me?.voice) return;
    await api.voiceId("rate", dir, { person: c.name, voice_id: me.voice.voice_id, accent, accent_score: accentScore || null, natural_score: naturalScore || null, note });
    setAccentScore(0); setNaturalScore(0); setNote(""); await load();
  });
  const compare = () => go("compare", async () => {
    const q = (c.voice_profile?.accent ?? "").trim();
    const found = await api.castVoice<{ voices: ElevenVoice[] }>("library", dir, { query: q });
    setCmp(await api.voiceId<CastingCompare>("compare", dir, { person: c.name, candidates: found.voices }));
  });
  const choose = (v: ElevenVoice) => go("choose", async () => {
    if (c.voice_profile?.approved && !(await ask(`${c.name}'s voice is approved. Replace it with ${v.name}?`, { ok: "Replace it" }))) return;
    await api.castVoice("set", dir, { person: c.name, voice: { voice_id: v.voice_id, voice_name: v.name }, ...(c.voice_profile?.approved ? { replace_approved: true } : {}) });
    onChanged(); await load();
  });
  const keep = () => go("keep", async () => { await api.voiceId("library_save", dir, { person: c.name }); setLib((await api.voiceId<{ entries: CastLibraryEntry[] }>("cast_library", dir)).entries); });
  const showLibrary = () => go("library", async () => setLib((await api.voiceId<{ entries: CastLibraryEntry[] }>("cast_library", dir)).entries));
  const use = (e: CastLibraryEntry) => go("use", async () => {
    const clone = e.voice.made === "clone";
    if (!(await ask(`Give ${c.name} the voice and profile of ${e.name} (${e.voice.voice_name})?\n\n${e.rights}${c.voice_profile?.approved ? `\n\n${c.name}'s approved voice will be replaced.` : ""}`, { ok: "Use it" }))) return;
    await api.voiceId("library_use", dir, { person: c.name, id: e.id, replace_approved: !!c.voice_profile?.approved, rights_confirmed: clone });
    onChanged(); await load();
  });

  return (
    <section aria-label="Voice identity" className="vid">
      <h3>Voice identity</h3>
      <div className="cw-fields">{IDENTITY_FIELDS.map(([k, name, hint]) => <label key={k} className="field"><span>{name}</span>
        <textarea className="text-input" rows={2} value={p[k] ?? ""} placeholder={hint} onChange={(e) => setP({ ...p, [k]: e.target.value })} /></label>)}</div>
      <div className="cw-save"><button className="btn" disabled={!dirty || !!busy} onClick={() => void go("save", async () => { await run(() => api.bible("set_voice_profile", dir, { id: c.id, ...p })); })}>Save identity</button></div>

      {me && <div className="vid-lock" aria-label="Lock">
        <h4>Lock</h4>
        <p className={me.consistency.state === "changed" || me.consistency.state === "missing" ? "error-text" : "dim"} role={me.consistency.state === "changed" ? "alert" : undefined}>{lockWords(me)}</p>
        <div className="sm-row">
          {me.voice && !me.lock && <button className="btn sm" disabled={!!busy} onClick={() => void lock()}>Lock this voice</button>}
          {me.lock && <><button className="btn sm" disabled={!!busy} onClick={() => void lock()}>Lock the voice they have now</button><button className="link" disabled={!!busy} onClick={() => void unlock()}>Unlock</button></>}
        </div>
        <p className="dim sm-note">A lock only records which voice, model and reference were approved so a change is noticed. It does not change anything.</p>
      </div>}

      {me?.voice && <div className="vid-rate" aria-label="Rate the voice">
        <h4>After listening to {me.voice.voice_name || "this voice"}</h4>
        <p className="dim">{me.accent.words}{me.natural !== null ? ` Natural: ${me.natural} of 5.` : ""}</p>
        <div className="sm-row">
          <label className="field"><span>Accent you listened for</span><input className="text-input" value={accent} maxLength={40} onChange={(e) => setAccent(e.target.value)} placeholder="Yorkshire" /></label>
          <label className="field"><span>How convincing</span><select value={accentScore} onChange={(e) => setAccentScore(Number(e.target.value))}><option value={0}>not rated</option>{SCORES.map((s) => <option key={s} value={s}>{s} of 5</option>)}</select></label>
          <label className="field"><span>How natural</span><select value={naturalScore} onChange={(e) => setNaturalScore(Number(e.target.value))}><option value={0}>not rated</option>{SCORES.map((s) => <option key={s} value={s}>{s} of 5</option>)}</select></label>
        </div>
        <label className="field"><span>Note</span><input className="text-input" value={note} maxLength={300} onChange={(e) => setNote(e.target.value)} /></label>
        <button className="btn sm" disabled={!!busy || (!accentScore && !naturalScore)} onClick={() => void rate()}>Save my rating</button>
        <p className="dim sm-note">FilmCrafter cannot tell whether an accent is authentic. This is your judgement, kept so you can compare voices.</p>
      </div>}

      <div className="vid-cast" aria-label="Compare voices">
        <h4>Compare voices</h4>
        <button className="btn sm" disabled={!!busy || !hasKey} onClick={() => void compare()}>{busy === "compare" ? "Looking…" : "Compare voices from my library"}</button>
        {!hasKey && <span className="dim"> Add your ElevenLabs key in Settings to search your library.</span>}
        {cmp && <>
          <p className="dim">{cmp.rows.length ? `Best fits for ${cmp.person} of ${cmp.searched} voices.` : "None of the voices in your library fit this profile."} {cmp.note}</p>
          <ul className="vid-rows">{cmp.rows.map((r) => (
            <li key={r.voice.voice_id} className={r.current ? "cur" : ""}>
              <div><b>{r.voice.name}</b> {r.current && <span className="ls-cur">their voice now</span>} <span className="dim">fit {r.score}{r.why.length ? `: ${r.why.join(", ")}` : ""}</span></div>
              <div className="dim">{r.available.where}. {r.licence}</div>
              <div className="dim">{auditionWords(r.audition_credits)}</div>
              {r.rated.count > 0 && <div className="dim">You rated it: {r.rated.accent.words}{r.rated.natural !== null ? ` Natural ${r.rated.natural} of 5.` : ""}</div>}
              <div className="sm-row">{r.voice.preview_url && <SamplePlayer dir={dir} url={r.voice.preview_url} name={r.voice.name} />}
                {!r.current && <button className="btn sm" disabled={!!busy} onClick={() => void choose(r.voice)}>Give {c.name} this voice</button>}</div>
            </li>))}</ul>
        </>}
      </div>

      <div className="vid-lib" aria-label="Cast library">
        <h4>Cast library</h4>
        <div className="sm-row">
          <button className="btn sm" disabled={!!busy || !me?.voice} onClick={() => void keep()}>Keep {c.name} for other films</button>
          <button className="btn sm ghost" disabled={!!busy} onClick={() => void showLibrary()}>Show my cast library</button>
        </div>
        {lib && (lib.length === 0 ? <p className="dim">Nobody is kept yet.</p>
          : <ul className="vid-rows">{lib.map((e) => <li key={e.id}><div><b>{e.name}</b> <span className="dim">{e.voice.voice_name} · from {e.film}</span></div><div className="dim">{e.rights}</div>
            <button className="btn sm" disabled={!!busy} onClick={() => void use(e)}>Use for {c.name}</button></li>)}</ul>)}
        <p className="dim sm-note">Only a reference to the voice in your ElevenLabs account and the profile are kept, not audio. The new voice is not approved or locked.</p>
      </div>
      {err && <p className="error-text" role="alert">{err}</p>}
    </section>
  );
}
