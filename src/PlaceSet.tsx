import { useCallback, useEffect, useState } from "react";
import { open } from "@tauri-apps/plugin-dialog";
import { api, errorText, type PlaceSetStatus } from "./api";

const MODE_LABEL = { pictures: "From pictures", model: "From a 3D model", blender: "Made in Blender" } as const;

/**
 * The set for one place, on the place's own page (Cast, Places). The golden path: a place is described, given pictures, and then (optionally) given a set the camera can move around in. Two ways in, both
 * plain: from the place's pictures (2D, nothing to learn), or from a 3D model or Blender file (for people who use them). The full set builder and DirectorCam open from here, on this place's set.
 */
export function PlaceSet({ dir, place, name, pictures, onOpenSet, onPlan, onCheck }: { dir: string; place: string; name: string; pictures: number; onOpenSet: (set: string) => void; onPlan: (set: string) => void; onCheck?: (set: string) => void }) {
  const [st, setSt] = useState<PlaceSetStatus | null>(null);
  const [busy, setBusy] = useState("");
  const [err, setErr] = useState("");
  const [look, setLook] = useState<{ file: string; uncovered: number; warnings: string[] } | null>(null);
  const load = useCallback(() => api.placeSet("status", dir, { place }).then(setSt).catch((e) => setErr(errorText(e))), [dir, place]);
  useEffect(() => { setSt(null); setLook(null); setErr(""); void load(); }, [load, pictures]);
  const run = async (label: string, f: () => Promise<PlaceSetStatus | unknown>) => {
    setErr(""); setBusy(label);
    try { const r = await f(); if (r && typeof r === "object" && "place" in r) { setSt(r as PlaceSetStatus); setLook(null); } } catch (e) { setErr(errorText(e)); } finally { setBusy(""); }
  };
  const choose = async (kind: "model" | "blend") => {
    const f = await open({ multiple: false, filters: kind === "model" ? [{ name: "3D models", extensions: ["glb", "gltf"] }] : [{ name: "Blender files", extensions: ["blend"] }] });
    if (typeof f === "string") await run(kind === "model" ? "model" : "blend", () => api.placeSet(kind === "model" ? "from_model" : "from_blend", dir, { place, path: f }));
  };
  const s = st?.set ?? null;
  const blender = st?.blender.found;
  return (
    <section className="cw-set" aria-label="Set for this place">
      <h3>Set <span className="dim">optional: a version of this place the camera can move around in, so it looks the same from every shot</span></h3>
      {!st ? <p className="dim">{err || "Looking…"}</p> : !s ? <>
        <p className="dim">{st.next}</p>
        <div className="cw-set-ways">
          <div className="cw-set-way" aria-label="From pictures">
            <b>From this place's pictures</b><span className="dim">The easy way. Your pictures stand in a set. No 3D needed.</span>
            <button className="btn sm" disabled={!!busy || pictures === 0} title={pictures === 0 ? "Add a picture to this place first" : ""} onClick={() => void run("pictures", () => api.placeSet("from_pictures", dir, { place }))}>
              {busy === "pictures" ? "Making…" : pictures ? `Make a set from ${pictures} picture${pictures === 1 ? "" : "s"}` : "Add a picture first"}</button>
          </div>
          <div className="cw-set-way" aria-label="From 3D">
            <b>From a 3D model</b><span className="dim">For power users: a model you already have (.glb or .gltf), or a Blender file.</span>
            <div className="sm-row">
              <button className="btn sm" disabled={!!busy} onClick={() => void choose("model")}>{busy === "model" ? "Reading…" : "Choose a model…"}</button>
              <button className="btn sm" disabled={!!busy || !blender} title={blender ? "" : "Blender was not found"} onClick={() => void choose("blend")}>{busy === "blend" ? "Blender is reading it…" : "From a Blender file…"}</button>
              <button className="btn sm" disabled={!!busy || !blender} title={blender ? "" : "Blender was not found"} onClick={() => void run("new", () => api.placeSet("blender_new", dir, { place }))}>{busy === "new" ? "Opening Blender…" : "Build it in Blender"}</button>
            </div>
            <span className="dim">{blender ? `Blender ${st.blender.version} found on this computer.` : "Blender is optional and was not found. Models and pictures work without it."}</span>
          </div>
        </div></> : <>
        <p><b>{MODE_LABEL[s.mode]}</b> <span className="dim">· {s.mode === "pictures" ? `${s.pictures} picture${s.pictures === 1 ? "" : "s"}` : `${s.models} model${s.models === 1 ? "" : "s"}`} · {s.cameras} camera{s.cameras === 1 ? "" : "s"}{s.locked ? " · locked" : ""}</span></p>
        <p className="dim" role="status">{st.next}</p>
        <div className="sm-row">
          <button className="btn sm" disabled={!!busy} onClick={() => void run("look", async () => { setLook(await api.placeSet<{ file: string; uncovered: number; warnings: string[] }>("preview", dir, { place })); return null; })}>{busy === "look" ? "Drawing…" : "Look from the camera"}</button>
          <button className="btn sm" onClick={() => onPlan(s.id)}>Plan the shots</button>
          {onCheck && <button className="btn sm" onClick={() => onCheck(s.id)} title="What is where in every shot, and what a viewer might see go wrong">Check continuity</button>}
          <button className="btn sm ghost" onClick={() => onOpenSet(s.id)} title="The full set builder: move things, add cameras, check collisions">Edit the set</button>
          {s.mode === "blender" && <>
            <button className="btn sm" disabled={!!busy || !blender} onClick={() => void run("open", async () => { await api.placeSet("open_blender", dir, { place }); return null; })}>Open in Blender</button>
            <button className="btn sm" disabled={!!busy || !blender} title="Save in Blender first, then press this" onClick={() => void run("bring", () => api.placeSet("bring_back", dir, { place }))}>{busy === "bring" ? "Bringing it back…" : "Bring it back from Blender"}</button></>}
          <button className="link" disabled={!!busy} title="The set stays in the film; the place can be given another" onClick={() => void run("unlink", () => api.placeSet("unlink", dir, { place }))}>Take the link off</button>
        </div>
        {look && <figure className="cw-set-look" aria-label="The set from its camera"><img alt={`${name} from the set's camera`} src={`${api.mediaUrl(`${dir}/${look.file}`)}?v=${look.file}`} style={{ maxWidth: 420, borderRadius: 6 }} />
          <figcaption className="dim">{look.uncovered > 0.02 ? `${Math.round(look.uncovered * 100)}% of this view is empty: nothing in the set covers it. ` : ""}{look.warnings.join(" ")}</figcaption></figure>}
      </>}
      {err && st && <p className="ss-warn" role="alert">{err}</p>}
    </section>
  );
}
