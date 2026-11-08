import { useCallback, useEffect, useState } from "react";
import { open } from "@tauri-apps/plugin-dialog";
import { api, errorText, type AssistKind, type BibleCharacter, type BibleEnvironment, type BibleProp, type BibleView } from "./api";
import { AssistSheet, askForHelp } from "./AssistSheet";
import { ask } from "./ask";
import { askText } from "./askText";
import { PrincipleIcon } from "./principleIcons";
import { SoundMusic } from "./SoundMusic";
import * as I from "./icons";
import { PlaceSet } from "./PlaceSet";
import { SetBuilder } from "./SetBuilder";
import { DirectorCam } from "./DirectorCam";
import { Reconstruct } from "./Reconstruct";

type Kind = "character" | "environment" | "prop";
type Entry = BibleCharacter | BibleEnvironment | BibleProp;
type Tab = "bible" | Kind | "sound";

const TABS: { id: Tab; label: string }[] = [{ id: "bible", label: "Rules & style" }, { id: "character", label: "Characters" }, { id: "environment", label: "Places" }, { id: "prop", label: "Props" }, { id: "sound", label: "Sound & Music" }];
const RULES: [string, string, string][] = [["world", "The world", "What is always true here: the place, the era, how things work."], ["tone", "Tone", "How it should feel to watch."],
  ["rules", "Rules the film keeps", "Anything that must never change (a character never takes off her ring)."], ["avoid", "Avoid", "What should never appear."]];
const PHILOSOPHY: [string, string][] = [["visual", "Visual"], ["cinematography", "Cinematography"], ["lighting", "Lighting"], ["acting", "Acting"], ["colour", "Colour"], ["continuity", "Continuity"]];
const CHAR_FIELDS: [string, string, boolean][] = [["role", "Role in the story", false], ["age", "Age", false], ["physical", "Physical traits", true], ["relationships", "Relationships", true], ["arc", "Emotional arc", true], ["voice", "Voice", false], ["notes", "Notes", true]];
const SPATIAL: [string, string][] = [["entrances", "Entrances"], ["exits", "Exits"], ["doors", "Doors"], ["windows", "Windows"], ["landmarks", "Landmarks"], ["furniture", "Furniture"],
  ["blocking", "Where actors can stand"], ["camera_zones", "Where the camera can go"], ["lighting", "Lighting"], ["day_night", "Day or night"]];

const label = (t: Tab) => TABS.find((x) => x.id === t)!.label;

/**
 * The Production Bible, Cast and World: the one source of truth the rest of the film is made from. Seeded from the story, then yours.
 * Characters, places and props are single entries with related states (Sarah at 8, at 28, at 70; the kitchen by day and by night).
 */
export function CastWorld({ dir, initialTab }: { dir: string; initialTab?: Tab }) {
  const [b, setB] = useState<BibleView | null>(null);
  const [tab, setTab] = useState<Tab>(initialTab ?? "character");
  const [sel, setSel] = useState<string | null>(null);
  const [err, setErr] = useState("");
  const [note, setNote] = useState("");
  const [helping, setHelping] = useState("");
  const [setView, setSetView] = useState<{ kind: "set" | "plan" | "continuity"; id: string } | null>(null);
  const [recon, setRecon] = useState<{ id: string; name: string } | null>(null);
  const [placeTick, setPlaceTick] = useState(0);
  const [assist, setAssist] = useState<{ kind: AssistKind; id: string | null; name: string; proposal: Record<string, unknown> } | null>(null);
  /** Optional writing help: shows the price first, asks for a yes, then shows a suggestion to pick from. Never changes anything by itself. */
  const help = async (kind: AssistKind, id: string | null, name: string) => {
    setErr(""); setHelping(`${kind}:${id}`);
    try { const proposal = await askForHelp(dir, kind, id, name); if (proposal) setAssist({ kind, id, name, proposal }); } catch (e) { setErr(errorText(e)); } finally { setHelping(""); }
  };

  const apply = (v: BibleView) => setB(v);
  const run = useCallback(async (fn: () => Promise<BibleView>) => { setErr(""); try { const v = await fn(); setB(v); return v; } catch (e) { setErr(errorText(e)); return null; } }, []);
  useEffect(() => {
    // The first time, fill the Bible from the story. Seeding only adds, so doing it again is always safe.
    void run(async () => {
      const v = await api.bible("get", dir);
      if (v.counts.characters + v.counts.environments === 0) {
        const s = await api.bible("seed", dir);
        if (s.added && (s.added.characters || s.added.environments)) setNote(`Filled from your story: ${s.added.characters} characters and ${s.added.environments} places. Check them and add what the story doesn't say.`);
        return s;
      }
      return v;
    });
  }, [dir, run]);

  if (!b) return <div className="cw"><div className="film-load dim">{err || "Opening the Bible…"}</div></div>;
  const list: Entry[] = tab === "character" ? b.characters : tab === "environment" ? b.environments : tab === "prop" ? b.props : [];
  const cur = list.find((x) => x.id === sel) ?? list[0] ?? null;

  const refresh = async () => {
    const s = await run(() => api.bible("seed", dir));
    if (s?.added) setNote(s.added.characters || s.added.environments ? `Added ${s.added.characters} characters and ${s.added.environments} places from the story.` : "Everything in the story is already here.");
  };
  const add = async () => {
    const name = await askText(`Name the new ${tab === "environment" ? "place" : tab}`, tab === "character" ? "e.g. Sarah" : tab === "environment" ? "e.g. The kitchen" : "e.g. The letter");
    if (!name) return;
    const v = await run(() => api.bible("upsert", dir, { kind: tab, item: { name } }));
    if (v?.id) setSel(v.id);
  };

  return (
    <div className="cw">
      <div className="cw-frame">
      <div className="cw-head">
        <div className="cw-tabs" role="tablist">
          {TABS.map((t) => <button key={t.id} role="tab" aria-selected={tab === t.id} className={tab === t.id ? "on" : ""} onClick={() => { setTab(t.id); setSel(null); }}>
            {t.label}{t.id !== "bible" && t.id !== "sound" && <span className="dim"> {t.id === "character" ? b.counts.characters : t.id === "environment" ? b.counts.environments : b.counts.props}</span>}</button>)}
        </div>
        <div style={{ flex: 1 }} />
        <button className="btn ghost sm" onClick={refresh} title="Add anything new from the story. Nothing you wrote is changed.">Add from the story</button>
      </div>
      {note && <p className="cw-note" role="status">{note} <button className="link" onClick={() => setNote("")}>OK</button></p>}
      {b.need.length > 0 && tab === "bible" && <ul className="cw-need">{b.need.map((n) => <li key={n}>{n}</li>)}</ul>}
      {err && <p className="error-text" role="alert">{err}</p>}

      {tab === "sound" ? <SoundMusic dir={dir} b={b} run={run} /> : tab === "bible" ? <RulesStyle b={b} onSave={(d) => run(() => api.bible("update_rules", dir, d))} helping={helping === "world:null"} onHelp={() => help("world", null, "your world and style")} /> : (
        <div className="cw-body">
          <ul className="cw-list" aria-label={label(tab)}>
            {list.map((x) => {
              const pic = x.media[0]?.path;
              return <li key={x.id}><button className={cur?.id === x.id ? "on" : ""} onClick={() => setSel(x.id)}>
                <span className="thumb" style={pic ? { backgroundImage: `url("${api.mediaUrl(`${dir}/${pic}`)}")` } : undefined}>{!pic && <I.ImageIcon size={14} />}</span>
                <span className="nm">{x.name}</span>{x.states.length > 1 && <span className="dim">{x.states.length} states</span>}</button></li>;
            })}
            <li><button className="add" onClick={add}>+ Add {tab === "environment" ? "a place" : tab === "prop" ? "a prop" : "a character"}</button></li>
          </ul>
          {cur ? <Editor key={cur.id} dir={dir} kind={tab as Kind} item={cur} media={b.media_kinds} run={run} apply={apply} helping={helping === `${tab}:${cur.id}`} onHelp={() => help(tab as AssistKind, cur.id, cur.name)} onOpenSet={(id) => setSetView({ kind: "set", id })} onPlan={(id) => setSetView({ kind: "plan", id })} onCheck={(id) => setSetView({ kind: "continuity", id })} onReconstruct={() => setRecon({ id: cur.id, name: cur.name })} tick={placeTick} />
            : <p className="dim cw-empty">{tab === "character" ? "No characters yet. They appear from the story, or add one." : tab === "environment" ? "No places yet." : "No props yet. Add anything that must look the same every time it appears."}</p>}
        </div>)}
      </div>
      {setView?.kind === "set" && <SetBuilder dir={dir} openSet={setView.id} onClose={() => setSetView(null)} />}
      {recon && <Reconstruct dir={dir} place={recon.id} name={recon.name} onClose={() => { setRecon(null); setPlaceTick((n) => n + 1); }} onDone={() => { setRecon(null); setPlaceTick((n) => n + 1); }} />}
      {setView?.kind === "continuity" && <SetBuilder dir={dir} openSet={setView.id} openTab="continuity" onClose={() => setSetView(null)} />}
      {setView?.kind === "plan" && <DirectorCam dir={dir} initialSet={setView.id} onClose={() => setSetView(null)} />}
      {assist && <AssistSheet dir={dir} kind={assist.kind} id={assist.id} name={assist.name} proposal={assist.proposal} bible={b} onClose={() => setAssist(null)} onApplied={(v) => { setB(v); setAssist(null); setNote("Added what you chose. Everything else is as you had it."); }} />}
    </div>
  );
}

/** The world's rules, the philosophy that guides every shot, and the visual style. */
function RulesStyle({ b, onSave, onHelp, helping }: { b: BibleView; onSave: (d: Record<string, unknown>) => void; onHelp: () => void; helping: boolean }) {
  const [rules, setRules] = useState(b.rules);
  const [phil, setPhil] = useState(b.philosophy);
  const base = (({ principles: _p, ...rest }) => rest)(b.style);                       // the saved style without the principles, which are kept apart
  const [style, setStyle] = useState(base);
  const [fam, setFam] = useState(b.family);                                                                      // the kind of film: photorealistic, 3D, 2D, hybrid, crafts or art
  const [look, setLook] = useState(b.look);                                                                      // the exact look, one of the library
  const [genre, setGenre] = useState(b.genre);                                                                   // an optional genre feel layered on top
  const [princ, setPrinc] = useState<string[]>(b.principles_on);
  const [custom, setCustom] = useState(b.principles_custom);
  const sending = custom ? princ : null;
  const dirty = JSON.stringify([rules, phil, style, sending, look, genre]) !== JSON.stringify([b.rules, b.philosophy, base, b.principles_custom ? b.principles_on : null, b.look, b.genre]);
  const looks = b.families.find((f) => f.id === fam)?.looks ?? [];
  const picked = b.families.flatMap((f) => f.looks).find((l) => l.id === look);
  const toggle = (id: string) => { setCustom(true); setPrinc((p) => (p.includes(id) ? p.filter((x) => x !== id) : [...p, id])); };
  return (
    <div className="cw-rules">
      <div className="cw-helprow"><span className="dim">Stuck? Optional: let the writing helper suggest a visual style, the rules of the world and how the film is made, from your story. You choose what to use.</span>
        <button className="btn ghost sm" onClick={onHelp} disabled={helping}><I.Sparkle size={13} /> {helping ? "Writing…" : "Help me write this"}</button></div>
      <section>
        <h2>Visual style</h2>
        <p className="dim">The look affects characters, places, materials, light, camera and movement together, not just a phrase added to a prompt.</p>
        <div className="cw-fams" role="radiogroup" aria-label="Kind of film">
          {b.families.map((f) => <button key={f.id} role="radio" aria-checked={fam === f.id} className={`cw-fam fam-${f.id} ${fam === f.id ? "on" : ""}`} onClick={() => setFam(f.id)}><b>{f.name}</b><span>{f.blurb}</span></button>)}
        </div>
        {fam && <div className="cw-lanes" role="radiogroup" aria-label="Look">
          {looks.map((l) => <button key={l.id} role="radio" aria-checked={look === l.id} className={look === l.id ? "on" : ""} title={l.description} onClick={() => { setLook(l.id); if (!custom) setPrinc(b.principles.filter((p) => p.default).map((p) => p.id)); }}>{l.name}</button>)}
        </div>}
        {picked && <p className="cw-picked"><b>{picked.name}.</b> {picked.description} <span className="dim">Its look is written into every picture and video prompt, and kept strong against anything that pulls the other way.</span></p>}
        <div className="cw-genre"><span className="dim">Genre feel, optional, layered on top of the look</span>
          <div className="cw-lanes" role="radiogroup" aria-label="Genre feel">
            <button role="radio" aria-checked={!genre} className={!genre ? "on" : ""} onClick={() => setGenre("")}>None</button>
            {b.genres.map((g) => <button key={g.id} role="radio" aria-checked={genre === g.id} className={genre === g.id ? "on" : ""} title={g.description} onClick={() => setGenre(g.id)}>{g.name}</button>)}
          </div></div>
        <details className="cw-principles" open={fam !== "photoreal" && !!fam}>
          <summary>Animation principles <span className="dim">{custom ? `${princ.length} of 12 on` : "the style's own choice"}</span></summary>
          <p className="dim">The twelve principles the great animation studios work by. For each shot, the few that fit what happens in it are added to the prompt, so a jump gets anticipation and a flowing coat gets follow-through. Photorealistic films use only the ones that are also good acting and camera craft.</p>
          <div className="cw-pr">{b.principles.map((p) => <button key={p.id} className={`cw-prc ${princ.includes(p.id) ? "on" : ""} ${p.fits ? "" : "off"}`} aria-pressed={princ.includes(p.id)} onClick={() => toggle(p.id)} title={p.plain}>
            <span className="cw-prc-top"><PrincipleIcon id={p.id} /><b>{p.name}</b></span><span>{p.plain}</span></button>)}</div>
          {custom && <button className="link" onClick={() => { setCustom(false); setPrinc(b.principles.filter((p) => p.default).map((p) => p.id)); }}>Use the style's own choice</button>}
        </details>
        <label className="field"><span>What defines this look</span><textarea className="text-input" rows={2} value={style.traits} onChange={(e) => setStyle({ ...style, traits: e.target.value })} placeholder="Materials, textures, how things move" /></label>
        <label className="field"><span>References (one per line: a film, a painter, a link)</span><textarea className="text-input" rows={3} value={style.references.join("\n")}
          onChange={(e) => setStyle({ ...style, references: e.target.value.split("\n") })} placeholder="Describe the qualities you want, not a film to copy" /></label>
      </section>
      <section>
        <h2>World rules</h2>
        {RULES.map(([k, name, hint]) => <label key={k} className="field"><span>{name}</span><textarea className="text-input" rows={2} value={rules[k] ?? ""} placeholder={hint} onChange={(e) => setRules({ ...rules, [k]: e.target.value })} /></label>)}
      </section>
      <section>
        <h2>How the film is made</h2>
        <div className="cw-grid2">{PHILOSOPHY.map(([k, name]) => <label key={k} className="field"><span>{name}</span><textarea className="text-input" rows={2} value={phil[k] ?? ""} onChange={(e) => setPhil({ ...phil, [k]: e.target.value })} /></label>)}</div>
      </section>
      <div className="cw-save"><span className="dim">{dirty ? "Unsaved changes" : `Saved · revision ${b.rev}`}</span>
        <button className="btn primary" disabled={!dirty} onClick={() => onSave({ rules, philosophy: phil, style: { ...style, look, genre, references: style.references.map((r) => r.trim()).filter(Boolean), principles: sending } })}>Save</button></div>
    </div>
  );
}

/** One character, place or prop: its words, its related states, and its pictures. */
function Editor({ dir, kind, item, media, run, onHelp, helping, onOpenSet, onPlan, onCheck, onReconstruct, tick }: { onOpenSet: (id: string) => void; onPlan: (id: string) => void; onCheck: (id: string) => void; onReconstruct: () => void; tick: number; dir: string; kind: Kind; item: Entry; media: string[]; run: (fn: () => Promise<BibleView>) => Promise<BibleView | null>; apply: (v: BibleView) => void; onHelp: () => void; helping: boolean }) {
  const [draft, setDraft] = useState<Record<string, string>>({});
  const val = (k: string) => draft[k] ?? ((item as unknown as Record<string, string>)[k] ?? "");
  const spatial = (k: string) => draft[`sp:${k}`] ?? ((item as BibleEnvironment).spatial?.[k] ?? "");
  const commit = (k: string) => {
    if (draft[k] === undefined) return;
    void run(() => api.bible("upsert", dir, { kind, item: { id: item.id, [k]: draft[k] } })).then(() => setDraft(({ [k]: _x, ...rest }) => rest));
  };
  const commitSpatial = (k: string) => {
    const key = `sp:${k}`;
    if (draft[key] === undefined) return;
    void run(() => api.bible("upsert", dir, { kind, item: { id: item.id, spatial: { [k]: draft[key] } } })).then(() => setDraft(({ [key]: _x, ...rest }) => rest));
  };
  const field = (k: string, name: string, multi: boolean) => (
    <label className="field" key={k}><span>{name}</span>
      {multi ? <textarea className="text-input" rows={2} value={val(k)} onChange={(e) => setDraft({ ...draft, [k]: e.target.value })} onBlur={() => commit(k)} />
        : <input className="text-input" value={val(k)} onChange={(e) => setDraft({ ...draft, [k]: e.target.value })} onBlur={() => commit(k)} />}</label>);

  const addPicture = async () => {
    const f = await open({ multiple: true, filters: [{ name: "Pictures", extensions: ["png", "jpg", "jpeg", "webp"] }] });
    const files = typeof f === "string" ? [f] : Array.isArray(f) ? f : [];
    for (const file of files) await run(() => api.bible("add_media", dir, { kind, id: item.id, file, label: "Reference", media_kind: item.media.length ? "reference" : "master" }));
  };
  const replacePicture = async (path: string) => {
    const f = await open({ multiple: false, filters: [{ name: "Pictures", extensions: ["png", "jpg", "jpeg", "webp"] }] });
    if (typeof f === "string") await run(() => api.bible("replace_media", dir, { kind, id: item.id, path, file: f }));
  };
  const addState = async () => {
    const name = await askText("Name the state", kind === "character" ? "e.g. Age 8, Injured, In the red coat" : kind === "environment" ? "e.g. Night, Wrecked" : "e.g. Broken");
    if (name) await run(() => api.bible("add_state", dir, { kind, id: item.id, label: name }));
  };
  const remove = async () => { if (await ask(`Take “${item.name}” out of the Bible?\n\nThe Bible as it is now is kept in its history, and the pictures stay in the film folder.`, { ok: "Take out" })) await run(() => api.bible("remove", dir, { kind, id: item.id })); };

  return (
    <div className="cw-edit">
      <div className="cw-title"><input className="cw-name" value={val("name")} aria-label="Name" onChange={(e) => setDraft({ ...draft, name: e.target.value })} onBlur={() => commit("name")} />
        <span className="dim">{item.scenes.length ? `In scene${item.scenes.length === 1 ? "" : "s"} ${item.scenes.join(", ")}` : item.source === "story" ? "From the story" : "Added by you"}</span>
        <div style={{ flex: 1 }} /><button className="btn ghost sm" onClick={onHelp} disabled={helping} title="Optional: the writing helper suggests details from your story. You choose what to use."><I.Sparkle size={13} /> {helping ? "Writing…" : "Help me write"}</button>
        <button className="link" onClick={remove}>Take out</button></div>

      <section className="cw-pics">
        <h3>Pictures</h3>
        <div className="cw-media">
          {item.media.map((m) => (
            <figure key={m.path}><img src={api.mediaUrl(`${dir}/${m.path}`)} alt={m.label} />
              <figcaption><select className="cw-pickind" aria-label="What this picture shows" value={m.kind} onChange={(e) => void run(() => api.bible("update_media", dir, { kind, id: item.id, path: m.path, media_kind: e.target.value }))}>
                  {media.map((k) => <option key={k} value={k}>{k === "master" ? "Master sheet" : k}</option>)}</select>
                <button className="link" onClick={() => void replacePicture(m.path)} title="Choose another picture to take its place">replace</button>
                <button className="link" onClick={() => run(() => api.bible("remove_media", dir, { kind, id: item.id, path: m.path }))}>remove</button></figcaption></figure>))}
          <button className="cw-addpic" onClick={addPicture}>+ Add pictures…</button>
        </div>
        {item.media.length === 0 && <p className="dim">{kind === "character" ? "Bring your own artwork or reference sheets: front, three-quarter, side, back, expressions. The first one is the master." : "Bring a picture so every shot can match it."}</p>}
      </section>

      {kind === "environment" && <PlaceSet dir={dir} place={item.id} name={item.name} pictures={item.media.length} onOpenSet={onOpenSet} onPlan={onPlan} onCheck={onCheck} onReconstruct={onReconstruct} refresh={tick} />}
      {kind === "character" && <div className="cw-fields">{CHAR_FIELDS.map(([k, n, m]) => field(k, n, m))}</div>}
      {kind === "environment" && <>
        {field("description", "What it is", true)}{field("notes", "Notes", true)}
        <details className="cw-spatial" open={SPATIAL.some(([k]) => spatial(k))}><summary>Layout, so the place doesn't change between shots</summary>
          <div className="cw-grid2">{SPATIAL.map(([k, n]) => <label className="field" key={k}><span>{n}</span>
            <textarea className="text-input" rows={2} value={spatial(k)} onChange={(e) => setDraft({ ...draft, [`sp:${k}`]: e.target.value })} onBlur={() => commitSpatial(k)} /></label>)}</div></details></>}
      {kind === "prop" && field("notes", "Notes", true)}

      {kind === "character" && <section className="cw-wardrobe"><h3>Wardrobe</h3>
        {(item as BibleCharacter).wardrobe.length === 0 ? <p className="dim">No outfits yet.</p> : <ul>{(item as BibleCharacter).wardrobe.map((w) => <li key={w.id}><b>{w.name}</b> <span className="dim">{w.notes}</span></li>)}</ul>}
        <button className="btn ghost sm" onClick={async () => { const n = await askText("Name the outfit", "e.g. Red coat"); if (n) await run(() => api.bible("add_wardrobe", dir, { id: item.id, name: n })); }}>+ Add an outfit</button></section>}

      <section className="cw-states"><h3>States <span className="dim">the same {kind === "environment" ? "place" : kind} at another time or in another condition</span></h3>
        <ul>{item.states.map((s) => <li key={s.id}><b>{s.label}</b>{s.age && <span className="dim"> · age {s.age}</span>}{s.notes && <span className="dim"> · {s.notes}</span>}
          {item.states.length > 1 && <button className="link" onClick={() => run(() => api.bible("remove_state", dir, { kind, id: item.id, state: s.id }))}>remove</button>}</li>)}</ul>
        <button className="btn ghost sm" onClick={addState}>+ Add a state</button></section>
    </div>
  );
}
