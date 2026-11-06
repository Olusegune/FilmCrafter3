import { useState } from "react";
import { TRANSITION_LIST } from "./transitions";
import { open } from "@tauri-apps/plugin-dialog";
import { api, errorText, type BoardShot } from "./api";
import { PanelHead } from "./Dock";
import * as I from "./icons";

export const IMAGE_EXT = ["png", "jpg", "jpeg", "webp"];
export const CLIP_EXT = ["mp4", "mov", "webm", "m4v"];
export const MOTIONS: { id: string; label: string }[] = [
  { id: "zoom_in", label: "Slow push in" }, { id: "zoom_out", label: "Slow pull out" },
  { id: "pan_left", label: "Pan left" }, { id: "pan_right", label: "Pan right" },
  { id: "pan_up", label: "Tilt up" }, { id: "pan_down", label: "Tilt down" }, { id: "none", label: "Hold still" },
];
export const TRANSITIONS: { id: string; label: string }[] = TRANSITION_LIST;   // the full list lives in transitions.ts

const pick = async (multiple: boolean, images = true, clips = true) => {
  const ext = [...(images ? IMAGE_EXT : []), ...(clips ? CLIP_EXT : [])];
  const f = await open({ multiple, filters: [{ name: clips ? "Images and video clips" : "Images", extensions: ext }] });
  return f ? (Array.isArray(f) ? f : [f]) : [];
};

/** Your own image or clip for one shot, its camera move and transition. Free: nothing is sent anywhere. */
export function OwnMediaPanel({ dir, shot, onChanged }: { dir: string; shot: BoardShot | undefined; onChanged: () => void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  if (!shot) return null;
  const chosen = shot.versions.find((v) => v.approved) ?? shot.versions.filter((v) => v.state === "ready").slice(-1)[0];
  const isStill = shot.preview_kind === "image" && chosen?.media_kind === "image";
  const run = async (f: () => Promise<unknown>) => {
    setBusy(true); setError("");
    try { await f(); onChanged(); } catch (e) { setError(errorText(e)); } finally { setBusy(false); }
  };
  const addTake = () => run(async () => { const [p] = await pick(false); if (p) await api.media(dir, "import", { shot: shot.id, path: p }); });
  const addKey = () => run(async () => { const [p] = await pick(false, true, false); if (p) await api.media(dir, "import", { shot: shot.id, path: p, role: "keyframe" }); });
  const still = () => run(() => api.media(dir, "stills", { shots: [shot.id] }));
  return (
    <section className="panel own-media">
      <PanelHead icon={<I.Upload size={18} />} title="Your own media" tag="Free" tone="free" hint="Nothing here is sent to an AI service or checked by one." />
      <div className="own-row tiles">
        <button className="tile" onClick={addTake} disabled={busy || shot.locked}><I.Film size={20} /><b>Use my image or clip</b><span>Replaces this shot in the film</span></button>
        <button className="tile" onClick={addKey} disabled={busy || shot.locked} title="An image AI video starts from"><I.ImageIcon size={20} /><b>Use my image as keyframe</b><span>AI video starts from it</span></button>
        {shot.keyframe && !isStill && <button className="tile" onClick={still} disabled={busy || shot.locked}
                                              title="Use the approved keyframe itself, with a slow camera move"><I.Move size={20} /><b>Moving still from keyframe</b><span>Free, with a slow camera move</span></button>}
      </div>
      <div className="own-grid">
        {isStill && chosen && <label>Camera move
          <select value={shot.preview_motion ?? "zoom_in"} disabled={busy}
                  onChange={(e) => run(() => api.media(dir, "motion", { job: chosen.id, motion: e.target.value }))}>
            {MOTIONS.map((m) => <option key={m.id} value={m.id}>{m.label}</option>)}
          </select></label>}
        <label>Into this shot
          <select value={shot.transition ?? "cut"} disabled={busy}
                  onChange={(e) => run(() => api.media(dir, "transition", { shots: [shot.id], transition: e.target.value }))}>
            {TRANSITIONS.map((m) => <option key={m.id} value={m.id}>{m.label}</option>)}
          </select></label>
      </div>
      {error && <div className="error-text">{error}</div>}
      <p className="dim">Short clips repeat to fill the shot. Your media is never sent to an AI service or checked by one.</p>
    </section>
  );
}

/** Place many images/clips along the timeline, one per empty shot, in the order chosen. */
export async function addMediaToTimeline(dir: string, start?: string) {
  const paths = await pick(true);
  if (!paths.length) return null;
  return api.media<{ placed: { shot: string; file: string }[]; skipped: { file: string; reason: string }[] }>(dir, "fill", { paths, start });
}

/** Moving still on the preview: the same camera move the export makes, as a CSS animation. */
// The song is the clock: the animation stays paused and is positioned at the playhead on every tick.
// drift: the performance profile's breathing micro-animation (people only), running while the song plays.
export function StillPreview({ src, motion, duration, offset, drift, playing }: { src: string; motion?: string | null; duration: number; offset: number;
  drift?: { amp: number; period: number } | null; playing?: boolean }) {
  const img = <img className={`clip kb kb-${motion ?? "none"}`} alt="" src={src}
                   style={{ animationDuration: `${Math.max(0.5, duration)}s`, animationDelay: `${-Math.min(duration, Math.max(0, offset))}s`, animationPlayState: playing ? "running" : "paused" }} />;       // paused: the move stands still on the frame at the playhead
  if (!drift) return img;
  return <div className="clip breathe" style={{ ["--amp" as string]: String(1 + drift.amp), ["--sway" as string]: `${(drift.amp / 3) * 100}%`,
    animationDuration: `${drift.period}s`, animationPlayState: playing ? "running" : "paused" }}>{img}</div>;
}
