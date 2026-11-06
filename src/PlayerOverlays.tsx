import { useEffect, useRef, useState } from "react";
import { api, type Overlay } from "./api";
import { loadFonts } from "./FontPicker";
import { moveAt, reducedMotion, type Beat } from "./overlayMotion";
import { evalKeys, upsertKey } from "./overlayKeys";
import ICONS from "./shapeIcons.json";
import { needsSeek } from "./playerMath";

/** On-screen text, pictures and cards over the Studio player, as they will be drawn on the exported film (an approximation: the export draws the lettering
 *  itself, so edges and shadow differ slightly). They move in the way you chose. Follows Export > On-screen text and the Layers panel as you change them.
 *  The layer selected in the Layers panel is always shown (faintly when it is not on at this moment) and can be dragged to where you want it. */
/** A video clip in the player: shown from its own start point and kept in step with the film's time. (The player shows the clip as it is: a cut-out colour is applied when the film is made.) */
function ClipView({ o, src, at, on, cls, common, style, playing }: { o: Overlay; src: string; at: number; on: boolean; cls: string; common: object; style: React.CSSProperties; playing: boolean }) {
  const ref = useRef<HTMLVideoElement>(null);
  const want = (o.in_s ?? 0) + Math.max(0, at - (o.start ?? 0));
  useEffect(() => {
    const v = ref.current;
    if (!v || !on || !Number.isFinite(want)) return;
    const len = v.duration && Number.isFinite(v.duration) ? v.duration : o.src_dur ?? 0;
    const t = len ? (o.loop ? want % len : Math.min(want, Math.max(0, len - 0.05))) : want;
    if (needsSeek(v.currentTime, t, playing)) v.currentTime = t;               // playing: only when it has drifted (every frame would stutter); paused: every scrub step shows its own frame
  }, [want, on, o.loop, o.src_dur, playing]);
  return <video ref={ref} className={cls} style={style} src={src} muted playsInline preload="auto" aria-hidden="true" {...common} />;
}

export function PlayerOverlays({ dir, time, playing = false, selected, onSelect, beat, accents }: { dir: string; time: number; playing?: boolean; selected?: string | null; onSelect?: (id: string | null) => void; beat?: Beat | null; accents?: number[] | null }) {
  const [items, setItems] = useState<Overlay[]>([]);
  const [drag, setDrag] = useState<{ id: string; x: number; y: number } | null>(null);
  const box = useRef<HTMLDivElement>(null);
  const [faces, setFaces] = useState<Record<string, string>>({});      // font id -> the family name to draw it in on the player
  useEffect(() => {
    const want = [...new Set(items.filter((o) => o.kind === "text" && o.font).map((o) => o.font as string))].filter((id) => !(id in faces));
    if (!want.length) return;
    loadFonts(dir).then((list) => {
      const add: Record<string, string> = {};
      for (const id of want) {
        const f = [...list.project, ...list.installed].find((x) => x.id === id);
        if (!f) { add[id] = ""; continue; }
        if (id.startsWith("project:")) {        // a font file kept in the project: loaded into the player
          const family = `pf-${id.replace(/[^a-z0-9]/gi, "_")}`;
          try { const face = new FontFace(family, `url(${api.mediaUrl(`${dir}/fonts/${f.file}`)})`); face.load().then((l) => document.fonts.add(l)).catch(() => undefined); add[id] = family; }
          catch { add[id] = ""; }
        } else add[id] = f.name;                // an installed font: the window can draw it by its name
      }
      setFaces((c) => ({ ...c, ...add }));
    }).catch(() => undefined);
  }, [items, dir, faces]);
  useEffect(() => {
    const pull = () => api.overlays(dir, "list").then(setItems).catch(() => setItems([]));
    pull();
    window.addEventListener("pf-overlays-changed", pull);
    return () => window.removeEventListener("pf-overlays-changed", pull);
  }, [dir]);

  const here = (o: Overlay) => o.enabled && o.placed && o.start != null && o.end != null && time >= o.start && time <= o.end;
  const live = items.filter((o) => here(o) || (o.id === selected && o.enabled));
  if (!live.length) return null;

  const begin = (e: React.PointerEvent, o: Overlay, cur: { x: number; y: number }) => {
    if (!onSelect) return;
    e.stopPropagation();
    onSelect(o.id);
    const r = box.current?.getBoundingClientRect();
    if (!r || o.kind === "fill" || o.cover) return;
    const sx = e.clientX, sy = e.clientY, ox = cur.x, oy = cur.y;
    const rel = Math.max(0, Math.min((o.end ?? 0) - (o.start ?? 0), time - (o.start ?? 0)));       // for a layer with keyframes: where on its own clock it was dropped
    let last = { id: o.id, x: ox, y: oy };
    (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
    const move = (ev: PointerEvent) => {
      last = { id: o.id, x: Math.max(0, Math.min(1, ox + (ev.clientX - sx) / r.width)), y: Math.max(0, Math.min(1, oy + (ev.clientY - sy) / r.height)) };
      setDrag(last);
    };
    const up = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
      setDrag(null);
      if (Math.abs(last.x - ox) + Math.abs(last.y - oy) > 0.002) {
        const rx = Math.round(last.x * 1000) / 1000, ry = Math.round(last.y * 1000) / 1000;
        const keyed = !!o.keys?.length;                    // with keyframes, dropping it sets a key at the playhead; without, it moves the layer
        const patch = keyed ? { keys: upsertKey(o.keys, rel, { x: rx, y: ry }) } : { x: rx, y: ry };
        setItems((all) => all.map((v) => (v.id === o.id ? { ...v, ...patch } : v)));        // stay where it was dropped while the engine saves
        api.overlays(dir, "update", { id: o.id, ...patch }).then(() => window.dispatchEvent(new Event("pf-overlays-changed"))).catch(() => window.dispatchEvent(new Event("pf-overlays-changed")));
      }
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
  };

  return (
    <div className="player-overlays" ref={box}>
      {live.map((o) => {
        const on = here(o);
        const s = o.start ?? 0, e = o.end ?? s + 4;
        const f = Math.max(0.05, Math.min(o.fade || 0.4, (e - s) / 3));
        const opacity = (on ? Math.max(0, Math.min(1, (time - s) / f, (e - time) / f)) : 0.45) * (o.keys?.length && o.kind !== "fill" && !o.cover ? evalKeys(o.keys, Math.min(Math.max(time - s, 0), e - s)).opacity ?? 1 : 1);
        const keyed = !!o.keys?.length && o.kind !== "fill" && !o.cover;
        const kv = keyed ? evalKeys(o.keys, Math.min(Math.max(time - s, 0), e - s)) : null;           // keyframes replace the movement preset
        const m = kv ? { dx: 0, dy: 0, k: kv.scale ?? 1, reveal: 1 } : reducedMotion() ? { dx: 0, dy: 0, k: 1, reveal: 1 } : moveAt(o.anim, Math.min(Math.max(time, s), e), s, e, f, beat, o.kind === "text" ? (o.text ?? "").length : 0, accents);
        const cur = { x: kv?.x ?? o.x, y: kv?.y ?? o.y };
        const at = drag?.id === o.id ? drag : cur;
        const sel = o.id === selected;
        const cls = `po-item ${sel ? "po-sel" : ""} ${onSelect ? "po-pick" : ""}`;
        const bl = o.blend ? { mixBlendMode: ({ multiply: "multiply", screen: "screen", overlay: "overlay", softlight: "soft-light", hardlight: "hard-light", darken: "darken", lighten: "lighten", add: "plus-lighter", difference: "difference" } as Record<string, React.CSSProperties["mixBlendMode"]>)[o.blend] } : {};       // the player shows how it mixes; the finished film does the same arithmetic
        const common = { onPointerDown: onSelect ? (ev: React.PointerEvent) => begin(ev, o, cur) : undefined };
        const grad = `linear-gradient(${o.angle ?? 180}deg, ${o.color}, ${o.color2 || o.color})`;       // 0 is to the top, 90 to the right, 180 to the bottom
        if (o.kind === "fill" || o.cover) {
          const style = { ...bl, opacity, transform: `scale(${m.k})`, ...(o.kind === "fill" ? { background: grad } : { objectFit: "cover" as const }) };
          return o.kind === "fill"
            ? <div key={o.id} className={`${cls} po-fill`} style={style} {...common} />
            : <img key={o.id} className={`${cls} po-fill`} alt="" style={style} src={api.mediaUrl(`${dir}/${o.file}`)} draggable={false} {...common} />;
        }
        const k = o.scale ?? 1, fillOpacity = opacity * (o.opacity ?? 1), painted = !!(o.gradient && o.color2);
        const turnBy = (o.rotation ?? 0) + (kv?.rotation ?? 0);
        const turn = turnBy ? ` rotate(${turnBy}deg)` : "";
        const pos = { ...bl, left: `${at.x * 100}%`, top: `${at.y * 100}%`, opacity, clipPath: m.reveal < 1 ? `inset(0 ${(1 - m.reveal) * 100}% 0 0)` : undefined, transform: `translate(calc(-50% + ${m.dx}cqw), calc(-50% + ${m.dy}cqh)) scale(${m.k})${turn}` };
        if (o.kind === "shape") {
          const w = o.width * k, h = (o.height ?? (o.shape === "line" ? 0.006 : 0.2)) * k, sw = o.stroke_w ?? 0;
          const round = o.shape === "circle" ? "50%" : o.shape === "rounded" ? `calc(min(${w * 100}cqw, ${h * 100}cqh) * ${o.radius ?? 0.2})` : 0;
          return <div key={o.id} className={cls} {...common} style={{ ...pos, opacity: fillOpacity, width: `${w * 100}cqw`, height: `${h * 100}cqh`, minHeight: 1, boxSizing: "border-box",
            background: o.filled === false ? "transparent" : painted ? grad : o.color, border: sw > 0 ? `${sw * 100}cqh solid ${o.stroke ?? "#ffffff"}` : undefined, borderRadius: round, maxWidth: "none" }} />;
        }
        if (o.kind === "icon") {
          const polys = (ICONS as Record<string, { polys: number[][][] }>)[o.icon ?? "star"]?.polys ?? [];
          const a = ((o.angle ?? 180) * Math.PI) / 180, dx = Math.sin(a), dy = -Math.cos(a), half = (Math.abs(dx) + Math.abs(dy)) / 2;       // the same gradient line CSS uses
          return <svg key={o.id} className={cls} {...common} viewBox="0 0 1 1" style={{ ...pos, opacity: fillOpacity, width: `${o.width * k * 100}cqw`, height: `${o.width * k * 100}cqw`, maxWidth: "none" }}>
            {painted && <defs><linearGradient id={`g-${o.id}`} gradientUnits="userSpaceOnUse" x1={0.5 - dx * half} y1={0.5 - dy * half} x2={0.5 + dx * half} y2={0.5 + dy * half}>
              <stop offset="0" stopColor={o.color} /><stop offset="1" stopColor={o.color2} /></linearGradient></defs>}
            {polys.map((p, i) => <polygon key={i} points={p.map((q) => q.join(",")).join(" ")} fill={painted ? `url(#g-${o.id})` : o.color} />)}</svg>;
        }
        if (o.kind === "text") {
          const sw = o.stroke_w ?? 0;
          const style: React.CSSProperties = { ...pos, opacity: fillOpacity, fontSize: `${o.size * k * 100}cqh`, color: o.color, fontFamily: o.font && faces[o.font] ? `"${faces[o.font]}", var(--font-display, sans-serif)` : undefined };
          if (painted) Object.assign(style, { backgroundImage: grad, WebkitBackgroundClip: "text", backgroundClip: "text", WebkitTextFillColor: "transparent" });
          if (sw > 0) Object.assign(style, { WebkitTextStroke: `${sw * 200}cqh ${o.stroke ?? "#000000"}`, paintOrder: "stroke fill" });
          if (o.shadow === false) style.textShadow = "none";
          return <span key={o.id} className={`${cls} po-text`} style={style} {...common}>{o.text}</span>;
        }
        if (o.kind === "clip") return <ClipView key={o.id} o={o} src={api.mediaUrl(`${dir}/${o.file}`)} at={time} on={on} playing={playing} cls={`${cls} po-img`} common={common}
                                             style={{ ...pos, opacity: fillOpacity, filter: "none", width: `${Math.min(2, o.width) * 100}%`, aspectRatio: o.src_w && o.src_h ? `${o.src_w} / ${o.src_h}` : undefined }} />;
        return <img key={o.id} className={`${cls} po-img`} alt="" draggable={false} {...common} src={api.mediaUrl(`${dir}/${o.file}`)}
                    style={{ ...pos, opacity: fillOpacity, width: `${Math.min(2, o.width * k) * 100}%`, ...(o.shadow === false ? { filter: "none" } : {}) }} />;
      })}
    </div>
  );
}
