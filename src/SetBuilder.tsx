import { useCallback, useEffect, useState } from "react";
import { open as openDialog } from "@tauri-apps/plugin-dialog";
import { Sheet } from "./Sheet";
import { SetContinuity } from "./SetContinuity";
import { api, errorText, type WlCamera, type WlCheck, type WlEvent, type BlenderStatus, type WlCollisions, type WlList, type WlMove, type WlSet, type WlView, type WlViews3d } from "./api";

/** Where a world point goes on the floor plan: x across, z up the plan (further into the set is higher). */
export function planPoint(x: number, z: number, b: WlSet["world"]["bounds"], w: number, h: number, pad = 14): [number, number] {
  const sx = (w - 2 * pad) / Math.max(b.x[1] - b.x[0], 0.001), sz = (h - 2 * pad) / Math.max(b.z[1] - b.z[0], 0.001);
  return [pad + (x - b.x[0]) * sx, h - pad - (z - b.z[0]) * sz];
}

/** The triangle that shows what a camera sees on the floor plan: its position and two edges of its field of view, `reach` metres long. */
export function cameraWedge(c: WlCamera, b: WlSet["world"]["bounds"], w: number, h: number, reach = 6): string {
  const edge = (deg: number) => { const a = ((c.yaw + deg) * Math.PI) / 180; return planPoint(c.x + Math.sin(a) * reach, c.z + Math.cos(a) * reach, b, w, h); };
  const [ox, oy] = planPoint(c.x, c.z, b, w, h), [lx, ly] = edge(-c.fov / 2), [rx, ry] = edge(c.fov / 2);
  return `${ox.toFixed(1)},${oy.toFixed(1)} ${lx.toFixed(1)},${ly.toFixed(1)} ${rx.toFixed(1)},${ry.toFixed(1)}`;
}

/** What the gap in a view means, in a sentence. */
export const gapWords = (v: WlView): string => (v.uncovered > 0.02 ? `${Math.round(v.uncovered * 100)}% of this view shows nothing the set has.` : "The set covers this view.");

const N = ({ label, value, step = 0.1, onChange, w = 70 }: { label: string; value: number; step?: number; onChange: (v: number) => void; w?: number }) => (
  <label>{label} <input className="text-input" type="number" step={step} aria-label={label} defaultValue={value} key={`${label}-${value}`} style={{ width: w }} onBlur={(e) => { const v = Number(e.target.value); if (Number.isFinite(v) && v !== value) onChange(v); }} /></label>);

/**
 * WorldLock, the set builder. A set is a place that exists on its own: flat pictures standing at fixed positions in metres, characters on the floor, saved cameras. A camera view is computed from the set, so
 * moving a camera never moves an object, and what the pictures do not cover is shown as a gap, never filled in. Free and local; nothing is generated or sent. 2.5D only: pictures are flat.
 */
export function SetBuilder({ dir, onClose, openSet, openTab }: { dir: string; onClose: () => void; openSet?: string; openTab?: "continuity" }) {
  const [list, setList] = useState<WlList | null>(null);
  const [set, setSet] = useState<WlSet | null>(null);
  const [tab, setTab] = useState<"layout" | "d3" | "cameras" | "shots" | "checks" | "continuity">(openTab ?? "layout");
  const [sel, setSel] = useState<{ kind: "asset" | "camera" | "character"; id: string } | null>(null);
  const [busy, setBusy] = useState("");
  const [err, setErr] = useState("");
  const [said, setSaid] = useState("");
  const [name, setName] = useState("");
  const [shots, setShots] = useState<string[]>([]);
  const [view, setView] = useState<WlView | null>(null);
  const [vshot, setVshot] = useState("");
  const [check, setCheck] = useState<WlCheck | null>(null);
  const [move, setMove] = useState<WlMove | null>(null);
  const [mfrom, setMfrom] = useState("");
  const [mto, setMto] = useState("");
  const [vname, setVname] = useState("");
  const [fours, setFours] = useState<WlViews3d | null>(null);
  const [hits, setHits] = useState<WlCollisions | null>(null);
  const [bl, setBl] = useState<BlenderStatus | null>(null);
  const [gname, setGname] = useState("");
  const [ev, setEv] = useState({ shot: "", thing: "", kind: "move" as WlEvent["kind"], x: "", z: "", state: "" });

  const loadList = useCallback(() => api.worldlock<WlList>("list", dir).then(setList).catch((e) => setErr(errorText(e))), [dir]);
  useEffect(() => { void loadList(); api.shots<{ shots: { id: string }[] }>("get", dir).then((r) => setShots(r.shots.map((s) => s.id))).catch(() => {}); }, [loadList, dir]);
  const go = async (label: string, f: () => Promise<void>) => { setErr(""); setSaid(""); setBusy(label); try { await f(); } catch (e) { setErr(errorText(e)); } finally { setBusy(""); } };
  const call = (label: string, action: Parameters<typeof api.worldlock>[0], data: Record<string, unknown> = {}) => go(label, async () => { if (!set) return; setSet(await api.worldlock<WlSet>(action, dir, { set: set.id, ...data })); });
  const open = (id: string) => go("open", async () => { setSet(await api.worldlock<WlSet>("get", dir, { set: id })); setSel(null); setView(null); setCheck(null); setMove(null); });
  useEffect(() => { if (openSet) void open(openSet); }, [openSet]); // eslint-disable-line react-hooks/exhaustive-deps
  const bring = () => go("picture", async () => {
    const f = await openDialog({ multiple: false, filters: [{ name: "Pictures", extensions: ["png", "jpg", "jpeg", "webp", "bmp", "tif", "tiff"] }] });
    if (typeof f !== "string" || !set) return;
    const r = await api.worldlock<WlSet & { id: string }>("asset_add", dir, { set: set.id, path: f, height: 2.5, z: 6 });
    setSet(r); setSel({ kind: "asset", id: r.id_ ?? r.assets[r.assets.length - 1].id });
  });

  if (!list) return <Sheet label="Set builder" className="wl-sheet" onDismiss={onClose}><h2>Sets</h2>{err ? <p className="ss-warn" role="alert">{err}</p> : <p className="dim">Loading…</p>}</Sheet>;
  const b = set?.world.bounds;
  const W = 420, H = 320;
  const asset = (id: string) => set?.assets.find((a) => a.id === id);
  const camera = (id: string) => set?.cameras.find((c) => c.id === id);
  const char = (id: string) => set?.characters.find((c) => c.id === id);
  const selAsset = sel?.kind === "asset" ? asset(sel.id) : undefined;
  const selCam = sel?.kind === "camera" ? camera(sel.id) : undefined;
  const selChar = sel?.kind === "character" ? char(sel.id) : undefined;
  const things = set ? [...set.assets.map((a) => ({ id: a.id, name: a.name })), ...set.characters.map((c) => ({ id: c.id, name: `${c.name} (character)` }))] : [];
  const lock = set?.locked;

  return (
    <Sheet label="Set builder" className="wl-sheet" onDismiss={onClose}>
      <div className="vs-head"><h2>Sets <span className="dim">a place that stays the same from every camera</span></h2><div style={{ flex: 1 }} /><button className="icon-btn" onClick={onClose} aria-label="Close">×</button></div>
      <p className="dim">Free and local: nothing is generated or sent. A set is flat pictures and 3D models standing at fixed positions in metres. A camera view is worked out from the set, so moving a camera never moves an object, and anything the pictures do not cover shows as a gap and is never filled in.</p>
      {err && <p className="ss-warn" role="alert">{err}</p>}
      {said && <p className="dim" role="status">{said}</p>}
      <div className="sm-row">
        <select className="text-input" aria-label="Sets" value={set?.id ?? ""} onChange={(e) => { if (e.target.value) void open(e.target.value); else setSet(null); }}><option value="">{list.sets.length ? "Choose a set…" : "No sets yet"}</option>{list.sets.map((s) => <option key={s.id} value={s.id}>{s.name}{s.locked ? " (locked)" : ""}</option>)}</select>
        <input className="text-input" placeholder="Name a new set" aria-label="New set name" value={name} maxLength={60} onChange={(e) => setName(e.target.value)} />
        <button className="btn sm" disabled={!!busy || !name.trim()} onClick={() => void go("create", async () => { const r = await api.worldlock<WlSet>("create", dir, { name }); setSet(r); setName(""); void loadList(); })}>Make a set</button></div>

      {set && b && <>
        <div className="sm-row" aria-label="Set controls"><b>{set.name}</b><span className="dim">version {set.version}{lock ? " · locked" : ""}</span>
          <button className="btn sm ghost" disabled={!!busy || !set.can_undo || lock} onClick={() => void go("undo", async () => setSet(await api.worldlock<WlSet>("undo", dir, { set: set.id })))} title={set.undo_label}>Undo</button>
          <button className="btn sm ghost" disabled={!!busy || !set.can_redo || lock} onClick={() => void go("redo", async () => setSet(await api.worldlock<WlSet>("redo", dir, { set: set.id })))} title={set.redo_label}>Redo</button>
          <button className="btn sm ghost" disabled={!!busy} onClick={() => void call("lock", lock ? "unlock" : "lock")}>{lock ? "Unlock this set" : "Lock this set"}</button></div>
        {lock && <p className="dim">This set is locked: it is the approved place. You can look at it from any camera, but nothing can change it until it is unlocked.</p>}
        <div className="cw-tabs" role="tablist">{([["layout", "Layout"], ["d3", "3D"], ["cameras", "Cameras"], ["shots", "Over the shots"], ["checks", "Checks and versions"], ["continuity", "Continuity"]] as const).map(([k, l]) => <button key={k} role="tab" aria-selected={tab === k} className={tab === k ? "on" : ""} onClick={() => setTab(k)}>{l}</button>)}</div>

        {tab === "layout" && <section aria-label="Layout">
          <p className="dim">Seen from above: across is left to right, up the plan is further into the set. Click something to select it.</p>
          <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Floor plan" style={{ width: "100%", maxWidth: 520, background: "#12161c", borderRadius: 8 }}>
            <rect x="14" y="14" width={W - 28} height={H - 28} fill="none" stroke="#3a4350" strokeDasharray="4 4" />
            {set.cameras.map((c) => <polygon key={c.id} data-testid={`cam-${c.id}`} points={cameraWedge(c, b, W, H)} fill={sel?.id === c.id ? "rgba(255,181,46,0.35)" : "rgba(100,183,255,0.18)"} stroke="#64b7ff" onClick={() => setSel({ kind: "camera", id: c.id })} />)}
            {set.assets.map((a) => { const [x1, y1] = planPoint(a.x - a.width / 2, a.z, b, W, H), [x2, y2] = planPoint(a.x + a.width / 2, a.z, b, W, H);
              return <line key={a.id} data-testid={`asset-${a.id}`} x1={x1} y1={y1} x2={x2} y2={y2} stroke={sel?.id === a.id ? "#ffb52e" : a.kind === "prop" ? "#e8845c" : "#9bd37a"} strokeWidth={sel?.id === a.id ? 5 : 3.5} strokeLinecap="round" onClick={() => setSel({ kind: "asset", id: a.id })}><title>{a.name}</title></line>; })}
            {set.characters.map((c) => { const [x, y] = planPoint(c.x, c.z, b, W, H); return <g key={c.id} onClick={() => setSel({ kind: "character", id: c.id })}><circle data-testid={`char-${c.id}`} cx={x} cy={y} r={6} fill={sel?.id === c.id ? "#ffb52e" : "#f4f7fa"} /><title>{c.name}</title></g>; })}
          </svg>
          <div className="sm-row"><button className="btn sm" disabled={!!busy || lock} onClick={() => void bring()}>Stand a picture in the set…</button>
            <button className="btn sm" disabled={!!busy || lock} onClick={() => void call("character", "character_set", { name: `Person ${set.characters.length + 1}`, x: 0, z: 4 })}>Place a person</button>
            <button className="btn sm" disabled={!!busy || lock} onClick={() => void call("camera", "camera_set", { name: `Camera ${set.cameras.length + 1}`, x: 0, y: 1.6, z: 0 })}>Save a camera</button></div>
          {selAsset && <div className="ss-heard" aria-label="Selected picture"><b>{selAsset.name}</b> <span className="dim">{selAsset.kind} · {selAsset.pixels[0]} × {selAsset.pixels[1]} px</span>
            <div className="sm-row"><N label="Across (m)" value={selAsset.x} onChange={(v) => void call("move", "asset_set", { id: selAsset.id, x: v })} /><N label="Up (m)" value={selAsset.y} onChange={(v) => void call("move", "asset_set", { id: selAsset.id, y: v })} />
              <N label="Depth (m)" value={selAsset.z} onChange={(v) => void call("move", "asset_set", { id: selAsset.id, z: v })} /><N label="Width (m)" value={selAsset.width} onChange={(v) => void call("move", "asset_set", { id: selAsset.id, width: v })} />
              <N label="Height (m)" value={selAsset.height} onChange={(v) => void call("move", "asset_set", { id: selAsset.id, height: v })} /></div>
            <div className="sm-row"><select className="text-input" aria-label="What it is" value={selAsset.kind} disabled={lock} onChange={(e) => void call("kind", "asset_set", { id: selAsset.id, kind: e.target.value })}><option value="layer">A layer (a backdrop or a wall)</option><option value="prop">A prop</option><option value="landmark">A landmark</option></select>
              <button className="btn sm ghost" disabled={!!busy || lock} onClick={() => void call("remove", "asset_remove", { id: selAsset.id }).then(() => setSel(null))}>Take it out of the set</button></div></div>}
          {selCam && <div className="ss-heard" aria-label="Selected camera"><b>{selCam.name}</b>
            <div className="sm-row"><N label="Camera across (m)" value={selCam.x} onChange={(v) => void call("move", "camera_set", { id: selCam.id, x: v })} /><N label="Camera height (m)" value={selCam.y} onChange={(v) => void call("move", "camera_set", { id: selCam.id, y: v })} />
              <N label="Camera depth (m)" value={selCam.z} onChange={(v) => void call("move", "camera_set", { id: selCam.id, z: v })} /><N label="Turn (°)" value={selCam.yaw} step={5} onChange={(v) => void call("move", "camera_set", { id: selCam.id, yaw: v })} />
              <N label="Tilt (°)" value={selCam.pitch} step={5} onChange={(v) => void call("move", "camera_set", { id: selCam.id, pitch: v })} /><N label="Lens width (° of view)" value={selCam.fov} step={5} onChange={(v) => void call("move", "camera_set", { id: selCam.id, fov: v })} /></div>
            <button className="btn sm ghost" disabled={!!busy || lock} onClick={() => void call("remove", "camera_remove", { id: selCam.id }).then(() => setSel(null))}>Remove this camera</button></div>}
          {selChar && <div className="ss-heard" aria-label="Selected person"><b>{selChar.name}</b>
            <div className="sm-row"><N label="Person across (m)" value={selChar.x} onChange={(v) => void call("move", "character_set", { id: selChar.id, x: v })} /><N label="Person depth (m)" value={selChar.z} onChange={(v) => void call("move", "character_set", { id: selChar.id, z: v })} />
              <N label="Facing (°)" value={selChar.facing} step={15} onChange={(v) => void call("move", "character_set", { id: selChar.id, facing: v })} /></div>
            <button className="btn sm ghost" disabled={!!busy || lock} onClick={() => void call("remove", "character_remove", { id: selChar.id }).then(() => setSel(null))}>Remove this person</button></div>}
        </section>}

        {tab === "d3" && <section aria-label="3D">
          <p className="dim">Stand real 3D models (glTF: .glb, or .gltf with embedded data) in the set. They are drawn by FilmCrafter's own renderer: flat shading under the set's lights, no shadows, no animation. A model's front faces the camera until you turn it.</p>
          <div className="sm-row"><button className="btn sm" disabled={!!busy || lock} onClick={() => void go("model", async () => {
            const f = await openDialog({ multiple: false, filters: [{ name: "3D models", extensions: ["glb", "gltf"] }] });
            if (typeof f !== "string") return;
            const r = await api.worldlock<WlSet & { id: string }>("model_add", dir, { set: set.id, path: f, y: 0, z: 6 });
            setSet(r); setSaid(`Added. ${r.models?.find((m) => m.id === r.id)?.summary.warnings.join(" ") ?? ""}`);
          })}>Stand a 3D model in the set…</button>
            <label className="ov-check"><input type="checkbox" checked={!!set.ground?.visible} disabled={lock} onChange={(e) => void call("ground", "ground_set", { visible: e.target.checked })} /> Show the ground (a metre-checker)</label></div>
          <div className="sm-row"><label>Sky overhead <input type="color" aria-label="Sky overhead" value={set.sky?.top ?? "#1a2236"} disabled={lock} onChange={(e) => void call("sky", "sky_set", { top: e.target.value })} /></label>
            <label>Sky at the horizon <input type="color" aria-label="Sky at the horizon" value={set.sky?.horizon ?? "#d9a066"} disabled={lock} onChange={(e) => void call("sky", "sky_set", { horizon: e.target.value })} /></label>
            <N label="Fog (0 to 1)" value={set.sky?.fog ?? 0} step={0.01} w={96} onChange={(v) => void call("sky", "sky_set", { fog: v })} /></div>
          {(set.models ?? []).length === 0 ? <p className="dim">No 3D models yet.</p> : <ul className="ss-cues">{(set.models ?? []).map((m) => <li key={m.id} aria-label={`Model ${m.name}`}>
            <div className="sm-row"><b>{m.name}</b> <span className="dim">{m.summary.triangles.toLocaleString()} triangles · {m.summary.size.join(" × ")} m</span>
              <label className="ov-check"><input type="checkbox" checked={m.visible} disabled={lock} onChange={(e) => void call("model", "model_set", { id: m.id, visible: e.target.checked })} /> Shown</label>
              <label className="ov-check"><input type="checkbox" checked={m.solid} disabled={lock} onChange={(e) => void call("model", "model_set", { id: m.id, solid: e.target.checked })} /> Solid</label>
              {(set.groups ?? []).length > 0 && <select className="text-input" aria-label={`Group of ${m.name}`} value={m.parent ?? ""} disabled={lock} onChange={(e) => void call("model", "model_set", { id: m.id, parent: e.target.value || null })}><option value="">No group</option>{(set.groups ?? []).map((g) => <option key={g.id} value={g.id}>{g.name}</option>)}</select>}
              <button className="btn sm ghost" disabled={!!busy || lock} aria-label={`Remove ${m.name}`} onClick={() => void call("model", "model_remove", { id: m.id })}>Remove</button></div>
            <details><summary className="dim">Position and size</summary><div className="sm-row"><N label={`${m.name} across (m)`} value={m.x} onChange={(v) => void call("model", "model_set", { id: m.id, x: v })} /><N label={`${m.name} up (m)`} value={m.y} onChange={(v) => void call("model", "model_set", { id: m.id, y: v })} />
              <N label={`${m.name} depth (m)`} value={m.z} onChange={(v) => void call("model", "model_set", { id: m.id, z: v })} /><N label={`${m.name} turn (°)`} value={m.yaw} step={15} onChange={(v) => void call("model", "model_set", { id: m.id, yaw: v })} />
              <N label={`${m.name} size (×)`} value={m.scale} step={0.1} onChange={(v) => void call("model", "model_set", { id: m.id, scale: v })} /></div></details>
            {m.summary.warnings.map((w) => <p key={w} className="ss-warn">{w}</p>)}</li>)}</ul>}
          <div className="sm-row"><input className="text-input" placeholder="Name a group of models" aria-label="New group name" value={gname} maxLength={60} onChange={(e) => setGname(e.target.value)} />
            <button className="btn sm" disabled={!!busy || lock || !gname.trim()} onClick={() => void call("group", "group_set", { name: gname }).then(() => setGname(""))}>Make a group</button>
            {(set.groups ?? []).map((g) => <span key={g.id} className="dim">{g.name}: <N label={`${g.name} across (m)`} value={g.x} onChange={(v) => void call("group", "group_set", { id: g.id, x: v })} /></span>)}</div>
          <div className="sm-row"><button className="btn" disabled={!!busy} onClick={() => void go("fours", async () => setFours(await api.worldlock<WlViews3d>("views3d", dir, { set: set.id, size: [480, 270] })))}>See it from four sides</button>
            <button className="btn sm ghost" disabled={!!busy} onClick={() => void go("hits", async () => setHits(await api.worldlock<WlCollisions>("collisions", dir, { set: set.id })))}>Check for collisions</button></div>
          {hits && (hits.ok ? <p className="dim" role="status" aria-label="Collision result">No collisions found among {hits.checked.models} models (measured on their boxes).</p> : <ul className="ss-cues" aria-label="Collision result">{hits.issues.map((i, n) => <li key={n} className="ss-warn">{i.text}</li>)}</ul>)}
          {fours && <div className="sm-row" aria-label="Four views">{fours.views.map((v) => <figure key={v.name} style={{ margin: 0 }}><img alt={`${v.name} view`} src={`${api.mediaUrl(`${dir}/${v.file}`)}?v=${v.file}`} style={{ width: 230, borderRadius: 6 }} /><figcaption className="dim">{v.name}{v.uncovered > 0.02 ? ` · ${Math.round(v.uncovered * 100)}% empty` : ""}</figcaption></figure>)}</div>}
          <h4>Blender <span className="dim">optional; the set does not need it</span></h4>
          <div className="sm-row"><button className="btn sm ghost" disabled={!!busy} onClick={() => void go("bl", async () => setBl(await api.blender<BlenderStatus>("status", dir)))}>Look for Blender</button>
            <button className="btn sm ghost" disabled={!!busy} onClick={() => void go("blx", async () => { const r = await api.blender<BlenderStatus>("export", dir, { set: set.id }); setBl({ ...(bl ?? { found: false, path: "", version: "", note: "" }), ...r, note: `The script is written in ${r.relative}. Run it with: blender -b -P build_scene.py (experimental: the models and cameras come across, the ground, sky and lights do not).` }); })}>Write the Blender script</button></div>
          {bl && <p className="dim" role="status" aria-label="Blender">{bl.found ? `Blender ${bl.version} found. ` : ""}{bl.note}</p>}
        </section>}

        {tab === "cameras" && <section aria-label="Cameras">
          <div className="sm-row"><label>As at shot <select className="text-input" aria-label="As at shot" value={vshot} onChange={(e) => setVshot(e.target.value)}><option value="">The set as built</option>{shots.map((s) => <option key={s} value={s}>{s}</option>)}</select></label></div>
          <ul className="ss-cues">{set.cameras.map((c) => <li key={c.id} className="sm-row"><b>{c.name}</b> <span className="dim">{c.x}, {c.y}, {c.z} m · turn {c.yaw}° · {c.fov}° wide</span>
            <button className="btn sm" disabled={!!busy} aria-label={`See from ${c.name}`} onClick={() => void go("view", async () => setView(await api.worldlock<WlView>("render", dir, { set: set.id, camera: c.id, size: [960, 540], ...(vshot ? { shot: vshot } : {}) })))}>See from here</button></li>)}</ul>
          {view && <div aria-label="View"><img alt="The view from the camera" src={`${api.mediaUrl(`${dir}/${view.file}`)}?v=${view.file}`} style={{ maxWidth: "100%", borderRadius: 6 }} />
            <p className={view.uncovered > 0.02 ? "ss-warn" : "dim"} role="status">{gapWords(view)} {view.shot ? `As at shot ${view.shot}.` : ""}</p>
            {view.warnings.filter((w) => !w.includes("shows nothing the set has")).map((w) => <p key={w} className="ss-warn">{w}</p>)}
            {view.skipped.length > 0 && <p className="dim">{view.skipped.length} picture{view.skipped.length === 1 ? " is" : "s are"} not in this view ({view.skipped.map((s) => asset(s.id)?.name ?? s.id).join(", ")}).</p>}</div>}
          {set.cameras.length > 1 && <div className="sm-row"><span className="dim">Does a move stay inside the set?</span>
            <select className="text-input" aria-label="Move from" value={mfrom} onChange={(e) => setMfrom(e.target.value)}><option value="">From…</option>{set.cameras.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}</select>
            <select className="text-input" aria-label="Move to" value={mto} onChange={(e) => setMto(e.target.value)}><option value="">To…</option>{set.cameras.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}</select>
            <button className="btn sm" disabled={!!busy || !mfrom || !mto} onClick={() => void go("move", async () => setMove(await api.worldlock<WlMove>("check_move", dir, { set: set.id, from: mfrom, to: mto, steps: 10 })))}>Check the move</button></div>}
          {move && <p className={move.ok ? "dim" : "ss-warn"} role="status" aria-label="Move check">{move.ok ? "The whole move stays inside what the set covers." : move.warning}</p>}
        </section>}

        {tab === "shots" && <section aria-label="Over the shots">
          <h4>Which camera each shot uses</h4>
          {shots.length === 0 ? <p className="dim">This film has no shots yet.</p> : <ul className="ss-cues">{shots.map((s) => <li key={s} className="sm-row"><b>{s}</b>
            <select className="text-input" aria-label={`Camera for ${s}`} value={set.shots.find((x) => x.shot === s)?.camera ?? ""} disabled={lock} onChange={(e) => void call("shot", "shot_camera", { shot: s, camera: e.target.value || null })}><option value="">No camera chosen</option>{set.cameras.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}</select></li>)}</ul>}
          <h4>What changes in the set <span className="dim">the set as built is never changed: from the shot after the event, the set is seen with it applied</span></h4>
          <ul className="ss-cues">{set.events.map((e) => <li key={e.id} className="sm-row"><b>{e.shot}</b> {things.find((t) => t.id === (e.asset ?? e.character))?.name ?? "something removed"} <span className="dim">{e.kind}{e.to.x !== undefined ? ` to ${e.to.x}, ${e.to.z ?? "·"}` : ""}{e.state ? ` · ${e.state}` : ""}</span>
            <button className="btn sm ghost" disabled={!!busy || lock} aria-label={`Remove the event at ${e.shot}`} onClick={() => void call("event", "event_remove", { id: e.id })}>Remove</button></li>)}</ul>
          <div className="sm-row">
            <select className="text-input" aria-label="Event shot" value={ev.shot} onChange={(e) => setEv({ ...ev, shot: e.target.value })}><option value="">At shot…</option>{shots.map((s) => <option key={s} value={s}>{s}</option>)}</select>
            <select className="text-input" aria-label="Event thing" value={ev.thing} onChange={(e) => setEv({ ...ev, thing: e.target.value })}><option value="">Which…</option>{things.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}</select>
            <select className="text-input" aria-label="Event kind" value={ev.kind} onChange={(e) => setEv({ ...ev, kind: e.target.value as WlEvent["kind"] })}><option value="move">Moves</option><option value="state">Changes state</option><option value="remove">Leaves</option><option value="appear">Appears</option></select>
            <input className="text-input" type="number" step={0.1} placeholder="to across (m)" aria-label="Event across" value={ev.x} style={{ width: 100 }} onChange={(e) => setEv({ ...ev, x: e.target.value })} />
            <input className="text-input" type="number" step={0.1} placeholder="to depth (m)" aria-label="Event depth" value={ev.z} style={{ width: 100 }} onChange={(e) => setEv({ ...ev, z: e.target.value })} />
            <input className="text-input" placeholder="State, e.g. on the floor" aria-label="Event state" value={ev.state} maxLength={80} onChange={(e) => setEv({ ...ev, state: e.target.value })} />
            <button className="btn sm" disabled={!!busy || lock || !ev.shot || !ev.thing} onClick={() => void go("event", async () => {
              const isAsset = !!asset(ev.thing);
              const to: Record<string, number> = {}; if (ev.x !== "") to.x = Number(ev.x); if (ev.z !== "") to.z = Number(ev.z);
              setSet(await api.worldlock<WlSet>("event_set", dir, { set: set.id, shot: ev.shot, [isAsset ? "asset" : "character"]: ev.thing, kind: ev.kind, to, state: ev.state })); setEv({ shot: "", thing: "", kind: "move", x: "", z: "", state: "" });
            })}>Record it</button></div>
        </section>}

        {tab === "continuity" && <SetContinuity dir={dir} set={set.id} />}
        {tab === "checks" && <section aria-label="Checks and versions">
          {set.characters.length >= 2 && <div className="sm-row"><span className="dim">The line the camera must not cross runs between</span>
            {[0, 1].map((i) => <select key={i} className="text-input" aria-label={`Line person ${i + 1}`} value={set.axis[i] ?? ""} disabled={lock} onChange={(e) => { const next = [...set.axis]; next[i] = e.target.value; void call("axis", "meta_set", { axis: next.filter(Boolean) }); }}><option value="">Person…</option>{set.characters.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}</select>)}</div>}
          <div className="sm-row"><button className="btn" disabled={!!busy} onClick={() => void go("check", async () => setCheck(await api.worldlock<WlCheck>("check", dir, { set: set.id })))}>Check the set</button></div>
          {check && (check.ok ? <p className="dim" role="status" aria-label="Check result">Nothing found in {check.checked.pictures} pictures, {check.checked.cameras} cameras and {check.checked.events} events.</p>
            : <ul className="ss-cues" aria-label="Check result">{check.issues.map((i, n) => <li key={n} className="ss-warn">{i.text}</li>)}</ul>)}
          <h4>Saved versions <span className="dim">kept for good; the undo history is limited</span></h4>
          <div className="sm-row"><input className="text-input" placeholder="Name this version" aria-label="Version name" value={vname} maxLength={60} onChange={(e) => setVname(e.target.value)} />
            <button className="btn sm" disabled={!!busy || !vname.trim()} onClick={() => void go("version", async () => { setSet(await api.worldlock<WlSet>("version_save", dir, { set: set.id, name: vname })); setVname(""); setSaid("Saved."); })}>Save this version</button></div>
          <ul className="ss-cues">{set.saved_versions.map((v) => <li key={v.number} className="sm-row"><b>{v.name}</b> <span className="dim">{v.assets} pictures</span>
            <button className="btn sm ghost" disabled={!!busy || lock} aria-label={`Restore ${v.name}`} onClick={() => void call("restore", "version_restore", { number: v.number })}>Restore (undo can bring back what you have now)</button></li>)}</ul>
        </section>}
      </>}
    </Sheet>
  );
}
