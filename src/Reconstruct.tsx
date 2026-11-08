import { useCallback, useEffect, useState } from "react";
import { open as openDialog } from "@tauri-apps/plugin-dialog";
import { Sheet } from "./Sheet";
import { api, errorText, type RcEstimate, type RcItem, type RcStatus } from "./api";

const pct = (n: number) => `${Math.round(n * 100)}%`;

/** The top-down plan of the draft: the assumed reference camera at the bottom, each object as a box where the picture puts it (x across, z away from the camera). Rejected objects are left out. */
export function FloorPlan({ items, fov }: { items: RcItem[]; fov: number }) {
  const live = items.filter((i) => i.status !== "rejected");
  const zmax = Math.max(8, ...live.map((i) => i.distance_m * 1.15));
  const half = Math.tan((fov / 2) * Math.PI / 180);
  const W = 420, H = 260, sx = W / (2 * zmax * half * 1.1), sz = (H - 24) / zmax;
  const px = (x: number) => W / 2 + x * sx, pz = (z: number) => H - 14 - z * sz;
  return (
    <svg role="img" aria-label="Floor plan of the draft" viewBox={`0 0 ${W} ${H}`} width="100%" style={{ maxWidth: 520, background: "rgba(255,255,255,0.03)", borderRadius: 8 }}>
      <polygon points={`${px(0)},${pz(0)} ${px(-zmax * half)},${pz(zmax)} ${px(zmax * half)},${pz(zmax)}`} fill="rgba(255,181,46,0.07)" stroke="rgba(255,181,46,0.4)" />
      {live.map((i) => { const x = (((i.bbox[0] + i.bbox[2]) / 2) - 0.5) * 2 * i.distance_m * half; const wall = i.kind === "structure"; const w = Math.min(W - 8, Math.max(6, i.width_m * sx)), dpt = wall ? 3 : Math.max(5, i.depth_m * sz);            // walls and the sky are drawn as thin lines so they do not hide the things in front of them
        return <g key={i.id} opacity={0.35 + 0.65 * i.confidence}><rect x={px(x) - w / 2} y={pz(i.distance_m) - dpt / 2} width={w} height={dpt} rx={2} fill={wall ? "#c9a35e" : i.status === "accepted" ? "#5ec27a" : "#8ab4ff"} stroke="#fff" strokeOpacity={0.4}><title>{`${i.name}: ${pct(i.confidence)} sure`}</title></rect></g>; })}
      <circle cx={px(0)} cy={pz(0)} r={5} fill="#ffb52e" /><text x={px(0) + 9} y={pz(0) + 4} fontSize="10" fill="#cfd6e4">camera (assumed 1.6 m up)</text>
    </svg>);
}

/**
 * Make a set from reference pictures with the AI's help. Each step is its own button and nothing is sent until the person confirms the one step that sends something. What comes back is a proposal with the AI's own
 * confidence and reasons, to be corrected and approved; what a single picture cannot show is said on the screen, not hidden.
 */
export function Reconstruct({ dir, place, name, onClose, onDone }: { dir: string; place: string; name: string; onClose: () => void; onDone: () => void }) {
  const [st, setSt] = useState<RcStatus | null>(null);
  const [est, setEst] = useState<RcEstimate | null>(null);
  const [ok, setOk] = useState(false);
  const [busy, setBusy] = useState("");
  const [err, setErr] = useState("");
  const [mode, setMode] = useState<"layers" | "boxes">("layers");
  const run = useCallback(async (label: string, f: () => Promise<RcStatus | void>) => { setErr(""); setBusy(label); try { const r = await f(); if (r) setSt(r); } catch (e) { setErr(errorText(e)); } finally { setBusy(""); } }, []);
  useEffect(() => { void run("load", () => api.reconstruct("status", dir, { place })); }, [run, dir, place]);
  useEffect(() => { if (st && st.references.length && !st.proposal) api.reconstruct<RcEstimate>("estimate", dir, { place }).then(setEst).catch(() => setEst(null)); }, [st?.references.length, st?.proposal, dir, place]); // eslint-disable-line react-hooks/exhaustive-deps
  const add = async () => { const f = await openDialog({ multiple: true, filters: [{ name: "Pictures", extensions: ["png", "jpg", "jpeg", "webp"] }] }); const files = typeof f === "string" ? [f] : Array.isArray(f) ? f : []; for (const file of files) await run("add", () => api.reconstruct("add_reference", dir, { place, path: file })); };
  const set = (item: string, patch: Record<string, unknown>) => run("item", () => api.reconstruct("item_set", dir, { place, item, patch }));
  const p = st?.proposal ?? null;
  const accepted = p?.items.filter((i) => i.status === "accepted").length ?? 0;
  return (
    <Sheet label="A set from pictures" className="wl-sheet" onDismiss={onClose}>
      <div className="vs-head"><h2>A set from pictures <span className="dim">{name}</span></h2><div style={{ flex: 1 }} /><button className="icon-btn" onClick={onClose} aria-label="Close">×</button></div>
      <p className="dim">Turn pictures of this place into a draft set you correct and approve. The AI lists what it can see and guesses where things are; that is an estimate from one point of view, not a measurement.</p>
      {st && <p className="ss-warn" role="note">{st.limits}</p>}
      {err && <p className="ss-warn" role="alert">{err}</p>}

      <h4>1. Pictures of the place</h4>
      <div className="sm-row">{st?.references.map((r) => <figure key={r.id} style={{ margin: 0 }}><img alt={r.name} src={api.mediaUrl(`${dir}/${r.file}`)} style={{ width: 120, borderRadius: 6 }} />
        <figcaption className="dim"><button className="link" disabled={!!busy || !!st.approved} onClick={() => void run("rm", () => api.reconstruct("remove_reference", dir, { place, id: r.id }))}>remove</button></figcaption></figure>)}</div>
      <div className="sm-row"><button className="btn sm" disabled={!!busy || !!st?.approved} onClick={() => void add()}>Add pictures…</button>
        {!!st?.place_pictures && !st.references.length && <button className="btn sm" disabled={!!busy} onClick={() => void run("fromplace", () => api.reconstruct("add_reference", dir, { place, from_place: true }))}>Use this place's {st.place_pictures} picture{st.place_pictures === 1 ? "" : "s"}</button>}</div>
      <p className="dim">One to six pictures. More angles make a better draft; one picture can only show what faces its camera.</p>

      <h4>2. Ask the AI what it sees</h4>
      {!p && <>
        {est && <p role="status" aria-label="What this sends">{est.local ? "Your local model does this: free, and nothing leaves this computer." : `This sends ${est.sends} to your AI provider. Estimated cost about $${est.usd.toFixed(3)} (${est.note})`}</p>}
        {est && !est.local && <label className="ov-check"><input type="checkbox" checked={ok} onChange={(e) => setOk(e.target.checked)} /> I understand this sends the pictures to my AI provider and costs about ${est.usd.toFixed(3)}</label>}
        <div className="sm-row"><button className="btn sm" disabled={!!busy || !st?.references.length || !est || (!est.local && !ok)} onClick={() => void run("propose", () => api.reconstruct("propose", dir, { place, confirmed: ok || !!est?.local }))}>{busy === "propose" ? "The AI is looking…" : "Ask the AI to list what it sees"}</button></div></>}
      {p && <p className="dim">{p.scene.kind ? `${p.scene.kind}. ` : ""}{p.scene.summary} <span>Asked {p.model}.</span></p>}

      {p && <>
        <h4>3. Check and correct <span className="dim">{accepted} of {p.items.length} accepted</span></h4>
        <div className="sm-row"><button className="btn sm" disabled={!!busy} onClick={() => void run("all", () => api.reconstruct("accept_all", dir, { place, min_confidence: 0.4 }))}>Accept everything it is at least 40% sure of</button></div>
        <FloorPlan items={p.items} fov={st!.assumed.fov} />
        <ul className="ss-cues" aria-label="Inventory">{p.items.map((i) => <li key={i.id} aria-label={`Item ${i.name}`}>
          <div className="sm-row"><label className="ov-check"><input type="checkbox" checked={i.status === "accepted"} disabled={!!busy || !!st?.approved} aria-label={`Accept ${i.name}`} onChange={(e) => void set(i.id, { status: e.target.checked ? "accepted" : "rejected" })} /> <b>{i.name}</b></label>
            <span className="dim">{i.kind} · {pct(i.confidence)} sure · about {i.distance_m} m away, {i.width_m} × {i.height_m} m</span></div>
          <p className="dim" style={{ margin: "2px 0" }}>{i.reason}{i.hidden ? ` Not visible: ${i.hidden}` : ""}</p>
          <details><summary className="dim">Correct its name or distance</summary><div className="sm-row"><label>Distance (m) <input className="text-input" type="number" step={0.5} aria-label={`${i.name} distance (m)`} defaultValue={i.distance_m} key={`${i.id}-${i.distance_m}`} style={{ width: 80 }} disabled={!!st?.approved}
            onBlur={(e) => { const v = Number(e.target.value); if (Number.isFinite(v) && v !== i.distance_m) void set(i.id, { distance_m: v }); }} /></label>
            <label>Name <input className="text-input" aria-label={`${i.name} name`} defaultValue={i.name} key={`${i.id}-${i.name}`} disabled={!!st?.approved} onBlur={(e) => { if (e.target.value.trim() && e.target.value !== i.name) void set(i.id, { name: e.target.value }); }} /></label></div></details></li>)}</ul>
        {p.uncertainty.length > 0 && <details><summary>What the AI could not tell ({p.uncertainty.length})</summary><ul>{p.uncertainty.map((u) => <li key={u}>{u}</li>)}</ul></details>}
        {p.missing_views.length > 0 && <details><summary>Pictures that would improve this ({p.missing_views.length})</summary><ul>{p.missing_views.map((u) => <li key={u}>{u}</li>)}</ul></details>}
        {p.reuse.length > 0 && <p className="dim">Models you already have that match by name: {p.reuse.map((r) => r.name).join(", ")}. They are not used unless you add them yourself in the set builder.</p>}

        <h4>4. Build the draft set</h4>
        <div className="sm-row"><select className="text-input" aria-label="How to build it" value={mode} onChange={(e) => setMode(e.target.value as "layers" | "boxes")} disabled={!!st?.approved}><option value="layers">Flat pictures cut from the reference (looks like the picture)</option><option value="boxes">Boxes of the visible size (for blocking in 3D)</option></select>
          <button className="btn sm" disabled={!!busy || accepted === 0 || !!st?.approved} onClick={() => void run("build", () => api.reconstruct("build", dir, { place, mode }))}>{busy === "build" ? "Building…" : st?.built ? "Build it again" : "Build the draft"}</button></div>
        <p className="dim">{st?.image_to_3d}</p>
        {st?.built && <>
          <h4>5. Approve</h4>
          <p role="status">{st.approved ? "Approved: the set is locked. Unlock it in the set builder to change it." : `A draft set was made from ${st.built.items.length} object${st.built.items.length === 1 ? "" : "s"}. It is a draft until you approve it: look at it from the camera, change anything in the set builder, then approve.`}</p>
          <div className="sm-row"><button className="btn sm" disabled={!!busy || !!st.approved} onClick={() => void run("approve", async () => { const r = await api.reconstruct<RcStatus>("approve", dir, { place }); onDone(); return r; })}>{st.approved ? "Approved" : "Approve and lock the set"}</button>
            <button className="btn sm ghost" onClick={onDone}>Look at the set</button></div></>}
      </>}
    </Sheet>
  );
}
