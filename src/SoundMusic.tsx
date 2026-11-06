import { useCallback, useEffect, useMemo, useState } from "react";
import { open } from "@tauri-apps/plugin-dialog";
import { api, errorText, type AiPrice, type AudioAsset, type AudioLibrary, type BibleCharacter, type BibleView, type CastPlan, type VoiceProfile, type VoiceSuggestion } from "./api";
import { ask } from "./ask";
import { SceneSound } from "./SceneSound";
import { MakeSound } from "./MakeSound";
import { SamplePlayer, VoiceMaker } from "./CastVoices";
import { VoiceIdentity } from "./VoiceIdentity";
import { notifyVoice, useCast } from "./voiceHooks";
import { aiAskWords, audioFacts, commaList, PROFILE_FIELDS, SOUND_FIELDS, MUSIC_FIELDS, voiceKey } from "./soundWords";

type Area = "voices" | "sfx" | "music" | "scenes" | "style";
const AREAS: { id: Area; label: string; hint: string }[] = [
  { id: "voices", label: "Voices", hint: "Who each character should sound like" },
  { id: "sfx", label: "Sound effects", hint: "The sounds of this world" },
  { id: "music", label: "Music", hint: "Scores, themes and songs" },
  { id: "scenes", label: "Scene sound", hint: "Plan each scene's soundscape" },
  { id: "style", label: "Sound style", hint: "How the film should sound" },
];
const AUDIO_FILTER = [{ name: "Audio", extensions: ["wav", "mp3", "m4a", "flac", "ogg", "aac"] }];

/**
 * Sound & Music, the audio half of the Production Bible. Everything here is free and local: organising what the film sounds like, importing and hearing sounds you already have, describing
 * them and linking them to people, places and scenes. Voices are a view over the casting that already exists (nothing is generated or chosen for you); the style and the voice profiles
 * are saved in the Bible, the libraries in the film's audio folder. Nothing here is sent anywhere.
 */
export function SoundMusic({ dir, b, run }: { dir: string; b: BibleView; run: (fn: () => Promise<BibleView>) => Promise<BibleView | null> }) {
  const [area, setArea] = useState<Area>("voices");
  return (
    <div className="snd">
      <div className="sm-areas" role="tablist" aria-label="Sound and music">
        {AREAS.map((a) => <button key={a.id} role="tab" aria-selected={area === a.id} className={area === a.id ? "on" : ""} onClick={() => setArea(a.id)}><b>{a.label}</b><span className="dim">{a.hint}</span></button>)}
      </div>
      <p className="dim sm-free">Nothing on this page costs anything: it organises, imports and plays. Making new sounds or music comes later and always shows its price first.</p>
      {area === "voices" && <Voices dir={dir} b={b} run={run} />}
      {area === "sfx" && <Library dir={dir} kind="sfx" b={b} />}
      {area === "music" && <Library dir={dir} kind="music" b={b} />}
      {area === "scenes" && <SceneSound dir={dir} />}
      {area === "style" && <Style b={b} run={run} dir={dir} />}
    </div>
  );
}

// ---------------------------------------------------------------- sound style

function Style({ b, run, dir }: { b: BibleView; run: (fn: () => Promise<BibleView>) => Promise<BibleView | null>; dir: string }) {
  const [style, setStyle] = useState(b.sound_style);
  useEffect(() => { setStyle(b.sound_style); }, [b.sound_style]);
  const dirty = JSON.stringify(style) !== JSON.stringify(b.sound_style);
  const set = (sec: "sound" | "music", k: string, v: string) => setStyle({ ...style, [sec]: { ...style[sec], [k]: v } });
  return (
    <div className="cw-rules sm-style">
      <section>
        <h2>How the film sounds</h2>
        <div className="cw-grid2">{SOUND_FIELDS.map(([k, name, hint]) => <label key={k} className="field"><span>{name}</span>
          <textarea className="text-input" rows={2} value={style.sound[k] ?? ""} placeholder={hint} onChange={(e) => set("sound", k, e.target.value)} /></label>)}</div>
      </section>
      <section>
        <h2>The music</h2>
        <div className="cw-grid2">{MUSIC_FIELDS.map(([k, name, hint]) => <label key={k} className="field"><span>{name}</span>
          <textarea className="text-input" rows={2} value={style.music[k] ?? ""} placeholder={hint} onChange={(e) => set("music", k, e.target.value)} /></label>)}</div>
      </section>
      <div className="cw-save">{dirty ? <span className="dim">Not saved yet</span> : <span className="dim">Saved with the Bible; every change keeps the one before it.</span>}
        <button className="btn" disabled={!dirty} onClick={() => void run(() => api.bible("update_sound_style", dir, { sound_style: style }))}>Save the sound style</button></div>
    </div>
  );
}

// ---------------------------------------------------------------- voices (a view over casting, plus the voice profile)

function Voices({ dir, b, run }: { dir: string; b: BibleView; run: (fn: () => Promise<BibleView>) => Promise<BibleView | null> }) {
  const { cast, reload } = useCast(dir);
  const [sel, setSel] = useState<string | null>(null);
  const [plan, setPlan] = useState<CastPlan | null>(null);
  const [making, setMaking] = useState(false);
  const cur = b.characters.find((c) => c.id === sel) ?? b.characters[0] ?? null;
  useEffect(() => {
    if (!cast?.key) return;
    api.castVoice("status", dir, { plan: true }).then((r) => setPlan(r.plan)).catch(() => {});       // reading the plan is free
  }, [dir, cast?.key]);
  if (!b.characters.length) return <p className="dim cw-empty">No characters yet. They appear in the Characters tab from your story, or add one there.</p>;
  return (
    <div className="cw-body">
      <ul className="cw-list" aria-label="Characters">
        {b.characters.map((c) => {
          const v = cast?.people[voiceKey(c.name)];
          return <li key={c.id}><button className={cur?.id === c.id ? "on" : ""} onClick={() => setSel(c.id)}>
            <span className="nm">{c.name}</span>
            <span className="dim">{v ? (c.voice_profile?.approved ? "approved" : "has a voice") : "no voice"}</span></button></li>;
        })}
      </ul>
      {cur && <VoiceEditor key={cur.id} dir={dir} c={cur} voice={cast?.people[voiceKey(cur.name)]} hasKey={!!cast?.key} run={run} onChoose={() => setMaking(true)} onChanged={() => { reload(); notifyVoice(); }} />}
      {making && cur && cast && <VoiceMaker dir={dir} person={cur.name} cast={cast} plan={plan} replaceApproved={!!cur.voice_profile?.approved} onClose={() => setMaking(false)} onDone={() => { setMaking(false); reload(); notifyVoice(); }} />}
    </div>
  );
}

function VoiceEditor({ dir, c, voice, hasKey, run, onChoose, onChanged }: { dir: string; c: BibleCharacter; voice: { voice_name: string; model: string; made: string } | undefined; hasKey: boolean;
  run: (fn: () => Promise<BibleView>) => Promise<BibleView | null>; onChoose: () => void; onChanged: () => void }) {
  const saved: VoiceProfile = useMemo(() => ({ description: "", age_range: "", accent: "", timbre: "", pace: "", emotional_range: "", delivery: "", notes: "", approved: false, ...(c.voice_profile ?? {}) }), [c.voice_profile]);
  const [p, setP] = useState(saved);
  useEffect(() => setP(saved), [saved]);
  const dirty = JSON.stringify(p) !== JSON.stringify(saved);
  const approve = async (on: boolean) => {
    if (on && !(await ask(`Approve ${voice?.voice_name ?? "this voice"} as ${c.name}'s voice?\n\nApproving protects it: FilmCrafter will never replace an approved voice by itself. You can take the approval back any time. This costs nothing.`, { ok: "Approve" }))) return;
    await run(() => api.bible("set_voice_profile", dir, { id: c.id, approved: on }));
  };
  return (
    <div className="cw-edit">
      <div className="cw-title"><h2 style={{ margin: 0, fontSize: 22 }}>{c.name}</h2><span className="dim">{c.role}{c.age ? ` · ${c.age}` : ""}</span></div>
      <section>
        <h3>The voice they have</h3>
        {voice ? <p className="sm-voice"><b>{voice.voice_name}</b> <span className="dim">from {voice.made === "design" ? "a design" : voice.made === "clone" ? "a recording" : "your library"}</span></p>
          : <p className="dim">{hasKey ? "No voice yet." : "No voice yet. Add your ElevenLabs key in Settings to choose, design or clone one here, or attach your own recordings on the Voiceover screen."}</p>}
        <div className="sm-row">
          {hasKey && <button className="btn" onClick={async () => { if (c.voice_profile?.approved && !(await ask(`${c.name}'s voice is approved.\n\nChoosing another voice replaces it. The approval stays on until you take it back, but FilmCrafter will use the voice you pick next.`, { ok: "Choose another voice" }))) return; onChoose(); }}>{voice ? "Change voice…" : "Give a voice…"}</button>}
          {voice && <label className="ov-check"><input type="checkbox" checked={p.approved} disabled={dirty} onChange={(e) => void approve(e.target.checked)} /> Approved</label>}
        </div>
        <p className="dim sm-note">Choosing a voice asks first, and only designing, cloning or speaking uses your ElevenLabs plan. Choosing from your library is free.</p>
      </section>
      <section>
        <h3>What their voice should be like</h3>
        <div className="cw-fields">{PROFILE_FIELDS.map(([k, name, hint]) => <label key={k} className="field"><span>{name}</span>
          <textarea className="text-input" rows={2} value={(p as unknown as Record<string, string>)[k] ?? ""} placeholder={hint} onChange={(e) => setP({ ...p, [k]: e.target.value })} /></label>)}</div>
        <p className="dim sm-note">A description for you and for the voice assistant. It does not change the voice they have.</p>
        <div className="cw-save"><button className="btn" disabled={!dirty} onClick={() => void run(() => api.bible("set_voice_profile", dir, { id: c.id, ...p }))}>Save</button></div>
      </section>
      <SuggestVoices dir={dir} c={c} hasKey={hasKey} onUse={(s) => setP({ ...p, ...s })} onChanged={onChanged} />
      <VoiceIdentity dir={dir} c={c} hasKey={hasKey} run={run} onChanged={onChanged} />
    </div>
  );
}

/** "Suggest voices for this character": the writing AI proposes what the voice should be like (price first, you choose what to use); matching voices come from your library on this computer. */
function SuggestVoices({ dir, c, hasKey, onUse, onChanged }: { dir: string; c: BibleCharacter; hasKey: boolean; onUse: (s: Partial<VoiceProfile>) => void; onChanged: () => void }) {
  const [r, setR] = useState<VoiceSuggestion | null>(null);
  const [busy, setBusy] = useState("");
  const [err, setErr] = useState("");
  const go = async (what: string, f: () => Promise<void>) => { setErr(""); setBusy(what); try { await f(); } catch (e) { setErr(errorText(e)); } finally { setBusy(""); } };
  const suggest = () => go("ai", async () => {
    const est = await api.voiceDirect<AiPrice>("voices_estimate", dir, { id: c.id });
    if (!(await ask(aiAskWords(`Suggest what ${c.name} should sound like, and look for matching voices?`, est.sends, est), { ok: "Suggest" }))) return;
    setR(await api.voiceDirect<VoiceSuggestion>("voices_suggest", dir, { id: c.id }));
  });
  const match = () => go("match", async () => setR(await api.voiceDirect<VoiceSuggestion>("voices_match", dir, { id: c.id })));
  const use = (id: string, name: string) => go("use", async () => {
    if (c.voice_profile?.approved && !(await ask(`${c.name}'s voice is approved. Replace it with ${name}?`, { ok: "Replace it" }))) return;
    await api.castVoice("set", dir, { person: c.name, voice: { voice_id: id, voice_name: name }, ...(c.voice_profile?.approved ? { replace_approved: true } : {}) });
    onChanged();
  });
  return (
    <section>
      <h3>Find a voice <span className="dim">suggestions only: nothing changes until you choose</span></h3>
      <div className="sm-row">
        <button className="btn" disabled={!!busy} onClick={() => void suggest()}>{busy === "ai" ? "Thinking…" : "Suggest voices for this character…"}</button>
        {hasKey && <button className="btn ghost" disabled={!!busy} onClick={() => void match()} title="Looks through your ElevenLabs library using the notes above. Free.">{busy === "match" ? "Looking…" : "Find matches from my notes (free)"}</button>}
      </div>
      {!hasKey && <p className="dim sm-note">Add your ElevenLabs key in Settings to look through your voice library. The suggestion of what the voice should be like works without it.</p>}
      {err && <p className="error-text" role="alert">{err}</p>}
      {r && <div className="sm-suggest">
        {r.proposal && <div className="sm-prop"><b>What {c.name} might sound like</b>
          <ul>{PROFILE_FIELDS.filter(([k]) => (r.proposal as Record<string, string>)[k]).map(([k, name]) => <li key={k}><span className="dim">{name}:</span> {(r.proposal as Record<string, string>)[k]}</li>)}</ul>
          <button className="btn sm" onClick={() => onUse(Object.fromEntries(PROFILE_FIELDS.map(([k]) => [k, (r.proposal as Record<string, string>)[k]]).filter(([, v]) => v)))}>Put these into the notes above</button>
          <span className="dim"> (you still press Save)</span></div>}
        {r.note && <p className="dim">{r.note}</p>}
        {r.matches.length === 0 && !r.note && <p className="dim">No voice in the {r.searched} looked through fits that clearly. Try describing the voice in the notes, or design one from the casting sheet.</p>}
        {r.matches.map((m) => <div key={m.voice.voice_id} className="cv-item"><div><b>{m.voice.name}</b> <span className="dim">fits: {m.why.join(", ") || "a little"}</span>
          <div className="dim cv-tags">{Object.values(m.voice.labels).slice(0, 4).join(" · ")}{m.voice.description ? ` · ${m.voice.description}` : ""}</div></div>
          {m.voice.preview_url && <SamplePlayer dir={dir} url={m.voice.preview_url} name={m.voice.name} />}
          <button className="btn sm" disabled={!!busy} onClick={() => void use(m.voice.voice_id, m.voice.name)}>Use for {c.name}</button></div>)}
      </div>}
    </section>
  );
}

// ---------------------------------------------------------------- the sound effects and music libraries

function Library({ dir, kind, b }: { dir: string; kind: "sfx" | "music"; b: BibleView }) {
  const [lib, setLib] = useState<AudioLibrary | null>(null);
  const [sel, setSel] = useState<string | null>(null);
  const [err, setErr] = useState("");
  const [note, setNote] = useState("");
  const [filter, setFilter] = useState("");
  const [busy, setBusy] = useState(false);
  const [making, setMaking] = useState(false);
  const act = useCallback(async (f: () => Promise<AudioLibrary>) => { setErr(""); setBusy(true); try { const r = await f(); setLib(r); return r; } catch (e) { setErr(errorText(e)); return null; } finally { setBusy(false); } }, []);
  useEffect(() => { void act(() => api.filmAudio("list", dir, { kind })); }, [dir, kind, act]);
  const assets = (lib?.assets ?? []).filter((a) => a.kind === kind && (!filter || a.category === filter));
  const cur = assets.find((a) => a.id === sel) ?? assets[0] ?? null;
  const cats = lib?.categories[kind] ?? [];
  const names = (id: string) => cats.find((c) => c.id === id)?.name ?? id;

  const add = async () => {
    const picked = await open({ multiple: true, filters: AUDIO_FILTER, title: kind === "sfx" ? "Choose sound effects" : "Choose music" });
    const files = Array.isArray(picked) ? picked : picked ? [picked] : [];
    if (!files.length) return;
    const r = await act(() => api.filmAudio("import", dir, { kind, files, category: filter || undefined }));
    if (r) {
      setNote([r.added?.length ? `Added ${r.added.length}.` : "", ...(r.skipped ?? []).map((s) => `${s.file}: ${s.why}`)].filter(Boolean).join(" "));
      if (r.added?.[0]) setSel(r.added[0]);
    }
  };
  const remove = async (a: AudioAsset) => {
    if (!(await ask(`Take “${a.name}” out of the library?\n\nThe file is moved aside, not deleted, and you can bring it back.`, { ok: "Take it out" }))) return;
    await act(() => api.filmAudio("remove", dir, { id: a.id }));
    setNote(`“${a.name}” was taken out. Its file is kept in the film's audio folder.`);
  };

  return (
    <div className="cw-body">
      <div className="sm-side">
        <div className="sm-row"><button className="btn" disabled={busy} onClick={() => void add()}>{kind === "sfx" ? "Import sounds…" : "Import music…"}</button>
          <button className="btn ghost" disabled={busy} onClick={() => setMaking(true)}>Make with AI…</button>
          <select className="text-input" value={filter} onChange={(e) => setFilter(e.target.value)} aria-label="Category">
            <option value="">All categories</option>{cats.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}</select></div>
        <ul className="cw-list" aria-label={kind === "sfx" ? "Sound effects" : "Music"}>
          {assets.map((a) => <li key={a.id}><button className={cur?.id === a.id ? "on" : ""} onClick={() => setSel(a.id)}>
            <span className="nm">{a.name}</span><span className="dim">{audioFacts(a)}</span></button></li>)}
        </ul>
        {making && <MakeSound dir={dir} kind={kind} onClose={() => setMaking(false)} onMade={() => void act(() => api.filmAudio("list", dir, { kind }))} />}
        {lib && !assets.length && <p className="dim">{kind === "sfx" ? "No sound effects yet. Import the sounds you already have: footsteps, rain, a door. Each gets its own place in the film's library." : "No music yet. Import a score, a theme or a song you have the right to use."}</p>}
      </div>
      <div>
        {note && <p className="cw-note" role="status">{note} <button className="link" onClick={() => setNote("")}>OK</button></p>}
        {err && <p className="error-text" role="alert">{err}</p>}
        {cur ? <AssetEditor key={cur.id} dir={dir} a={cur} b={b} names={names} cats={cats} onSave={(d) => act(() => api.filmAudio("update", dir, { id: cur.id, ...d }))}
                            onApprove={(s) => act(() => api.filmAudio("approve", dir, { id: cur.id, state: s }))} onRemove={() => void remove(cur)} />
          : !lib ? <p className="dim">Opening the library…</p> : null}
        {lib && lib.removed_items.filter((r) => r.kind === kind).length > 0 && <details className="sm-removed"><summary>{lib.removed_items.filter((r) => r.kind === kind).length} taken out</summary>
          <p className="dim">Their files are kept in the film's audio folder; nothing was deleted.</p>
          <ul>{lib.removed_items.filter((r) => r.kind === kind).map((r) => <li key={r.id}>{r.name} <button className="link" onClick={() => void act(() => api.filmAudio("restore", dir, { id: r.id }))}>Bring it back</button></li>)}</ul></details>}
      </div>
    </div>
  );
}

function AssetEditor({ dir, a, b, names, cats, onSave, onApprove, onRemove }: { dir: string; a: AudioAsset; b: BibleView; names: (id: string) => string; cats: { id: string; name: string }[];
  onSave: (d: Record<string, unknown>) => Promise<unknown>; onApprove: (s: "pending" | "approved" | "rejected") => Promise<unknown>; onRemove: () => void }) {
  const [d, setD] = useState({ name: a.name, description: a.description, category: a.category, genre: a.genre, mood: a.mood, tempo: a.tempo, licence: a.licence,
    tags: a.tags.join(", "), places: a.places.join(", "), props: a.props.join(", "), characters: a.characters.join(", "), scenes: a.scenes.join(", "), shots: a.shots.join(", ") });
  const dirty = JSON.stringify(d) !== JSON.stringify({ name: a.name, description: a.description, category: a.category, genre: a.genre, mood: a.mood, tempo: a.tempo, licence: a.licence,
    tags: a.tags.join(", "), places: a.places.join(", "), props: a.props.join(", "), characters: a.characters.join(", "), scenes: a.scenes.join(", "), shots: a.shots.join(", ") });
  const music = a.kind === "music";
  const pick = (k: "places" | "props" | "characters", options: string[]) => (
    <label className="field"><span>{k === "places" ? "Places" : k === "props" ? "Props" : "Characters"}</span>
      <input className="text-input" list={`sm-${k}`} value={d[k]} placeholder={options.slice(0, 3).join(", ")} onChange={(e) => setD({ ...d, [k]: e.target.value })} />
      <datalist id={`sm-${k}`}>{options.map((o) => <option key={o} value={o} />)}</datalist></label>);
  return (
    <div className="cw-edit">
      <div className="cw-title"><input className="cw-name" value={d.name} onChange={(e) => setD({ ...d, name: e.target.value })} aria-label="Name" />
        <span className={`sm-badge ${a.approval}`}>{a.approval === "approved" ? "Approved" : a.approval === "rejected" ? "Rejected" : "Not decided"}</span></div>
      <audio className="sm-player" controls preload="none" src={api.mediaUrl(`${dir}/${a.file}`)} aria-label={`Hear ${a.name}`} />
      <p className="dim sm-facts">{audioFacts(a)} · {a.source === "imported" ? `imported from ${a.original_name}` : "made with FilmCrafter"} · id {a.id}</p>
      {!a.exists && a.exists !== undefined && <p className="error-text">The file is missing from the film's audio folder.</p>}
      <div className="sm-row">
        <button className="btn" disabled={a.approval === "approved"} onClick={() => void onApprove("approved")}>Approve</button>
        <button className="btn ghost" disabled={a.approval === "rejected"} onClick={() => void onApprove("rejected")}>Reject</button>
        {a.approval !== "pending" && <button className="link" onClick={() => void onApprove("pending")}>Undecided</button>}
        <div style={{ flex: 1 }} /><button className="link" onClick={onRemove}>Take out of the library</button>
      </div>
      <div className="cw-fields">
        <label className="field"><span>Category</span><select className="text-input" value={d.category} onChange={(e) => setD({ ...d, category: e.target.value })}>{cats.map((c) => <option key={c.id} value={c.id}>{names(c.id)}</option>)}</select></label>
        <label className="field"><span>Tags</span><input className="text-input" value={d.tags} onChange={(e) => setD({ ...d, tags: e.target.value })} placeholder="rain, night, soft" /></label>
      </div>
      <label className="field"><span>Description</span><textarea className="text-input" rows={2} value={d.description} onChange={(e) => setD({ ...d, description: e.target.value })}
        placeholder={music ? "What it is and where it belongs" : "What you hear, and what it is for"} /></label>
      {music && <div className="cw-fields">
        <label className="field"><span>Genre</span><input className="text-input" value={d.genre} onChange={(e) => setD({ ...d, genre: e.target.value })} /></label>
        <label className="field"><span>Mood</span><input className="text-input" value={d.mood} onChange={(e) => setD({ ...d, mood: e.target.value })} /></label>
        <label className="field"><span>Tempo, if you know it</span><input className="text-input" value={d.tempo} onChange={(e) => setD({ ...d, tempo: e.target.value })} placeholder="72 bpm" /></label>
      </div>}
      <section>
        <h3>Where it belongs</h3>
        <div className="cw-fields">
          {pick("places", b.environments.map((x) => x.name))}
          {!music && pick("props", b.props.map((x) => x.name))}
          {pick("characters", b.characters.map((x) => x.name))}
          <label className="field"><span>Scenes</span><input className="text-input" value={d.scenes} onChange={(e) => setD({ ...d, scenes: e.target.value })} placeholder="1, 3" /></label>
          <label className="field"><span>Shots</span><input className="text-input" value={d.shots} onChange={(e) => setD({ ...d, shots: e.target.value })} placeholder="S01-02" /></label>
        </div>
      </section>
      <details className="cw-spatial" open={music && d.licence.commercial === "unknown"}>
        <summary>Rights {d.licence.commercial === "unknown" ? "· not known yet" : d.licence.commercial === "yes" ? "· cleared for commercial use" : "· not for commercial use"}</summary>
        <div className="cw-fields">
          <label className="field"><span>Where it came from</span><input className="text-input" value={d.licence.source} onChange={(e) => setD({ ...d, licence: { ...d.licence, source: e.target.value } })} placeholder="Your own, a library, a licence" /></label>
          <label className="field"><span>Commercial use</span><select className="text-input" value={d.licence.commercial} onChange={(e) => setD({ ...d, licence: { ...d.licence, commercial: e.target.value as "yes" | "no" | "unknown" } })}>
            <option value="unknown">Not known</option><option value="yes">Allowed</option><option value="no">Not allowed</option></select></label>
        </div>
        <label className="field"><span>Licence note</span><textarea className="text-input" rows={2} value={d.licence.note} onChange={(e) => setD({ ...d, licence: { ...d.licence, note: e.target.value } })} /></label>
        <p className="dim sm-note">You are the one who knows whether you may use this in a released film. FilmCrafter only keeps your note.</p>
      </details>
      <div className="cw-save"><span className="dim">{dirty ? "Not saved yet" : ""}</span>
        <button className="btn" disabled={!dirty} onClick={() => void onSave({ ...d, tags: commaList(d.tags), places: commaList(d.places), props: commaList(d.props), characters: commaList(d.characters), scenes: commaList(d.scenes), shots: commaList(d.shots) })}>Save</button></div>
    </div>
  );
}
