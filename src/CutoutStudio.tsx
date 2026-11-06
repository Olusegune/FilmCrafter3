import { useCallback, useEffect, useState } from "react";
import { open as openDialog } from "@tauri-apps/plugin-dialog";
import { revealItemInDir } from "@tauri-apps/plugin-opener";
import { Sheet } from "./Sheet";
import { api, errorText, type KeyParams, type KeyReport, type PlateReport, type VpCaps, type VpClipExport, type VpComposition, type VpCutout, type VpExport, type VpKey, type VpLayer, type VpPlatePrompt, type VpSource, type VpState } from "./api";

const KINDS: Record<string, string> = { plate: "Subject on a screen", background: "Background", foreground: "Foreground" };
const CHECKER = "repeating-conic-gradient(#3a3f47 0% 25%, #2a2e35 0% 50%) 50% / 16px 16px";
export const LAYER_DEFAULT: Omit<VpLayer, "cutout"> = { x: 0.5, y: 1, scale: 1, rotation: 0, flip: false, anchor: "feet", opacity: 1, match: 0, start: 0, loop: false, keys: [], shadow: { strength: 0.4, blur: 8, squash: 0.25, spread: 1 } };

/** The key's report in plain sentences, worst first. */
export function keyWords(r: KeyReport): string[] {
  const out = [...r.notes];
  out.unshift(`${Math.round(r.subject * 100)}% kept as subject, ${Math.round(r.removed * 100)}% removed, ${Math.round(r.soft_edge * 100)}% soft edge.`);
  if (r.flicker_before !== undefined && r.flicker_after !== undefined && r.flicker_before > 0) out.push(r.flicker_after < r.flicker_before ? `Edge flicker from frame to frame: ${r.flicker_before.toFixed(4)} before smoothing, ${r.flicker_after.toFixed(4)} after.` : `Edge flicker from frame to frame: ${r.flicker_before.toFixed(4)}.`);
  return out;
}

/** The plate's check in a sentence. */
export const plateWords = (p: PlateReport): string => `${p.usable ? "Usable" : "Not ready"}: ${p.screen} screen, ${Math.round(p.border_on_screen * 100)}% of the border is screen, unevenness ${p.spread.toFixed(3)}. ${p.notes.join(" ")}`;

/** What a source is, in a line. */
export const sourceWords = (s: VpSource): string => `${s.clip ? "Clip" : "Picture"} · ${KINDS[s.kind]} · ${s.width} × ${s.height}${s.clip && s.seconds ? ` · ${s.seconds.toFixed(1)} s at ${s.fps} per second` : ""}`;

const Num = ({ label, value, min, max, step, onChange }: { label: string; value: number; min: number; max: number; step: number; onChange: (v: number) => void }) => (
  <label className="field"><span>{label}: {value}</span><input type="range" min={min} max={max} step={step} value={value} aria-label={label} onChange={(e) => onChange(Number(e.target.value))} /></label>);

const PIC = { name: "Pictures", extensions: ["png", "jpg", "jpeg", "webp", "bmp", "tif", "tiff"] };
const VID = { name: "Videos", extensions: ["mp4", "mov", "webm", "mkv", "avi", "m4v"] };

/**
 * Virtual production: cut a subject (a picture or a clip) out of a green or blue screen and put it on another picture or clip, with cutouts that move. Free and local; nothing is generated or sent. The keyer
 * works on the colour of the screen only (it does not know what a person is), so the plate is checked first and the result says what to look at. Cutouts are PNG files with transparency; nothing is deleted.
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
  const [temporal, setTemporal] = useState(0.5);
  const [result, setResult] = useState<{ id: string; report: KeyReport } | null>(null);
  const [words, setWords] = useState<VpPlatePrompt | null>(null);
  const [subject, setSubject] = useState("");
  const [screen, setScreen] = useState<"green" | "blue">("green");
  const [comp, setComp] = useState<VpComposition | null>(null);
  const [rendered, setRendered] = useState("");
  const [video, setVideo] = useState("");
  const [vfps, setVfps] = useState(24);
  const [vsecs, setVsecs] = useState(0);
  const [at, setAt] = useState(0);
  const [caps, setCaps] = useState<VpCaps | null>(null);
  const [prog, setProg] = useState<{ stage: string; p: number } | null>(null);

  const load = useCallback(() => api.vp("get", dir).then((s) => { setSt(s); setP((cur) => cur ?? s.defaults); }).catch((e) => setErr(errorText(e))), [dir]);
  useEffect(() => { void load(); api.vpVideo<VpCaps>("capabilities", dir).then(setCaps).catch(() => {}); }, [load, dir]);
  useEffect(() => {
    let un: (() => void) | undefined;
    Promise.resolve(api.onEngine((e) => { if (e.task === "vpvideo" && e.event === "progress") setProg({ stage: String(e.stage ?? ""), p: Number(e.progress ?? 0) }); })).then((f) => { un = f; }).catch(() => {});
    return () => { un?.(); };
  }, []);
  const go = async (label: string, f: () => Promise<void>) => { setErr(""); setSaid(""); setBusy(label); setProg(null); try { await f(); } catch (e) { setErr(errorText(e)); } finally { setBusy(""); setProg(null); } };
  const url = (rel: string) => `${api.mediaUrl(`${dir}/${rel}`)}?v=${st?.cutouts.length ?? 0}`;

  const bring = (kind: "plate" | "background" | "foreground", clip = false) => go("import", async () => {
    const f = await openDialog({ multiple: false, filters: [clip ? VID : PIC] });
    if (typeof f !== "string") return;
    const r = clip ? await api.vpVideo("import_clip", dir, { path: f, kind }) : await api.vp("import", dir, { path: f, kind });
    setSt(r); if (kind === "plate") setPlate(r.id ?? ""); setSaid(r.already_there ? "That one was already in the film." : "Brought in. The original is untouched.");
  });

  if (!st || !p) return <Sheet label="Cutout studio" className="vp-sheet" onDismiss={onClose}><h2>Cutout studio</h2>{err ? <p className="ss-warn" role="alert">{err}</p> : <p className="dim">Loading…</p>}</Sheet>;
  const plates = st.sources.filter((s) => s.kind === "plate");
  const backgrounds = st.sources.filter((s) => s.kind !== "plate");
  const chosen = plate || plates[0]?.id || "";
  const chosenSrc = plates.find((s) => s.id === chosen);
  const isClip = !!chosenSrc?.clip;
  const setC = (patch: Partial<VpComposition>) => comp && setComp({ ...comp, ...patch });
  const layer = (i: number, patch: Partial<VpLayer>) => comp && setComp({ ...comp, layers: comp.layers.map((l, k) => (k === i ? { ...l, ...patch } : l)) });
  const cutById = (id: string): VpCutout | undefined => st.cutouts.find((c) => c.id === id);
  const bar = prog && busy ? <div className="dim" role="progressbar" aria-valuenow={Math.round(prog.p * 100)} aria-valuemin={0} aria-valuemax={100} aria-label="Progress">{prog.stage} {Math.round(prog.p * 100)}%</div> : null;
  const stop = busy === "key" || busy === "video" ? <button className="btn sm ghost" onClick={() => void api.vpVideo("cancel", dir).catch(() => {})}>Stop</button> : null;

  const keysOf = (i: number): VpKey[] => comp?.layers[i].keys ?? [];
  const setKey = (i: number, k: number, patch: Partial<VpKey>) => layer(i, { keys: keysOf(i).map((x, n) => (n === k ? { ...x, ...patch } : x)) });

  return (
    <Sheet label="Cutout studio" className="vp-sheet" onDismiss={onClose}>
      <div className="vs-head"><h2>Cutout studio <span className="dim">green screen to a new background</span></h2><div style={{ flex: 1 }} /><button className="icon-btn" onClick={onClose} aria-label="Close">×</button></div>
      <p className="dim">Free and local: nothing is generated or sent. The keyer reads the colour of the screen only; it does not know what a person is, so it cannot cut a subject out of a picture or clip with no screen.</p>
      <div className="cw-tabs" role="tablist">{([["pictures", "1 Pictures and clips"], ["cut", "2 Cut out"], ["compose", "3 Compose"]] as const).map(([k, l]) => <button key={k} role="tab" aria-selected={tab === k} className={tab === k ? "on" : ""} onClick={() => setTab(k)}>{l}</button>)}</div>
      {err && <p className="ss-warn" role="alert">{err}</p>}
      {said && <p className="dim" role="status">{said}</p>}
      {bar}

      {tab === "pictures" && <section aria-label="Pictures">
        <div className="sm-row">{(["plate", "background", "foreground"] as const).map((k) => <button key={k} className="btn sm" disabled={!!busy} onClick={() => void bring(k)}>Bring in: {KINDS[k]}…</button>)}</div>
        <div className="sm-row"><button className="btn sm" disabled={!!busy} onClick={() => void bring("plate", true)}>Bring in a clip: subject on a screen…</button>
          <button className="btn sm" disabled={!!busy} onClick={() => void bring("background", true)}>Bring in a clip: background…</button><span className="dim">Up to 30 seconds.</span></div>
        {st.sources.length === 0 ? <p className="dim">Nothing yet. Bring in a plate (a subject in front of a green or blue screen) and a background.</p> :
          <ul className="ss-cues">{st.sources.map((s) => <li key={s.id} className="sm-row">{s.clip ? <span style={{ width: 56, height: 36, background: CHECKER, borderRadius: 4, display: "inline-block" }} aria-hidden /> : <img alt="" src={url(s.file)} style={{ width: 56, height: 36, objectFit: "cover", borderRadius: 4 }} />}<b>{s.name}</b> <span className="dim">{sourceWords(s)}</span></li>)}</ul>}
        <h4>Words for a clean plate <span className="dim">nothing is sent</span></h4>
        <div className="sm-row"><input className="text-input" placeholder="Who or what is on the screen" aria-label="Who or what" value={subject} maxLength={200} onChange={(e) => setSubject(e.target.value)} />
          <select className="text-input" aria-label="Screen colour" value={screen} onChange={(e) => setScreen(e.target.value as "green" | "blue")}><option value="green">Green screen</option><option value="blue">Blue screen</option></select>
          <button className="btn sm" disabled={!!busy || !subject.trim()} onClick={() => void go("words", async () => setWords(await api.vp<VpPlatePrompt>("plate_prompt", dir, { subject, screen })))}>Write the words</button></div>
        {words && <div className="ss-heard"><q>{words.prompt}</q>{words.notes.map((n) => <p key={n} className="dim">{n}</p>)}</div>}
      </section>}

      {tab === "cut" && <section aria-label="Cut out">
        {plates.length === 0 ? <p className="dim">Bring in a plate first (step 1).</p> : <>
          <div className="sm-row"><select className="text-input" aria-label="Plate" value={chosen} onChange={(e) => { setPlate(e.target.value); setCheck(null); }}>{plates.map((s) => <option key={s.id} value={s.id}>{s.clip ? "Clip: " : ""}{s.name}</option>)}</select>
            {!isClip && <button className="btn sm ghost" disabled={!!busy} onClick={() => void go("check", async () => setCheck(await api.vp<PlateReport>("plate_check", dir, { source: chosen, screen: p.screen })))}>Check the screen</button>}</div>
          {check && <p className={check.usable ? "dim" : "ss-warn"} role="status" aria-label="Plate check">{plateWords(check)}</p>}
          <div className="sm-row"><label className="field"><span>Screen colour</span><select className="text-input" value={p.screen} onChange={(e) => setP({ ...p, screen: e.target.value as "green" | "blue" })}><option value="green">Green</option><option value="blue">Blue</option></select></label></div>
          <Num label="Similarity" value={p.similarity} min={0} max={0.4} step={0.01} onChange={(v) => setP({ ...p, similarity: v })} />
          <Num label="Edge softness (0 = from the picture)" value={p.softness ?? 0} min={0} max={0.5} step={0.01} onChange={(v) => setP({ ...p, softness: v === 0 ? null : v })} />
          <Num label="Shrink edge (px)" value={p.erode} min={0} max={12} step={1} onChange={(v) => setP({ ...p, erode: v })} />
          <Num label="Grow edge (px)" value={p.dilate} min={0} max={12} step={1} onChange={(v) => setP({ ...p, dilate: v })} />
          <Num label="Feather (px)" value={p.feather} min={0} max={20} step={0.5} onChange={(v) => setP({ ...p, feather: v })} />
          <Num label="Remove screen colour from the subject" value={p.despill} min={0} max={1} step={0.05} onChange={(v) => setP({ ...p, despill: v })} />
          {isClip && <Num label="Calm the edge between frames" value={temporal} min={0} max={1} step={0.05} onChange={setTemporal} />}
          <div className="sm-row"><label className="ov-check"><input type="checkbox" checked={p.fill_holes} onChange={(e) => setP({ ...p, fill_holes: e.target.checked })} /> Fill holes inside the subject</label>
            <label className="ov-check"><input type="checkbox" checked={p.decontaminate} onChange={(e) => setP({ ...p, decontaminate: e.target.checked })} /> Clean the colour of the edge</label></div>
          <div className="sm-row"><button className="btn" disabled={!!busy || !chosen} onClick={() => void go("key", async () => {
            const nm = `${chosenSrc?.name ?? "Subject"} cutout`;
            const r = isClip ? await api.vpVideo("key_clip", dir, { source: chosen, params: p, temporal, name: nm }) : await api.vp("key", dir, { source: chosen, params: p, name: nm });
            setSt(r); setResult({ id: r.id ?? "", report: r.report as KeyReport });
          })}>{busy === "key" ? (isClip ? "Cutting out the clip…" : "Cutting out…") : isClip ? "Cut out the clip" : "Cut out"}</button>{stop}</div>
          {result && <div className="ss-heard" aria-label="Key result">{keyWords(result.report).map((n) => <p key={n} className={result.report.notes.includes(n) ? "ss-warn" : "dim"}>{n}</p>)}</div>}</>}
        <h4>Cutouts</h4>
        {st.cutouts.length === 0 ? <p className="dim">No cutouts yet.</p> : <ul className="ss-cues">{st.cutouts.map((c) => <li key={c.id} className="sm-row">
          <span style={{ width: 72, height: 54, background: CHECKER, borderRadius: 4, display: "inline-block" }}><img alt={c.name} src={url(c.rgba)} style={{ width: 72, height: 54, objectFit: "contain" }} /></span>
          <b>{c.name}</b> <span className="dim">{c.kind === "clip" ? `Clip · ${c.frames} frames at ${c.fps} per second` : `${c.width} × ${c.height}`} · {Math.round(c.report.subject * 100)}% subject</span>
          {c.kind === "clip" ? <>
            <button className="btn sm ghost" disabled={!!busy} aria-label={`Export ${c.name} as a PNG sequence`} onClick={() => void go("export", async () => { const r = await api.vpVideo<VpClipExport>("export_clip", dir, { id: c.id, format: "png" }); setSaid(`Saved ${r.frames} PNG frames with transparency in ${r.path}.`); void Promise.resolve(revealItemInDir(r.path)).catch(() => {}); })}>PNG sequence</button>
            {(["prores4444", "webm"] as const).map((f) => <button key={f} className="btn sm ghost" disabled={!!busy || (caps ? !caps[f] : false)} title={caps && !caps[f] ? "This computer's video tool cannot make it." : undefined} aria-label={`Export ${c.name} as ${f === "webm" ? "WebM" : "ProRes 4444"}`}
              onClick={() => void go("export", async () => { const r = await api.vpVideo<VpClipExport>("export_clip", dir, { id: c.id, format: f }); setSaid(r.has_alpha ? `Saved with transparency (read back and checked): ${r.path}` : `Saved, but NO transparency was found in the file. Use the PNG sequence. ${r.path}`); void Promise.resolve(revealItemInDir(r.path)).catch(() => {}); })}>{f === "webm" ? "WebM (alpha)" : "ProRes 4444"}</button>)}</> :
            <button className="btn sm ghost" disabled={!!busy} aria-label={`Export ${c.name}`} onClick={() => void go("export", async () => { const r = await api.vp<VpExport>("export", dir, { id: c.id }); setSaid(r.has_alpha ? `Saved as a PNG with transparency in ${r.folder}.` : "Saved, but the PNG has no transparent pixels: check the key."); void Promise.resolve(revealItemInDir(r.folder)).catch(() => {}); })}>Export PNG</button>}
          <button className="btn sm ghost" disabled={!!busy} aria-label={`Remove ${c.name}`} onClick={() => void go("remove", async () => setSt(await api.vp("cutout_remove", dir, { id: c.id })))}>Remove</button></li>)}</ul>}
        {caps && <p className="dim sm-note">{caps.note}</p>}
      </section>}

      {tab === "compose" && <section aria-label="Compose">
        {st.cutouts.length === 0 ? <p className="dim">Make a cutout first (step 2).</p> : <>
          <div className="sm-row"><select className="text-input" aria-label="Saved compositions" value={comp?.id ?? ""} onChange={(e) => setComp(st.compositions.find((c) => c.id === e.target.value) ?? null)}><option value="">New composition</option>{st.compositions.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}</select>
            <button className="btn sm" onClick={() => setComp({ id: "", name: "Composition", background: backgrounds[0]?.id ?? null, size: [1280, 720], colour: [0.1, 0.1, 0.1], layers: [] })}>Start a new one</button></div>
          {comp && <>
            <div className="sm-row"><input className="text-input" aria-label="Composition name" value={comp.name} maxLength={60} onChange={(e) => setC({ name: e.target.value })} />
              <select className="text-input" aria-label="Background" value={comp.background ?? ""} onChange={(e) => setC({ background: e.target.value || null })}><option value="">Plain colour</option>{backgrounds.map((s) => <option key={s.id} value={s.id}>{s.clip ? "Clip: " : ""}{s.name}</option>)}</select>
              <label>size <input className="text-input" type="number" aria-label="Width" value={comp.size[0]} style={{ width: 80 }} onChange={(e) => setC({ size: [Number(e.target.value), comp.size[1]] })} /> × <input className="text-input" type="number" aria-label="Height" value={comp.size[1]} style={{ width: 80 }} onChange={(e) => setC({ size: [comp.size[0], Number(e.target.value)] })} /></label></div>
            <ul className="ss-cues">{comp.layers.map((l, i) => { const c = cutById(l.cutout); return <li key={i} aria-label={`Layer ${i + 1}`}><div className="sm-row">
              <select className="text-input" aria-label={`Layer ${i + 1} cutout`} value={l.cutout} onChange={(e) => layer(i, { cutout: e.target.value })}>{st.cutouts.map((x) => <option key={x.id} value={x.id}>{x.kind === "clip" ? "Clip: " : ""}{x.name}</option>)}</select>
              <label>across <input className="text-input" type="number" step={0.05} aria-label={`Layer ${i + 1} across`} value={l.x} style={{ width: 70 }} onChange={(e) => layer(i, { x: Number(e.target.value) })} /></label>
              <label>down <input className="text-input" type="number" step={0.05} aria-label={`Layer ${i + 1} down`} value={l.y} style={{ width: 70 }} onChange={(e) => layer(i, { y: Number(e.target.value) })} /></label>
              <label>size <input className="text-input" type="number" step={0.1} aria-label={`Layer ${i + 1} size`} value={l.scale} style={{ width: 70 }} onChange={(e) => layer(i, { scale: Number(e.target.value) })} /></label>
              <label>turn <input className="text-input" type="number" step={5} aria-label={`Layer ${i + 1} turn`} value={l.rotation} style={{ width: 70 }} onChange={(e) => layer(i, { rotation: Number(e.target.value) })} /></label>
              <label className="ov-check"><input type="checkbox" checked={l.flip} aria-label={`Layer ${i + 1} flip`} onChange={(e) => layer(i, { flip: e.target.checked })} /> Flip</label>
              <label>shadow <input className="text-input" type="number" step={0.1} min={0} max={1} aria-label={`Layer ${i + 1} shadow`} value={l.shadow?.strength ?? 0} style={{ width: 70 }} onChange={(e) => layer(i, { shadow: { ...(l.shadow ?? LAYER_DEFAULT.shadow!), strength: Number(e.target.value) } })} /></label>
              <label>match colour <input className="text-input" type="number" step={0.1} min={0} max={1} aria-label={`Layer ${i + 1} match`} value={l.match} style={{ width: 70 }} onChange={(e) => layer(i, { match: Number(e.target.value) })} /></label>
              <button className="btn sm ghost" aria-label={`Remove layer ${i + 1}`} onClick={() => setC({ layers: comp.layers.filter((_, k) => k !== i) })}>Remove</button></div>
              <div className="sm-row"><label>starts at <input className="text-input" type="number" step={0.25} min={0} aria-label={`Layer ${i + 1} starts at`} value={l.start ?? 0} style={{ width: 70 }} onChange={(e) => layer(i, { start: Number(e.target.value) })} /> s</label>
                {c?.kind === "clip" && <label className="ov-check"><input type="checkbox" checked={!!l.loop} aria-label={`Layer ${i + 1} loop`} onChange={(e) => layer(i, { loop: e.target.checked })} /> Repeat the clip</label>}
                <button className="btn sm ghost" aria-label={`Add a keyframe to layer ${i + 1}`} onClick={() => layer(i, { keys: [...keysOf(i), { t: keysOf(i).length ? keysOf(i)[keysOf(i).length - 1].t + 1 : 0, ease: "linear", x: l.x, y: l.y, scale: l.scale, rotation: l.rotation, opacity: 1 }] })}>Add a keyframe</button>
                <span className="dim">A keyframe says where it is at that second; between keyframes it moves.</span></div>
              {keysOf(i).map((k, n) => <div key={n} className="sm-row" aria-label={`Layer ${i + 1} keyframe ${n + 1}`}>
                <label>at <input className="text-input" type="number" step={0.25} min={0} aria-label={`Keyframe ${n + 1} time`} value={k.t} style={{ width: 64 }} onChange={(e) => setKey(i, n, { t: Number(e.target.value) })} /> s</label>
                <label>across <input className="text-input" type="number" step={0.05} aria-label={`Keyframe ${n + 1} across`} value={k.x ?? l.x} style={{ width: 64 }} onChange={(e) => setKey(i, n, { x: Number(e.target.value) })} /></label>
                <label>down <input className="text-input" type="number" step={0.05} aria-label={`Keyframe ${n + 1} down`} value={k.y ?? l.y} style={{ width: 64 }} onChange={(e) => setKey(i, n, { y: Number(e.target.value) })} /></label>
                <label>size <input className="text-input" type="number" step={0.1} aria-label={`Keyframe ${n + 1} size`} value={k.scale ?? l.scale} style={{ width: 64 }} onChange={(e) => setKey(i, n, { scale: Number(e.target.value) })} /></label>
                <label>opacity <input className="text-input" type="number" step={0.1} min={0} max={1} aria-label={`Keyframe ${n + 1} opacity`} value={k.opacity ?? 1} style={{ width: 64 }} onChange={(e) => setKey(i, n, { opacity: Number(e.target.value) })} /></label>
                <select className="text-input" aria-label={`Keyframe ${n + 1} movement`} value={k.ease} onChange={(e) => setKey(i, n, { ease: e.target.value as VpKey["ease"] })}><option value="linear">Straight to the next</option><option value="smooth">Eased to the next</option><option value="hold">Jump at the next</option></select>
                <button className="btn sm ghost" aria-label={`Remove keyframe ${n + 1} of layer ${i + 1}`} onClick={() => layer(i, { keys: keysOf(i).filter((_, z) => z !== n) })}>Remove</button></div>)}</li>; })}</ul>
            <div className="sm-row"><button className="btn sm" disabled={comp.layers.length >= st.limits.layers} onClick={() => setC({ layers: [...comp.layers, { cutout: st.cutouts[0].id, ...LAYER_DEFAULT }] })}>Add a cutout</button>
              <label>picture at <input className="text-input" type="number" step={0.25} min={0} aria-label="Picture at second" value={at} style={{ width: 70 }} onChange={(e) => setAt(Number(e.target.value))} /> s</label>
              <button className="btn" disabled={!!busy} onClick={() => void go("render", async () => { const saved = await api.vp("compose_set", dir, { ...comp, id: comp.id || undefined }); const id = saved.id ?? comp.id; setSt(saved); setComp(saved.compositions.find((c) => c.id === id) ?? comp); const r = await api.vp("render", dir, { id, time: at }); setRendered(r.file ?? ""); setSt(r); setSaid(`Drawn: ${r.layers} layer${r.layers === 1 ? "" : "s"}${r.missing?.length ? `, ${r.missing.length} left out because its cutout was removed` : ""}.`); })}>{busy === "render" ? "Drawing…" : "Save and render a picture"}</button></div>
            <div className="sm-row"><label>video: <input className="text-input" type="number" min={1} max={30} aria-label="Frames per second" value={vfps} style={{ width: 60 }} onChange={(e) => setVfps(Number(e.target.value))} /> per second, </label>
              <label><input className="text-input" type="number" min={0} step={0.5} aria-label="Seconds (0 = as long as its parts)" value={vsecs} style={{ width: 60 }} onChange={(e) => setVsecs(Number(e.target.value))} /> seconds (0 = as long as its parts)</label>
              <button className="btn" disabled={!!busy} onClick={() => void go("video", async () => { const saved = await api.vp("compose_set", dir, { ...comp, id: comp.id || undefined }); const id = saved.id ?? comp.id; setSt(saved); setComp(saved.compositions.find((c) => c.id === id) ?? comp);
                const r = await api.vpVideo("render_video", dir, { id, fps: vfps, ...(vsecs > 0 ? { seconds: vsecs } : {}) }); setVideo(r.file ?? ""); setSt(r); setSaid(`Video written: ${r.frames} frames, ${r.seconds} s.`); void Promise.resolve(revealItemInDir(`${dir}/${r.file}`.replace(/\//g, "\\"))).catch(() => {}); })}>{busy === "video" ? "Making the video…" : "Save and render a video"}</button>{stop}</div>
            {rendered && <img alt="The rendered composition" src={`${api.mediaUrl(`${dir}/${rendered}`)}?v=${rendered}`} style={{ maxWidth: "100%", borderRadius: 6, marginTop: 8 }} />}
            {video && <video controls aria-label="The rendered video" src={`${api.mediaUrl(`${dir}/${video}`)}?v=${video}`} style={{ maxWidth: "100%", borderRadius: 6, marginTop: 8 }} />}</>}</>}
      </section>}
    </Sheet>
  );
}
