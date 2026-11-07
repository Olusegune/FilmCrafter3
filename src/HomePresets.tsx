import { useEffect, useRef, useState } from "react";
import { Sheet } from "./Sheet";
import * as I from "./icons";
import { say } from "./PresetLibrary";
import { ALL, TYPES, TYPE_LABEL, featured, find, presetAspect, stackedNames, type HomePreset } from "./presetShelf";

/** The picture of a preset; a preset whose picture is missing (or cannot load) shows its kind on a plain tile, so a card is never empty. */
export function PresetThumb({ p }: { p: HomePreset }) {
  const [bad, setBad] = useState(false);
  return p.thumbnail && !bad
    ? <img className="hm-thumb" src={`/${p.thumbnail}`} alt="" loading="lazy" onError={() => setBad(true)} />
    : <div className="hm-thumb hm-noimg" aria-hidden="true">{TYPE_LABEL[p.type] ?? p.type}</div>;
}

/** One preset as a card: the picture, the name, a line about it. It opens the preset's details, where the film is started. */
export function PresetCard({ p, onPick }: { p: HomePreset; onPick: (p: HomePreset) => void }) {
  return (
    <li className="hm-pcard">
      <button type="button" className="hm-pbtn" onClick={() => onPick(p)}>
        <PresetThumb p={p} />
        <span className="hm-pname">{p.name}</span>
        <span className="hm-pdesc">{p.description}</span>
      </button>
    </li>
  );
}

/** The featured presets on Home, with a way to all of them. */
export function FeaturedPresets({ onPick, onAll }: { onPick: (p: HomePreset) => void; onAll: () => void }) {
  return (
    <section className="hm-section" aria-labelledby="hm-feat-h">
      <div className="hm-shead"><h2 id="hm-feat-h">Explore creative presets</h2><button type="button" className="link" onClick={onAll}>View all presets ({ALL.length})</button></div>
      <ul className="hm-presets">{featured().map((p) => <PresetCard key={p.id} p={p} onPick={onPick} />)}</ul>
    </section>
  );
}

/** What choosing a preset does, said plainly, and the one button that starts a film with it. Nothing is made or charged here. */
export function PresetDetailsSheet({ p, onStart, onClose }: { p: HomePreset; onStart: (p: HomePreset) => void; onClose: () => void }) {
  const stacked = stackedNames(p);
  const sets = Object.entries(p.settings);
  return (
    <Sheet label={p.name} className="hm-details" onDismiss={onClose}>
      <div className="vs-head"><h2>{p.name} <span className="dim pd-sub">{TYPE_LABEL[p.type] ?? p.type}</span></h2><div style={{ flex: 1 }} />
        <button className="icon-btn" onClick={onClose} aria-label="Close"><I.Close size={18} /></button></div>
      <div className="hm-dbody">
        <PresetThumb p={p} />
        <div>
          <p className="hm-dlead">{p.description}</p>
          {p.use && <p className="dim">{p.use}</p>}
          {sets.length > 0 && <><h3 className="perf-h">It sets</h3>
            <ul className="hm-dlist">{sets.map(([k, v]) => <li key={k}><b>{k === "duration_hint_s" ? "Length" : k === "aspect" ? "Frame shape" : k.charAt(0).toUpperCase() + k.slice(1)}</b> {k === "aspect" ? String(v) : say(k, v)}</li>)}</ul></>}
          {stacked.length > 0 && <><h3 className="perf-h">It also stacks</h3><p>{stacked.join(", ")}</p></>}
          <p className="dim hm-dnote">Starting a film with a preset only sets up the film's look, acting, colour, editing and frame. Nothing is made, nothing is bought, and every change can be undone in Presets.</p>
        </div>
      </div>
      <div className="sheet-actions">
        <button className="btn ghost" onClick={onClose}>Back</button>
        <button className="btn primary" onClick={() => onStart(p)} autoFocus>Start a film with this preset{presetAspect(p) ? ` (${presetAspect(p)})` : ""}</button>
      </div>
    </Sheet>
  );
}

/** The question for someone new: what would you like to create? Each answer goes straight to where it starts; "Not now" just closes it. Asked once. */
export function WelcomeSheet({ onStory, onPreset, onAnimated, onOpen, onClose }: { onStory: () => void; onPreset: () => void; onAnimated: () => void; onOpen: () => void; onClose: () => void }) {
  const ways: [string, string, () => void][] = [
    ["A film from my story", "Bring a screenplay or write an idea. Your story is kept exactly as it is.", onStory],
    ["A short video using a preset", "Micro-dramas, shorts, explainers and more, set up for you.", onPreset],
    ["An animated film", "A character-centred animated short, with its look and acting set up.", onAnimated],
    ["Open an existing project", "Carry on with a film you already made.", onOpen]];
  return (
    <Sheet label="What would you like to create?" className="hm-welcome" onDismiss={onClose}>
      <div className="vs-head"><h2>What would you like to create?</h2><div style={{ flex: 1 }} />
        <button className="icon-btn" onClick={onClose} aria-label="Close"><I.Close size={18} /></button></div>
      <p className="sub">Choose the closest. You can do all of these later from Home, and nothing is made or charged by choosing.</p>
      <ul className="hm-ways">{ways.map(([name, what, go], i) => (
        <li key={name}><button type="button" className="hm-way" onClick={go} autoFocus={i === 0}><b>{name}</b><span>{what}</span></button></li>))}</ul>
      <div className="sheet-actions"><span className="dim">Ask again any time with <b>Help me choose</b> on Home.</span><button className="btn ghost" onClick={onClose}>Not now</button></div>
    </Sheet>
  );
}

/** Every preset, searchable and filtered by kind. Picking one opens its details. */
export function PresetGallerySheet({ onPick, onClose }: { onPick: (p: HomePreset) => void; onClose: () => void }) {
  const [q, setQ] = useState("");
  const [type, setType] = useState("all");
  const box = useRef<HTMLInputElement>(null);
  useEffect(() => { box.current?.focus(); }, []);
  const shown = find(ALL, q, type);
  return (
    <Sheet label="All presets" className="hm-gallery" onDismiss={onClose}>
      <div className="vs-head"><h2>Presets <span className="dim pd-sub">{ALL.length} ready-made</span></h2><div style={{ flex: 1 }} />
        <button className="icon-btn" onClick={onClose} aria-label="Close"><I.Close size={18} /></button></div>
      <label className="field"><span>Search</span><input ref={box} className="text-input" value={q} onChange={(e) => setQ(e.target.value)} placeholder="micro-drama, storybook, vertical…" /></label>
      <div className="hm-chips" role="group" aria-label="Kind of preset">
        {["all", ...TYPES].map((t) => <button key={t} type="button" className={`hm-chip ${type === t ? "on" : ""}`} aria-pressed={type === t} onClick={() => setType(t)}>{t === "all" ? "All" : TYPE_LABEL[t]}</button>)}
      </div>
      {shown.length === 0 ? <p className="dim" role="status">No preset matches “{q}”.</p>
        : <ul className="hm-presets" aria-label="Presets">{shown.map((p) => <PresetCard key={p.id} p={p} onPick={onPick} />)}</ul>}
    </Sheet>
  );
}
