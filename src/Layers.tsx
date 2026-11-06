import { useCallback, useEffect, useRef, useState } from "react";
import { open } from "@tauri-apps/plugin-dialog";
import { api, errorText, type LayerStyle, type LayerTemplate, type Overlay } from "./api";
import { ask } from "./ask";
import { IntroCardSheet } from "./IntroCard";
import * as I from "./icons";
import ICONS from "./shapeIcons.json";
import { FontPicker } from "./FontPicker";
import { KeysEditor } from "./KeysEditor";

type IconSet = Record<string, { label: string; polys: number[][][] }>;
const ICON_SET = ICONS as IconSet;
const SHAPES: [string, string][] = [["rect", "Rectangle"], ["rounded", "Rounded box"], ["circle", "Circle"], ["line", "Line"]];

function IconGlyph({ name, size = 22 }: { name: string; size?: number }) {
  return <svg width={size} height={size} viewBox="0 0 1 1" aria-hidden>{(ICON_SET[name]?.polys ?? []).map((p, i) => <polygon key={i} points={p.map((q) => q.join(",")).join(" ")} fill="currentColor" />)}</svg>;
}


/** A slider that saves when you let go (each save is one engine call), while the number follows your hand. */
function Range({ min, max, step, value, onCommit }: { min: number; max: number; step: number; value: number; onCommit: (v: number) => void }) {
  const [v, setV] = useState(value);
  useEffect(() => setV(value), [value]);
  const done = () => v !== value && onCommit(v);
  return <input type="range" min={min} max={max} step={step} value={v} onChange={(e) => setV(Number(e.target.value))} onPointerUp={done} onKeyUp={done} onBlur={done} />;
}

const BLENDS: [string, string][] = [["normal", "Normal"], ["multiply", "Multiply (darker)"], ["screen", "Screen (lighter)"], ["overlay", "Overlay"], ["softlight", "Soft light"], ["hardlight", "Hard light"],
  ["darken", "Darken"], ["lighten", "Lighten"], ["add", "Add (brighter)"], ["difference", "Difference"]];
const MASKS: [string, string][] = [["none", "None"], ["ellipse", "Oval"], ["rounded", "Rounded box"], ["rect", "Rectangle"]];

/** How the layer mixes with the picture under it, a glow or blur, a shape that hides part of it, and (for a picture) a colour cut out of it. All free; the finished film does the same as the preview here. */
function MixPanel({ sel, call, dir }: { sel: Overlay; call: (action: "update", data: Record<string, unknown>) => void; dir: string }) {
  const set = (data: Record<string, unknown>) => call("update", { id: sel.id, ...data });
  const [found, setFound] = useState("");
  const find = async () => {                                          // looks at the edges of the picture or the clip's first frame; changes nothing until it has found one
    setFound("Looking…");
    try {
      const r = await api.overlays<{ found: boolean; kind?: string; color?: string; sure?: number; message?: string }>(dir, "key_suggest", { id: sel.id });
      if (r.found && r.color) { set({ key_color: r.color }); setFound(`Found a ${r.kind} screen. Its colour is set.`); } else setFound(r.message ?? "No screen found.");
    } catch (e) { setFound(errorText(e)); }
  };
  const solid = sel.kind !== "fill" && sel.kind !== "clip" && !sel.cover;
  return (
    <details className="ly-mix">
      <summary>Mix and effects{sel.blend || sel.glow || sel.blur || sel.mask || sel.key_color ? " (in use)" : ""}</summary>
      <label className="field"><span>Mix with the picture</span>
        <select className="text-input" value={sel.blend ?? "normal"} onChange={(e) => set({ blend: e.target.value })}>{BLENDS.map(([v, n]) => <option key={v} value={v}>{n}</option>)}</select></label>
      {solid && <>
        <div className="ly-two">
          <label className="field"><span>Glow</span><Range min={0} max={1} step={0.05} value={sel.glow ?? 0} onCommit={(v) => set({ glow: v })} /></label>
          <label className="field"><span>Glow colour</span><Colour value={sel.glow_color ?? "#ffffff"} onCommit={(v) => set({ glow_color: v })} /></label></div>
        <label className="field"><span>Blur</span><Range min={0} max={1} step={0.05} value={sel.blur ?? 0} onCommit={(v) => set({ blur: v })} /></label></>}
      {sel.kind !== "clip" && <label className="field"><span>Show only through a shape</span>
        <select className="text-input" value={sel.mask ?? "none"} onChange={(e) => set({ mask: e.target.value })}>{MASKS.map(([v, n]) => <option key={v} value={v}>{n}</option>)}</select></label>}
      {sel.mask && sel.kind !== "clip" && <>
        <div className="ly-two">
          <label className="field"><span>Shape size</span><Range min={0.05} max={1} step={0.05} value={sel.mask_size ?? 0.8} onCommit={(v) => set({ mask_size: v })} /></label>
          <label className="field"><span>Soft edge</span><Range min={0} max={1} step={0.05} value={sel.mask_feather ?? 0} onCommit={(v) => set({ mask_feather: v })} /></label></div>
        <label className="ly-check"><input type="checkbox" checked={!!sel.mask_invert} onChange={(e) => set({ mask_invert: e.target.checked })} /> Hide the inside instead (a vignette)</label></>}
      {(sel.kind === "image" || sel.kind === "clip") && <>
        <label className="ly-check"><input type="checkbox" checked={!!sel.key_color} onChange={(e) => set({ key_color: e.target.checked ? "#00ff00" : "" })} /> Cut out a colour (a green screen)</label>
        {sel.key_color && <>
          <label className="field"><span>Colour to remove</span><Colour value={sel.key_color} onCommit={(v) => set({ key_color: v })} /></label>
          <button type="button" className="btn small" onClick={() => void find()} title="Looks at the edges of the picture for a green or blue screen and sets its colour">Find the screen colour</button>
          {found && <p className="dim ly-mixnote" role="status">{found}</p>}
          <div className="ly-two">
            <label className="field"><span>How much of it</span><Range min={0} max={1} step={0.05} value={sel.key_tol ?? 0.35} onCommit={(v) => set({ key_tol: v })} /></label>
            <label className="field"><span>Soft edge</span><Range min={0} max={1} step={0.05} value={sel.key_soft ?? 0.15} onCommit={(v) => set({ key_soft: v })} /></label></div>
          <label className="field"><span>Take the colour off the edges</span><Range min={0} max={1} step={0.05} value={sel.key_spill ?? 0.6} onCommit={(v) => set({ key_spill: v })} /></label></>}</>}
      <p className="dim ly-mixnote">The player shows how a layer mixes. Glow, blur, shapes and cut-out colours are drawn when the film is made.</p>
    </details>
  );
}

/** A colour picker that saves when the picker is closed, not on every colour it passes through. */
function Colour({ value, onCommit }: { value: string; onCommit: (v: string) => void }) {
  const ref = useRef<HTMLInputElement>(null);
  const [v, setV] = useState(value);
  useEffect(() => setV(value), [value]);
  useEffect(() => {
    const el = ref.current;
    const f = () => onCommit(el!.value);
    el?.addEventListener("change", f);
    return () => el?.removeEventListener("change", f);
  });
  return <input ref={ref} type="color" value={v} onInput={(e) => setV((e.target as HTMLInputElement).value)} onChange={() => undefined} />;
}

const clock = (s: number) => `${Math.floor(s / 60)}:${(s % 60).toFixed(1).padStart(4, "0")}`;
const label = (o: Overlay) => o.name || o.text || o.file?.split("/").pop()
  || (o.kind === "fill" ? "Colour backdrop" : o.kind === "shape" ? SHAPES.find(([v]) => v === o.shape)?.[1] ?? "Shape" : o.kind === "icon" ? ICON_SET[o.icon ?? "star"]?.label ?? "Icon" : o.kind === "clip" ? "Video clip" : "Picture");
export const ANIMS: [string, string][] = [["fade", "Fade"], ["rise", "Rise"], ["drop", "Drop in"], ["slide_left", "Slide from the right"], ["slide_right", "Slide from the left"],
  ["zoom_in", "Zoom in and settle"], ["zoom_out", "Settle down"], ["pushin", "Slow push-in"], ["wipe", "Wipe in from the left"], ["typewriter", "Typewriter"],
  ["bounce", "Bounce in"], ["pop", "Pop in"], ["pulse", "Pulse to the beat"], ["accent", "Pulse on the strong hits"]];

/** What a layer is and how to get one on the timeline, in the order a person does it. */
function HowLayersWork({ onAddText, compact }: { onAddText?: () => void; compact?: boolean }) {
  return (
    <div className={`ly-guide ${compact ? "compact" : ""}`}>
      {!compact && <h4>Put something over your film</h4>}
      <ol>
        <li><b>Choose when.</b> Move the playhead (the vertical line) to where it should appear.</li>
        <li><b>Add it.</b> Press <i>+ Text</i>, <i>+ Picture</i> or <i>+ Shape or icon</i>. It shows for 4 seconds from the playhead.</li>
        <li><b>Find it.</b> It is the coloured bar in the <i>Layers</i> row above the shots on the timeline, and it is drawn on the player.</li>
        <li><b>Place it.</b> Drag the bar to move it, or drag its ends to make it longer or shorter. Drag the layer on the player to put it where you want it.</li>
      </ol>
      {onAddText && <button className="btn primary small" onClick={onAddText}>Add a title at the playhead</button>}
    </div>
  );
}

/**
 * Layers: everything drawn over the film (text, pictures, signs, colour backdrops) as a stack, top layer first. Show or hide a layer, change its order,
 * duplicate or remove it, and edit it here; the selected layer shows on the player where you can drag it into place. Drawn at export, so it is free.
 */
export function LayersPanel({ dir, selected, onSelect, onClose, time, onFocus, docked }: { dir: string; selected: string | null; onSelect: (id: string | null) => void; onClose: () => void; time: number; onFocus?: (layer: Overlay | null) => void; docked?: boolean }) {
  const [items, setItems] = useState<Overlay[] | null>(null);
  const [err, setErr] = useState("");
  const [card, setCard] = useState(false);
  const [menu, setMenu] = useState(false);
  const [styles, setStyles] = useState<LayerStyle[]>([]);
  const [naming, setNaming] = useState(false);
  const [templates, setTemplates] = useState<LayerTemplate[]>([]);
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [tplNaming, setTplNaming] = useState(false);
  const [hist, setHist] = useState({ can_undo: false, can_redo: false });
  const [note, setNote] = useState<{ text: string; at: number } | null>(null);        // what just happened and where to find it, until the next change
  const loadHist = useCallback(() => api.overlays<{ can_undo: boolean; can_redo: boolean }>(dir, "history").then((h) => setHist(h ?? { can_undo: false, can_redo: false })).catch(() => {}), [dir]);
  const load = useCallback(() => api.overlays(dir, "list").then((r) => { setItems(r ?? []); loadHist(); }).catch((e) => setErr(errorText(e))), [dir, loadHist]);
  // Undo and redo of the last change to the layers (buttons here, Ctrl+Z / Ctrl+Shift+Z / Ctrl+Y from the Studio while this panel is open)
  const step = useCallback(async (which: "undo" | "redo") => {
    setErr("");
    try { setItems((await api.overlays(dir, which)) ?? []); window.dispatchEvent(new Event("pf-overlays-changed")); loadHist(); } catch (e) { setErr(errorText(e)); }
  }, [dir, loadHist]);
  useEffect(() => {
    const on = (e: Event) => step((e as CustomEvent<"undo" | "redo">).detail);
    window.addEventListener("pf-layers-history", on);
    return () => window.removeEventListener("pf-layers-history", on);
  }, [step]);
  useEffect(() => { load(); window.addEventListener("pf-overlays-changed", load); return () => window.removeEventListener("pf-overlays-changed", load); }, [load]);

  const loadStyles = useCallback(() => api.layerKit(dir, "styles").then((r) => setStyles(r?.styles ?? [])).catch(() => setStyles([])), [dir]);
  useEffect(() => { loadStyles(); }, [loadStyles]);
  const loadTemplates = useCallback(() => api.layerKit<{ templates: LayerTemplate[] }>(dir, "templates").then((r) => setTemplates(r?.templates ?? [])).catch(() => setTemplates([])), [dir]);
  useEffect(() => { loadTemplates(); }, [loadTemplates]);
  const togglePick = (id: string) => setPicked((s) => { const n = new Set(s); if (n.has(id)) n.delete(id); else n.add(id); return n; });
  const saveTemplate = async (name: string) => {
    setErr("");
    try { const r = await api.layerKit<{ templates: LayerTemplate[] }>(dir, "template_save", { ids: [...picked], name }); setTemplates(r.templates); setTplNaming(false); setPicked(new Set()); }
    catch (e) { setErr(errorText(e)); }
  };
  const useTemplate = async (name: string) => {
    if (!name) return;
    setErr("");
    try {
      const r = await api.layerKit<{ layers: Overlay[]; group: string }>(dir, "template_apply", { name, at: Math.max(0, Math.floor(time * 10) / 10) });
      setItems(r.layers); changed(); onSelect(r.layers.find((o) => o.group === r.group)?.id ?? null);
    } catch (e) { setErr(errorText(e)); }
  };
  const changed = () => window.dispatchEvent(new Event("pf-overlays-changed"));
  const saveStyle = async (name: string) => {
    if (!selected) return;
    setErr("");
    try { const r = await api.layerKit(dir, "save", { id: selected, name }); setStyles(r.styles); setNaming(false); } catch (e) { setErr(errorText(e)); }
  };
  const useStyle = async (name: string) => {
    if (!selected || !name) return;
    setErr("");
    try { const r = await api.layerKit<{ layers: Overlay[]; font_missing: boolean }>(dir, "apply", { name, ids: [selected] }); setItems(r.layers); changed(); if (r.font_missing) setErr("That style's font is not available in this project, so the layer keeps its own font."); }
    catch (e) { setErr(errorText(e)); }
  };
  const call = async (action: "add" | "update" | "remove" | "reorder" | "duplicate", data: Record<string, unknown>) => {
    setErr("");
    try { setItems(await api.overlays(dir, action, data)); changed(); }
    catch (e) { setErr(errorText(e)); }
  };
  const added = async (data: Record<string, unknown>) => {
    setErr("");
    try {
      const r = await api.overlays(dir, "add", data); setItems(r); onSelect(r[r.length - 1]?.id ?? null); changed();
      const mine = r[r.length - 1], at = typeof data.start === "number" ? data.start : mine?.start ?? 0;
      setNote({ text: `Added “${mine ? label(mine) : "layer"}” at ${clock(at)}. It is the bar in the Layers row above the shots on the timeline.`, at });
    }
    catch (e) { setErr(errorText(e)); }
  };
  const from = () => Math.max(0, Math.floor(time * 10) / 10);
  const addText = () => added({ kind: "text", text: "Your text", y: 0.5, start: from(), end: from() + 4, anim: "rise" });
  const addClip = async () => {
    const f = await open({ filters: [{ name: "Video clip", extensions: ["mp4", "mov", "m4v", "webm", "mkv"] }] });
    if (typeof f === "string") await added({ video: f, y: 0.5, x: 0.5, width: 0.4, start: from(), anim: "fade" });
  };
  const addPicture = async () => {
    const f = await open({ filters: [{ name: "Picture or text sign", extensions: ["png", "jpg", "jpeg", "webp", "svg"] }] });
    if (typeof f === "string") await added({ image: f, y: 0.5, width: 0.3, start: from(), end: from() + 4, anim: "zoom_in" });
  };
  const addShape = (shape: string) => { setMenu(false); return added({ kind: "shape", shape, x: 0.5, y: 0.5, width: shape === "line" ? 0.4 : 0.25, height: shape === "line" ? 0.006 : 0.25, color: "#ffd166", start: from(), end: from() + 4, anim: "fade" }); };
  const addIcon = (icon: string) => { setMenu(false); return added({ kind: "icon", icon, x: 0.5, y: 0.5, width: 0.12, color: "#ffd166", start: from(), end: from() + 4, anim: "zoom_in" }); };
  const remove = async (o: Overlay) => {
    if (!await ask(`Remove the layer “${label(o)}”?`, { ok: "Remove", danger: true })) return;
    if (selected === o.id) onSelect(null);
    await call("remove", { id: o.id });
  };

  const list = [...(items ?? [])].reverse();                       // the last layer is drawn on top, so it is listed first
  const sel = items?.find((o) => o.id === selected) ?? null;
  useEffect(() => { onFocus?.(sel); }, [sel, onFocus]);          // the Studio draws the selected layer's timeline under the player
  const num = (v: string) => (v.trim() === "" ? null : Number(v));
  return (
    <aside className={`layers ${docked ? "docked" : "glass"}`} aria-label="Layers">
      <div className="ly-head"><I.Layers size={16} /> <b>Layers</b><div style={{ flex: 1 }} />
        <button className="btn small ghost" onClick={() => step("undo")} disabled={!hist.can_undo} title="Undo the last change to the layers (Ctrl+Z)" aria-label="Undo">Undo</button>
        <button className="btn small ghost" onClick={() => step("redo")} disabled={!hist.can_redo} title="Redo it (Ctrl+Shift+Z)" aria-label="Redo">Redo</button>
        <button className="icon-btn" onClick={onClose} aria-label="Close layers"><I.Close size={16} /></button></div>
      <p className="ly-lead">Things drawn over the film: titles, pictures, shapes. A new one starts at the <b>playhead</b> (now <b className="num" aria-label="Playhead time">{clock(time)}</b>) and lasts 4 seconds. Free: drawn when you export.</p>
      {items && items.length > 0 && <div className="ly-add">
        <button className="btn small" onClick={addText} title="Adds a title at the playhead for 4 seconds">+ Text</button>
        <button className="btn small" onClick={addPicture} title="Adds a picture at the playhead for 4 seconds">+ Picture…</button>
        <button className="btn small" onClick={addClip} title="Adds a video clip at the playhead, for as long as it runs (10 seconds at most to start with): a picture-in-picture, or a green-screen subject">+ Video clip…</button>
        <button className="btn small" onClick={() => setMenu((v) => !v)} aria-expanded={menu}>+ Shape or icon ▾</button></div>}
      {items && !items.length && <div className="ly-cards" role="group" aria-label="What to add">
        <button className="ly-card" onClick={addText}><b>Title or text</b><span>A title, a name, a caption.</span></button>
        <button className="ly-card" onClick={addPicture}><b>Picture</b><span>A logo, a photo, a sign.</span></button>
        <button className="ly-card" onClick={addClip}><b>Video clip</b><span>A small video in a corner, or a green-screen subject.</span></button>
        <button className="ly-card" onClick={() => setMenu((v) => !v)} aria-expanded={menu}><b>Shape or icon</b><span>A box, a line, an arrow, a star.</span></button></div>}
      <details className="ly-more-add"><summary>More ways to add</summary>
        <div className="ly-add">
          <button className="btn small ghost" onClick={() => setCard(true)}>Intro card…</button></div></details>
      {note && <div className="ly-note" role="status"><span>{note.text}</span>
        <button className="link" onClick={() => { window.dispatchEvent(new Event("pf-show-timeline")); window.dispatchEvent(new CustomEvent("pf-seek", { detail: note.at })); }}>Show it on the timeline</button></div>}
      {menu && <div className="ly-menu" role="menu">
        <div className="ly-shapes">{SHAPES.map(([v, n]) => <button key={v} className="btn small ghost" role="menuitem" onClick={() => addShape(v)}>{n}</button>)}</div>
        <div className="ly-icons">{Object.entries(ICON_SET).map(([k, v]) => <button key={k} className="ly-icon" role="menuitem" title={v.label} onClick={() => addIcon(k)}><IconGlyph name={k} /></button>)}</div></div>}
      <div className="ly-tpl">
        <select className="text-input" value="" aria-label="Add a template at the playhead" onChange={(e) => useTemplate(e.target.value)} disabled={!templates.length}>
          <option value="">{templates.length ? "Add a template at the playhead…" : "No templates yet (tick layers, then save them)"}</option>
          {templates.map((t) => <option key={t.name} value={t.name}>{t.name} · {t.layers} layers · {t.seconds.toFixed(1)} s</option>)}</select>
        {picked.size > 0 && (tplNaming
          ? <form className="ly-name" onSubmit={(e) => { e.preventDefault(); saveTemplate((e.currentTarget.elements.namedItem("tpl") as HTMLInputElement).value); }}>
              <input name="tpl" className="text-input" placeholder="Name this template" maxLength={60} autoFocus /><button className="btn small" type="submit">Save</button>
              <button className="btn small ghost" type="button" onClick={() => setTplNaming(false)}>Cancel</button></form>
          : <button className="btn small ghost" onClick={() => setTplNaming(true)} title="Keep the ticked layers together, with their timing relative to each other">Save {picked.size} ticked as a template…</button>)}
      </div>
      {err && <p className="error-text" role="alert">{err}</p>}
      {items && !items.length && <p className="ly-hint">Move the playhead to where it should appear, then choose what to add. It shows as a coloured bar in the <b>Layers</b> row above the shots, and on the player where you can drag it into place.</p>}
      {items && items.length > 0 && <details className="ly-help"><summary>How layers work</summary><HowLayersWork compact /></details>}
      <ul className="ly-list">
        {list.map((o, i) => (
          <li key={o.id} className={`ly-row ${o.id === selected ? "sel" : ""} ${o.enabled ? "" : "off"}`}>
            <div className="ly-line">
              <label title={o.enabled ? "Shown in the film" : "Hidden"}><input type="checkbox" aria-label={`Show ${label(o)} in the film`} checked={o.enabled} onChange={(e) => call("update", { id: o.id, enabled: e.target.checked })} /></label>
              <label title="Tick to keep with other layers as a template"><input type="checkbox" className="ly-pick" aria-label={`Keep ${label(o)} for a template`} checked={picked.has(o.id)} onChange={() => togglePick(o.id)} /></label>
              <button className="link ly-name" onClick={() => onSelect(o.id === selected ? null : o.id)}>{label(o)}</button>
              <span className="dim num" title={o.placed ? "When it shows in the film" : "It has no time in the film yet, so it is not on the timeline. Set a start and end below."}>{o.placed ? `${clock(o.start!)} – ${clock(o.end!)}` : "no time yet"}</span>
              <button className="icon-btn" title="Bring forward" disabled={i === 0} onClick={() => call("reorder", { id: o.id, to: "up" })}><span className="ly-arrow">▲</span></button>
              <button className="icon-btn" title="Send back" disabled={i === list.length - 1} onClick={() => call("reorder", { id: o.id, to: "down" })}><span className="ly-arrow">▼</span></button>
              <button className="icon-btn" title="Duplicate" onClick={() => call("duplicate", { id: o.id })}><I.Layers size={14} /></button>
              <button className="icon-btn" title="Remove" onClick={() => remove(o)}><I.Trash size={14} /></button>
            </div>
          </li>))}
      </ul>
      {sel && <div className="ly-edit" key={sel.id}>
        <b>{label(sel)}</b>
        <div className="ly-timing">
          <span className="ly-timing-head">When it shows</span>
          <div className="ly-two">
            <label className="field"><span>Start (s)</span><input className="text-input" inputMode="decimal" defaultValue={sel.start ?? ""} key={`s${sel.start}`} onBlur={(e) => call("update", { id: sel.id, start: num(e.target.value) })} /></label>
            <label className="field"><span>End (s)</span><input className="text-input" inputMode="decimal" defaultValue={sel.end ?? ""} key={`e${sel.end}`} onBlur={(e) => call("update", { id: sel.id, end: num(e.target.value) })} /></label></div>
          <div className="ly-timing-btns">
            <button className="btn small ghost" onClick={() => call("update", { id: sel.id, start: from() })} title="Make it start where the playhead is">Start at the playhead</button>
            <button className="btn small ghost" onClick={() => call("update", { id: sel.id, end: Math.max(from(), (sel.start ?? 0) + 0.1) })} title="Make it end where the playhead is">End at the playhead</button></div>
          <p className="dim">Or drag its bar on the timeline: the middle moves it, the ends trim it.</p>
        </div>
        <div className="ly-style">
          <select className="text-input" value="" aria-label="Apply a saved style" onChange={(e) => useStyle(e.target.value)} disabled={!styles.length}>
            <option value="">{styles.length ? "Apply a saved style…" : "No saved styles yet"}</option>{styles.map((s) => <option key={s.name} value={s.name}>{s.name}</option>)}</select>
          {naming
            ? <form className="ly-name" onSubmit={(e) => { e.preventDefault(); const v = (e.currentTarget.elements.namedItem("style") as HTMLInputElement).value; saveStyle(v); }}>
                <input name="style" className="text-input" placeholder="Name this style" maxLength={60} autoFocus /><button className="btn small" type="submit">Save</button>
                <button className="btn small ghost" type="button" onClick={() => setNaming(false)}>Cancel</button></form>
            : <button className="btn small ghost" onClick={() => setNaming(true)} title="Keep how this layer looks and moves, to use on any layer in any project">Save as a style…</button>}
        </div>
        <label className="field"><span>Name</span><input className="text-input" defaultValue={sel.name ?? ""} placeholder={sel.text || "Layer name"} maxLength={60}
          onBlur={(e) => e.target.value !== (sel.name ?? "") && call("update", { id: sel.id, name: e.target.value })} /></label>
        {sel.kind === "text" && <label className="field"><span>Text</span><textarea className="text-input" rows={2} maxLength={300} defaultValue={sel.text}
          onBlur={(e) => e.target.value !== sel.text && call("update", { id: sel.id, text: e.target.value })} /></label>}
        {sel.kind === "shape" && <>
          <label className="field"><span>Shape</span><select className="text-input" value={sel.shape ?? "rect"} onChange={(e) => call("update", { id: sel.id, shape: e.target.value })}>
            {SHAPES.map(([v, n]) => <option key={v} value={v}>{n}</option>)}</select></label>
          <div className="ly-two">
            <label className="field"><span>Fill</span><Colour value={sel.color} onCommit={(v) => call("update", { id: sel.id, color: v })} /></label>
            <label className="field"><span>Filled</span><input type="checkbox" checked={sel.filled !== false} onChange={(e) => call("update", { id: sel.id, filled: e.target.checked })} /></label></div>
          <div className="ly-two">
            <label className="field"><span>Outline</span><Colour value={sel.stroke ?? "#ffffff"} onCommit={(v) => call("update", { id: sel.id, stroke: v })} /></label>
            <label className="field"><span>Outline width</span><Range min={0} max={0.05} step={0.001} value={sel.stroke_w ?? 0} onCommit={(v) => call("update", { id: sel.id, stroke_w: v })} /></label></div>
          <div className="ly-two">
            <label className="field"><span>Width</span><Range min={0.02} max={1} step={0.01} value={sel.width} onCommit={(v) => call("update", { id: sel.id, width: v })} /></label>
            <label className="field"><span>Height</span><Range min={0.002} max={1} step={0.002} value={sel.height ?? 0.2} onCommit={(v) => call("update", { id: sel.id, height: v })} /></label></div>
          {sel.shape === "rounded" && <label className="field"><span>Corners</span><Range min={0} max={0.5} step={0.01} value={sel.radius ?? 0.2} onCommit={(v) => call("update", { id: sel.id, radius: v })} /></label>}</>}
        {sel.kind === "icon" && <>
          <label className="field"><span>Icon</span><select className="text-input" value={sel.icon ?? "star"} onChange={(e) => call("update", { id: sel.id, icon: e.target.value })}>
            {Object.entries(ICON_SET).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}</select></label>
          <div className="ly-two">
            <label className="field"><span>Colour</span><Colour value={sel.color} onCommit={(v) => call("update", { id: sel.id, color: v })} /></label>
            <label className="field"><span>Size</span><Range min={0.03} max={0.6} step={0.005} value={sel.width} onCommit={(v) => call("update", { id: sel.id, width: v })} /></label></div></>}
        {sel.kind === "clip" && <>
          <label className="field"><span>Width</span><Range min={0.05} max={1} step={0.01} value={sel.width} onCommit={(v) => call("update", { id: sel.id, width: v })} /></label>
          <label className="field"><span>Start the clip at (seconds into it{sel.src_dur ? `, of ${sel.src_dur.toFixed(1)}` : ""})</span>
            <input className="text-input" type="number" min={0} max={Math.max(0, (sel.src_dur ?? 86400) - 0.1)} step={0.1} defaultValue={sel.in_s ?? 0}
              onBlur={(e) => { const v = Math.max(0, Number(e.target.value) || 0); if (v !== (sel.in_s ?? 0)) call("update", { id: sel.id, in_s: v }); }} /></label>
          <label className="ly-check"><input type="checkbox" checked={!!sel.loop} onChange={(e) => call("update", { id: sel.id, loop: e.target.checked })} /> Play again from the start when it ends</label>
          <label className="field"><span>Opacity</span><Range min={0.05} max={1} step={0.05} value={sel.opacity ?? 1} onCommit={(v) => call("update", { id: sel.id, opacity: v })} /></label>
          <p className="dim ly-mixnote">The clip's own sound is not used. Its picture plays from the start point for as long as the layer is up.</p></>}
        {sel.kind !== "fill" && sel.kind !== "clip" && !sel.cover && <>
          <div className="ly-two">
            <label className="field"><span>Scale</span><Range min={0.1} max={4} step={0.05} value={sel.scale ?? 1} onCommit={(v) => call("update", { id: sel.id, scale: v })} /></label>
            <label className="field"><span>Rotate</span><Range min={-180} max={180} step={1} value={sel.rotation ?? 0} onCommit={(v) => call("update", { id: sel.id, rotation: v })} /></label></div>
          <label className="field"><span>Opacity</span><Range min={0.05} max={1} step={0.05} value={sel.opacity ?? 1} onCommit={(v) => call("update", { id: sel.id, opacity: v })} /></label></>}
        {(sel.kind === "text" || sel.kind === "shape" || sel.kind === "icon") && <div className="ly-paint">
          <label className="ly-check"><input type="checkbox" checked={!!sel.gradient} onChange={(e) => call("update", { id: sel.id, gradient: e.target.checked, ...(e.target.checked && !sel.color2 ? { color2: "#ff6b6b" } : {}) })} /> Gradient fill</label>
          {sel.gradient && <div className="ly-two">
            <label className="field"><span>Second colour</span><Colour value={sel.color2 ?? "#ff6b6b"} onCommit={(v) => call("update", { id: sel.id, color2: v })} /></label>
            <label className="field"><span>Angle</span><Range min={0} max={360} step={5} value={sel.angle ?? 180} onCommit={(v) => call("update", { id: sel.id, angle: v })} /></label></div>}</div>}
        {sel.kind === "text" && <>
          <FontPicker dir={dir} value={sel.font ?? ""} onChange={(id) => call("update", { id: sel.id, font: id })} />
          <div className="ly-two">
            <label className="field"><span>Outline</span><Colour value={sel.stroke ?? "#000000"} onCommit={(v) => call("update", { id: sel.id, stroke: v })} /></label>
            <label className="field"><span>Outline width</span><Range min={0} max={0.03} step={0.001} value={sel.stroke_w ?? 0} onCommit={(v) => call("update", { id: sel.id, stroke_w: v })} /></label></div></>}
        {(sel.kind === "text" || sel.kind === "image" || sel.kind === "svg") && !sel.cover &&
          <label className="ly-check"><input type="checkbox" checked={sel.shadow !== false} onChange={(e) => call("update", { id: sel.id, shadow: e.target.checked })} /> Soft shadow</label>}
        <MixPanel sel={sel} call={call} dir={dir} />
        {sel.kind !== "fill" && sel.kind !== "clip" && !sel.cover && <KeysEditor sel={sel} time={time} save={(keys) => call("update", { id: sel.id, keys })} />}
        {sel.kind !== "fill" && !sel.cover && !sel.keys?.length && <label className="field"><span>Movement</span>
          <select className="text-input" value={sel.anim ?? "fade"} onChange={(e) => call("update", { id: sel.id, anim: e.target.value })}>
            {ANIMS.map(([v, n]) => <option key={v} value={v}>{n}</option>)}</select></label>}
        {sel.kind === "text" && <div className="ly-two">
          <label className="field"><span>Size</span><Range min={0.02} max={0.3} step={0.005} value={sel.size} onCommit={(v) => call("update", { id: sel.id, size: v })} /></label>
          <label className="field"><span>Colour</span><Colour value={sel.color} onCommit={(v) => call("update", { id: sel.id, color: v })} /></label></div>}
        {(sel.kind === "image" || sel.kind === "svg") && !sel.cover && <label className="field"><span>Width</span>
          <Range min={0.05} max={1} step={0.01} value={sel.width} onCommit={(v) => call("update", { id: sel.id, width: v })} /></label>}
      </div>}
      {card && <IntroCardSheet dir={dir} onClose={() => setCard(false)} onChanged={() => { changed(); load(); }} />}
    </aside>
  );
}
