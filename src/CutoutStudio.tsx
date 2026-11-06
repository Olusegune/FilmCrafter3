import { useCallback, useEffect, useState } from "react";
import { open as openDialog } from "@tauri-apps/plugin-dialog";
import { revealItemInDir } from "@tauri-apps/plugin-opener";
import { Sheet } from "./Sheet";
import { api, errorText, type KeyParams, type KeyReport, type PlateReport, type VpComposition, type VpExport, type VpLayer, type VpPlatePrompt, type VpState } from "./api";

const KINDS: Record<string, string> = { plate: "Subject on a screen", background: "Background", foreground: "Foreground" };
const CHECKER = "repeating-conic-gradient(#3a3f47 0% 25%, #2a2e35 0% 50%) 50% / 16px 16px";
export const LAYER_DEFAULT: Omit<VpLayer, "cutout"> = { x: 0.5, y: 1, scale: 1, rotation: 0, flip: false, anchor: "feet", opacity: 1, match: 0, shadow: { strength: 0.4, blur: 8, squash: 0.25, spread: 1 } };

/** The key's report in plain sentences, worst first. */
export function keyWords(r: KeyReport): string[] {
  const out = [...r.notes];
  out.unshift(`${Math.round(r.subject * 100)}% kept as subject, ${Math.round(r.removed * 100)}% removed, ${Math.round(r.soft_edge * 100)}% soft edge.`);
  return out;
}

/** The plate's check in a sentence. */
export const plateWords = (p: PlateReport): string => `${p.usable ? "Usable" : "Not ready"}: ${p.screen} screen, ${Math.round(p.border_on_screen * 100)}% of the border is screen, unevenness ${p.spread.toFixed(3)}. ${p.notes.join(" ")}`;

const Num = ({ label, value, min, max, step, onChange }: { label: string; value: number; min: number; max: number; step: number; onChange: (v: number) => void }) => (
  <label className="field"><span>{label}: {value}</span><input type="range" min={min} max={max} step={step} value={value} aria-label={label} onChange={(e) => onChange(Number(e.target.value))} /></label>);

/**
 * Virtual production, part 1: cut a subject out of a green or blue screen and put it on another picture. Free and local; nothing is generated or sent. The keyer works on the colour of the screen only
 * (it does not know what a person is), so the plate is checked first and the result says what to look at. Cutouts are RGBA PNG files with transparency; nothing is deleted.
 */
export function CutoutStudio({ dir, onClose }: { dir: string; onClose: () => void }) {
  const [st, setSt] = useState<VpState | null>(null);
  const [tab, setTab] = useState<"pictures" | "cut" | "compose">("pictures");
  const [busy, setBusy] = useState("");
  const [err, setErr] = useState("");
  const [said, setSaid] = useState("");
  const [plate, setPlate] = useState("");
  const [check, setCheck] = useState<PlateReport | null>(null);
  const [p, setP] = useState<KeyParams | null>(null);
  const [result, setResult] = useState<{ id: string; report: KeyReport } | null>(null);
  const [words, setWords] = useState<VpPlatePrompt | null>(null);
  const [subject, setSubject] = useState("");
  const [screen, setScreen] = useState<"green" | "blue">("green");
  const [comp, setComp] = useState<VpComposition | null>(null);
  const [rendered, setRendered] = useState("");

  const load = useCallback(() => api.vp("get", dir).then((s) => { setSt(s); setP((cur) => cur ?? s.defaults); }).catch((e) => setErr(errorText(e))), [dir]);
  useEffect(() => { void load(); }, [load]);
  const go = async (label: string, f: () => Promise<void>) => { setErr(""); setSaid(""); setBusy(label); try { await f(); } catch (e) { setErr(errorText(e)); } finally { setBusy(""); } };
  const url = (rel: string) => `${api.mediaUrl(`${dir}/${rel}`)}?v=${st?.cutouts.length ?? 0}${rendered ? "" : ""}`;

  const bring = (kind: "plate" | "background" | "foreground") => go("import", async () => {
    const f = await openDialog({ multiple: false, filters: [{ name: "Pictures", extensions: ["png", "jpg", "jpeg", "webp", "bmp", "tif", "tiff"] }] });
    if (typeof f !== "string") return;
    const r = await api.vp("import", dir, { path: f, kind });
    setSt(r); if (kind === "plate") setPlate(r.id ?? ""); setSaid(r.already_there ? "That picture was already in the film." : "Brought in. The original is untouched.");
  });

  if (!st || !p) return <Sheet label="Cutout studio" className="vp-sheet" onDismiss={onClose}><h2>Cutout studio</h2>{err ? <p className="ss-warn" role="alert">{err}</p> : <p className="dim">Loading…</p>}</Sheet>;
  const plates = st.sources.filter((s) => s.kind === "plate");
  const backgrounds = st.sources.filter((s) => s.kind !== "plate");
  const chosen = plate || plates[0]?.id || "";
  const setC = (patch: Partial<VpComposition>) => comp && setComp({ ...comp, ...patch });
  const layer = (i: number, patch: Partial<VpLayer>) => comp && setComp({ ...comp, layers: comp.layers.map((l, k) => (k === i ? { ...l, ...patch } : l)) });

  return (
    <Sheet label="Cutout studio" className="vp-sheet" onDismiss={onClose}>
      <div className="vs-head"><h2>Cutout studio <span className="dim">green screen to a new background</span></h2><div style={{ flex: 1 }} /><button className="icon-btn" onClick={onClose} aria-label="Close">×</button></div>
      <p className="dim">Free and local: nothing is generated or sent. The keyer reads the colour of the screen only; it does not know what a person is, so it cannot cut a subject out of a picture with no screen.</p>
      <div className="cw-tabs" role="tablist">{([["pictures", "1 Pictures"], ["cut", "2 Cut out"], ["compose", "3 Compose"]] as const).map(([k, l]) => <button key={k} role="tab" aria-selected={tab === k} className={tab === k ? "on" : ""} onClick={() => setTab(k)}>{l}</button>)}</div>
      {err && <p className="ss-warn" role="alert">{err}</p>}
      {said && <p className="dim" role="status">{said}</p>}

      {tab === "pictures" && <section aria-label="Pictures">
        <div className="sm-row">{(["plate", "background", "foreground"] as const).map((k) => <button key={k} className="btn sm" disabled={!!busy} onClick={() => void bring(k)}>Bring in: {KINDS[k]}…</button>)}</div>
        {st.sources.length === 0 ? <p className="dim">Nothing yet. Bring in a plate (a subject in front of a green or blue screen) and a background.</p> :
          <ul className="ss-cues">{st.sources.map((s) => <li key={s.id} className="sm-row"><img alt="" src={url(s.file)} style={{ width: 56, height: 36, objectFit: "cover", borderRadius: 4 }} /><b>{s.name}</b> <span className="dim">{KINDS[s.kind]} · {s.width} × {s.height}</span></li>)}</ul>}
        <h4>Words for a clean plate <span className="dim">nothing is sent</span></h4>
        <div className="sm-row"><input className="text-input" placeholder="Who or what is on the screen" aria-label="Who or what" value={subject} maxLength={200} onChange={(e) => setSubject(e.target.value)} />
          <select className="text-input" aria-label="Screen colour" value={screen} onChange={(e) => setScreen(e.target.value as "green" | "blue")}><option value="green">Green screen</option><option value="blue">Blue screen</option></select>
          <button className="btn sm" disabled={!!busy || !subject.trim()} onClick={() => void go("words", async () => setWords(await api.vp<VpPlatePrompt>("plate_prompt", dir, { subject, screen })))}>Write the words</button></div>
        {words && <div className="ss-heard"><q>{words.prompt}</q>{words.notes.map((n) => <p key={n} className="dim">{n}</p>)}</div>}
      </section>}

      {tab === "cut" && <section aria-label="Cut out">
        {plates.length === 0 ? <p className="dim">Bring in a plate first (step 1).</p> : <>
          <div className="sm-row"><select className="text-input" aria-label="Plate" value={chosen} onChange={(e) => { setPlate(e.target.value); setCheck(null); }}>{plates.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}</select>
            <button className="btn sm ghost" disabled={!!busy} onClick={() => void go("check", async () => setCheck(await api.vp<PlateReport>("plate_check", dir, { source: chosen, screen: p.screen })))}>Check the screen</button></div>
          {check && <p className={check.usable ? "dim" : "ss-warn"} role="status" aria-label="Plate check">{plateWords(check)}</p>}
          <div className="sm-row"><label className="field"><span>Screen colour</span><select className="text-input" value={p.screen} onChange={(e) => setP({ ...p, screen: e.target.value as "green" | "blue" })}><option value="green">Green</option><option value="blue">Blue</option></select></label></div>
          <Num label="Similarity" value={p.similarity} min={0} max={0.4} step={0.01} onChange={(v) => setP({ ...p, similarity: v })} />
          <Num label="Edge softness (0 = from the picture)" value={p.softness ?? 0} min={0} max={0.5} step={0.01} onChange={(v) => setP({ ...p, softness: v === 0 ? null : v })} />
          <Num label="Shrink edge (px)" value={p.erode} min={0} max={12} step={1} onChange={(v) => setP({ ...p, erode: v })} />
          <Num label="Grow edge (px)" value={p.dilate} min={0} max={12} step={1} onChange={(v) => setP({ ...p, dilate: v })} />
          <Num label="Feather (px)" value={p.feather} min={0} max={20} step={0.5} onChange={(v) => setP({ ...p, feather: v })} />
          <Num label="Remove screen colour from the subject" value={p.despill} min={0} max={1} step={0.05} onChange={(v) => setP({ ...p, despill: v })} />
          <div className="sm-row"><label className="ov-check"><input type="checkbox" checked={p.fill_holes} onChange={(e) => setP({ ...p, fill_holes: e.target.checked })} /> Fill holes inside the subject</label>
            <label className="ov-check"><input type="checkbox" checked={p.decontaminate} onChange={(e) => setP({ ...p, decontaminate: e.target.checked })} /> Clean the colour of the edge</label></div>
          <div className="sm-row"><button className="btn" disabled={!!busy || !chosen} onClick={() => void go("key", async () => { const r = await api.vp("key", dir, { source: chosen, params: p, name: `${plates.find((s) => s.id === chosen)?.name ?? "Subject"} cutout` }); setSt(r); setResult({ id: r.id ?? "", report: r.report as KeyReport }); })}>{busy === "key" ? "Cutting out…" : "Cut out"}</button></div>
          {result && <div className="ss-heard" aria-label="Key result">{keyWords(result.report).map((n) => <p key={n} className={result.report.notes.includes(n) ? "ss-warn" : "dim"}>{n}</p>)}</div>}</>}
        <h4>Cutouts</h4>
        {st.cutouts.length === 0 ? <p className="dim">No cutouts yet.</p> : <ul className="ss-cues">{st.cutouts.map((c) => <li key={c.id} className="sm-row">
          <span style={{ width: 72, height: 54, background: CHECKER, borderRadius: 4, display: "inline-block" }}><img alt={c.name} src={url(c.rgba)} style={{ width: 72, height: 54, objectFit: "contain" }} /></span>
          <b>{c.name}</b> <span className="dim">{c.width} × {c.height} · {Math.round(c.report.subject * 100)}% subject</span>
          <button className="btn sm ghost" disabled={!!busy} aria-label={`Export ${c.name}`} onClick={() => void go("export", async () => { const r = await api.vp<VpExport>("export", dir, { id: c.id }); setSaid(r.has_alpha ? `Saved as a PNG with transparency in ${r.folder}.` : "Saved, but the PNG has no transparent pixels: check the key."); void Promise.resolve(revealItemInDir(r.folder)).catch(() => {}); })}>Export PNG</button>
          <button className="btn sm ghost" disabled={!!busy} aria-label={`Remove ${c.name}`} onClick={() => void go("remove", async () => setSt(await api.vp("cutout_remove", dir, { id: c.id })))}>Remove</button></li>)}</ul>}
      </section>}

      {tab === "compose" && <section aria-label="Compose">
        {st.cutouts.length === 0 ? <p className="dim">Make a cutout first (step 2).</p> : <>
          <div className="sm-row"><select className="text-input" aria-label="Saved compositions" value={comp?.id ?? ""} onChange={(e) => setComp(st.compositions.find((c) => c.id === e.target.value) ?? null)}><option value="">New composition</option>{st.compositions.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}</select>
            <button className="btn sm" onClick={() => setComp({ id: "", name: "Composition", background: backgrounds[0]?.id ?? null, size: [1280, 720], colour: [0.1, 0.1, 0.1], layers: [] })}>Start a new one</button></div>
          {comp && <>
            <div className="sm-row"><input className="text-input" aria-label="Composition name" value={comp.name} maxLength={60} onChange={(e) => setC({ name: e.target.value })} />
              <select className="text-input" aria-label="Background" value={comp.background ?? ""} onChange={(e) => setC({ background: e.target.value || null })}><option value="">Plain colour</option>{backgrounds.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}</select>
              <label>size <input className="text-input" type="number" aria-label="Width" value={comp.size[0]} style={{ width: 80 }} onChange={(e) => setC({ size: [Number(e.target.value), comp.size[1]] })} /> × <input className="text-input" type="number" aria-label="Height" value={comp.size[1]} style={{ width: 80 }} onChange={(e) => setC({ size: [comp.size[0], Number(e.target.value)] })} /></label></div>
            <ul className="ss-cues">{comp.layers.map((l, i) => <li key={i} className="sm-row" aria-label={`Layer ${i + 1}`}>
              <select className="text-input" aria-label={`Layer ${i + 1} cutout`} value={l.cutout} onChange={(e) => layer(i, { cutout: e.target.value })}>{st.cutouts.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}</select>
              <label>across <input className="text-input" type="number" step={0.05} aria-label={`Layer ${i + 1} across`} value={l.x} style={{ width: 70 }} onChange={(e) => layer(i, { x: Number(e.target.value) })} /></label>
              <label>down <input className="text-input" type="number" step={0.05} aria-label={`Layer ${i + 1} down`} value={l.y} style={{ width: 70 }} onChange={(e) => layer(i, { y: Number(e.target.value) })} /></label>
              <label>size <input className="text-input" type="number" step={0.1} aria-label={`Layer ${i + 1} size`} value={l.scale} style={{ width: 70 }} onChange={(e) => layer(i, { scale: Number(e.target.value) })} /></label>
              <label>turn <input className="text-input" type="number" step={5} aria-label={`Layer ${i + 1} turn`} value={l.rotation} style={{ width: 70 }} onChange={(e) => layer(i, { rotation: Number(e.target.value) })} /></label>
              <label className="ov-check"><input type="checkbox" checked={l.flip} aria-label={`Layer ${i + 1} flip`} onChange={(e) => layer(i, { flip: e.target.checked })} /> Flip</label>
              <label>shadow <input className="text-input" type="number" step={0.1} min={0} max={1} aria-label={`Layer ${i + 1} shadow`} value={l.shadow?.strength ?? 0} style={{ width: 70 }} onChange={(e) => layer(i, { shadow: { ...(l.shadow ?? LAYER_DEFAULT.shadow!), strength: Number(e.target.value) } })} /></label>
              <label>match colour <input className="text-input" type="number" step={0.1} min={0} max={1} aria-label={`Layer ${i + 1} match`} value={l.match} style={{ width: 70 }} onChange={(e) => layer(i, { match: Number(e.target.value) })} /></label>
              <button className="btn sm ghost" aria-label={`Remove layer ${i + 1}`} onClick={() => setC({ layers: comp.layers.filter((_, k) => k !== i) })}>Remove</button></li>)}</ul>
            <div className="sm-row"><button className="btn sm" disabled={comp.layers.length >= st.limits.layers} onClick={() => setC({ layers: [...comp.layers, { cutout: st.cutouts[0].id, ...LAYER_DEFAULT }] })}>Add a cutout</button>
              <button className="btn" disabled={!!busy} onClick={() => void go("render", async () => { const saved = await api.vp("compose_set", dir, { ...comp, id: comp.id || undefined }); const id = saved.id ?? comp.id; setSt(saved); setComp(saved.compositions.find((c) => c.id === id) ?? comp); const r = await api.vp("render", dir, { id }); setRendered(r.file ?? ""); setSt(r); setSaid(`Drawn: ${r.layers} layer${r.layers === 1 ? "" : "s"}${r.missing?.length ? `, ${r.missing.length} left out because its cutout was removed` : ""}.`); })}>{busy === "render" ? "Drawing…" : "Save and render"}</button></div>
            {rendered && <img alt="The rendered composition" src={`${api.mediaUrl(`${dir}/${rendered}`)}?v=${rendered}`} style={{ maxWidth: "100%", borderRadius: 6, marginTop: 8 }} />}</>}</>}
      </section>}
    </Sheet>
  );
}
