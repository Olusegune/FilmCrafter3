import { useCallback, useEffect, useState } from "react";
import { Sheet } from "./Sheet";
import { api, errorText, type DcAdvice, type DcCaps, type DcClip, type DcDraft, type DcMove, type DcPackage, type DcPath, type DcPlan, type DcPlans, type DcPlaced, type DcPreview, type WlList, type WlSet } from "./api";
import { cameraWedge, planPoint } from "./SetBuilder";
import { FinishClip } from "./FinishClip";

export const SIZES = ["establishing", "wide", "medium wide", "medium", "medium close-up", "close-up", "extreme close-up", "over the shoulder", "insert"];
export const MOVES: [DcMove["kind"], string, string][] = [["static", "Static", ""], ["pan", "Pan", "degrees, right is positive"], ["tilt", "Tilt", "degrees, up is positive"], ["dolly", "Dolly", "metres, forward is positive"], ["truck", "Truck", "metres, right is positive"],
  ["pedestal", "Pedestal", "metres, up is positive"], ["crane", "Crane", "metres up (and back)"], ["orbit", "Orbit", "degrees round the subject"], ["tracking", "Tracking", "goes with the person"], ["push_in", "Push in", "metres toward the subject"], ["pull_out", "Pull out", "metres away"]];
export const RULES: [string, string][] = [["line", "Crossing the line"], ["thirty", "Under 30° of change"], ["eyeline", "Eyeline"], ["screen_direction", "Screen direction"], ["blocked", "Something in the way"], ["out_of_frame", "Subject out of frame"], ["bounds", "Camera outside the set"], ["gap", "Set not covering the view"], ["continuity", "A person jumps"]];

/** The advice for one shot, worst first. */
export const adviceFor = (items: DcAdvice[], shot: string): DcAdvice[] => items.filter((i) => i.shot === shot).sort((a, b) => ["warning", "advice", "note"].indexOf(a.severity) - ["warning", "advice", "note"].indexOf(b.severity));

/** What a move is, in a sentence. */
export const moveWords = (m: DcMove): string => { const k = MOVES.find((x) => x[0] === m.kind); return !k || m.kind === "static" ? "The camera does not move." : m.kind === "tracking" ? "The camera goes with the person." : `${k[1]}: ${m.amount} (${k[2]}).`; };

const N = ({ label, value, step = 0.1, onChange, w = 66 }: { label: string; value: number; step?: number; onChange: (v: number) => void; w?: number }) => (
  <label>{label} <input className="text-input" type="number" step={step} aria-label={label} defaultValue={value} key={`${label}-${value}`} style={{ width: w }} onBlur={(e) => { const v = Number(e.target.value); if (Number.isFinite(v) && v !== value) onChange(v); }} /></label>);

/**
 * DirectorCam: plan the shots of a story beat on a WorldLock set. The plan is a draft made from the words of the beat (plain rules, no model, nothing sent); it becomes a plan when you keep it. Each shot has a camera
 * you can move, a move along a real path, who goes where, and advice (the line, eyelines, screen direction, objects in the way) that you can overrule by marking a shot deliberate. A shot's package is the first and
 * last frame, a strip along the path, a depth map and an object map, made from the set. Nothing is generated; a picture or video made from a package is not guaranteed to match it.
 */
export function DirectorCam({ dir, onClose, initialSet }: { dir: string; onClose: () => void; initialSet?: string }) {
  const [sets, setSets] = useState<WlList | null>(null);
  const [setId, setSetId] = useState("");
  const [set, setSet] = useState<WlSet | null>(null);
  const [plans, setPlans] = useState<DcPlans["plans"]>([]);
  const [plan, setPlan] = useState<DcPlan | null>(null);
  const [draft, setDraft] = useState<DcDraft | null>(null);
  const [beat, setBeat] = useState("");
  const [sel, setSel] = useState<string | null>(null);
  const [prev, setPrev] = useState<DcPreview | null>(null);
  const [pk, setPk] = useState<DcPackage | null>(null);
  const [path, setPath] = useState<DcPath | null>(null);
  const [caps, setCaps] = useState<DcCaps | null>(null);
  const [provider, setProvider] = useState("kie");
  const [model, setModel] = useState("");
  const [filmShots, setFilmShots] = useState<string[]>([]);
  const [target, setTarget] = useState("");
  const [busy, setBusy] = useState("");
  const [err, setErr] = useState("");
  const [said, setSaid] = useState("");
  const [renderer, setRenderer] = useState<"builtin" | "blender">("builtin");
  const [blenderOn, setBlenderOn] = useState(false);
  const [clip, setClip] = useState<DcClip | null>(null);

  const go = async (label: string, f: () => Promise<void>) => { setErr(""); setSaid(""); setBusy(label); try { await f(); } catch (e) { setErr(errorText(e)); } finally { setBusy(""); } };
  useEffect(() => { api.blender("status", dir).then((b) => setBlenderOn(b.found)).catch(() => {}); }, [dir]);
  useEffect(() => { api.worldlock<WlList>("list", dir).then(setSets).catch((e) => setErr(errorText(e))); api.shots<{ shots: { id: string }[] }>("get", dir).then((r) => setFilmShots(r.shots.map((s) => s.id))).catch(() => {}); }, [dir]);
  useEffect(() => { if (initialSet) void openSet(initialSet); }, [initialSet]); // eslint-disable-line react-hooks/exhaustive-deps
  const openSet = useCallback((id: string) => go("set", async () => {
    setSetId(id); setPlan(null); setDraft(null); setSel(null); setPrev(null); setPk(null); setPath(null);
    if (!id) { setSet(null); setPlans([]); return; }
    setSet(await api.worldlock<WlSet>("get", dir, { set: id })); setPlans((await api.directorCam<DcPlans>("plans", dir, { set: id })).plans);
  }), [dir]);  // eslint-disable-line react-hooks/exhaustive-deps
  const openPlan = (id: string) => go("plan", async () => { setPrev(null); setPk(null); setPath(null); setSel(null); setPlan(id ? await api.directorCam<DcPlan>("plan_get", dir, { set: setId, plan: id }) : null); });
  const change = (shot: string, patch: Record<string, unknown>) => go("shot", async () => { if (plan) setPlan(await api.directorCam<DcPlan>("shot_set", dir, { set: setId, plan: plan.id, shot, ...patch })); });

  if (!sets) return <Sheet label="DirectorCam" className="dc-sheet" onDismiss={onClose}><h2>DirectorCam</h2>{err ? <p className="ss-warn" role="alert">{err}</p> : <p className="dim">Loading…</p>}</Sheet>;
  const b = set?.world.bounds;
  const W = 440, H = 320;
  const shots = plan?.shots ?? draft?.shots ?? [];
  const cur = shots.find((s) => s.id === sel) ?? null;
  const advice = plan?.advice.items ?? [];

  return (
    <Sheet label="DirectorCam" className="dc-sheet" onDismiss={onClose}>
      <div className="vs-head"><h2>DirectorCam <span className="dim">plan the shots of a beat on a set</span></h2><div style={{ flex: 1 }} /><button className="icon-btn" onClick={onClose} aria-label="Close">×</button></div>
      <p className="dim">Free and local: no model is asked and nothing is generated or sent. The plan comes from the words of your beat and the people and things in the set. Every piece of advice can be overruled. A picture or video made from a shot package is not guaranteed to match the set: the package is what to check it against.</p>
      {err && <p className="ss-warn" role="alert">{err}</p>}
      {said && <p className="dim" role="status">{said}</p>}
      <div className="sm-row"><select className="text-input" aria-label="Set" value={setId} onChange={(e) => void openSet(e.target.value)}><option value="">{sets.sets.length ? "Choose a set…" : "No sets yet: make one in Sets"}</option>{sets.sets.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}</select>
        {set && <select className="text-input" aria-label="Plan" value={plan?.id ?? ""} onChange={(e) => void openPlan(e.target.value)}><option value="">{plans.length ? "Open a saved plan…" : "No saved plans"}</option>{plans.map((p) => <option key={p.id} value={p.id}>{p.name} · {p.approved}/{p.shots} approved</option>)}</select>}</div>

      {set && !plan && <section aria-label="Plan a beat">
        <label className="field"><span>The story beat <span className="dim">name the people and things as the set does</span></span>
          <textarea className="text-input" rows={3} aria-label="Story beat" value={beat} maxLength={600} onChange={(e) => setBeat(e.target.value)} placeholder="The girl enters the market, sees the oranges, and rushes to help the vendor." /></label>
        <button className="btn" disabled={!!busy || !beat.trim()} onClick={() => void go("beat", async () => { const r = await api.directorCam<DcDraft>("plan_beat", dir, { set: setId, beat }); setDraft(r); setSel(r.shots[0]?.id ?? null); })}>{busy === "beat" ? "Planning…" : "Plan the shots"}</button>
        {draft && <div className="ss-heard" aria-label="Draft"><p><b>{draft.shots.length} shots</b> <span className="dim">people: {draft.people.join(", ") || "none found"} · things: {draft.things.join(", ") || "none found"}</span></p>
          {draft.not_found.length > 0 && <p className="ss-warn">Not found in the set: {draft.not_found.join(", ")}.</p>}
          <p className="dim">{draft.note}</p>
          <div className="sm-row"><button className="btn" disabled={!!busy} onClick={() => void go("keep", async () => { const r = await api.directorCam<DcPlan>("plan_save", dir, { set: setId, name: beat.slice(0, 40), beat, shots: draft.shots }); setPlan(r); setDraft(null); setPlans((await api.directorCam<DcPlans>("plans", dir, { set: setId })).plans); setSel(r.shots[0]?.id ?? null); })}>Keep this plan</button>
            <button className="btn ghost" onClick={() => { setDraft(null); setSel(null); }}>Discard the draft</button></div></div>}
      </section>}

      {set && b && shots.length > 0 && <section aria-label="Shots">
        {plan?.set_changed && <p className="ss-warn" role="status">The set has changed since this plan was made (version {plan.set_version} then, {plan.set_version_now} now). Check the previews again.</p>}
        {plan && <p className={plan.advice.counts.warning ? "ss-warn" : "dim"} aria-label="Advice summary">{plan.advice.counts.warning} warning{plan.advice.counts.warning === 1 ? "" : "s"}, {plan.advice.counts.advice} advice, {plan.advice.counts.note} deliberate.</p>}
        <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Plan from above" style={{ width: "100%", maxWidth: 520, background: "#12161c", borderRadius: 8 }}>
          <rect x="14" y="14" width={W - 28} height={H - 28} fill="none" stroke="#3a4350" strokeDasharray="4 4" />
          {set.assets.filter((a) => a.kind !== "prop" || a.x < 40).map((a) => { const [x1, y1] = planPoint(a.x - a.width / 2, a.z, b, W, H), [x2, y2] = planPoint(a.x + a.width / 2, a.z, b, W, H); return <line key={a.id} x1={x1} y1={y1} x2={x2} y2={y2} stroke="#5d6b7a" strokeWidth={3} />; })}
          {set.characters.map((c) => { const [x, y] = planPoint(c.x, c.z, b, W, H); return <circle key={c.id} cx={x} cy={y} r={5} fill="#f4f7fa"><title>{c.name}</title></circle>; })}
          {shots.map((s) => <g key={s.id} onClick={() => setSel(s.id)}>
            <polygon data-testid={`shot-${s.n}`} points={cameraWedge({ ...s.camera, id: s.id } as never, b, W, H, 4)} fill={s.id === sel ? "rgba(255,181,46,0.4)" : "rgba(100,183,255,0.12)"} stroke={s.id === sel ? "#ffb52e" : "#64b7ff"} />
            {s.characters.map((c) => { const [x1, y1] = planPoint(c.from.x, c.from.z, b, W, H), [x2, y2] = planPoint(c.to.x, c.to.z, b, W, H); return <line key={c.id} x1={x1} y1={y1} x2={x2} y2={y2} stroke={s.id === sel ? "#ffb52e" : "#f08a5d"} strokeWidth={1.6} markerEnd="" strokeDasharray="3 2" />; })}</g>)}
          {prev && sel === prev.shot && <polyline points={prev.path.map((p) => planPoint(p.x, p.z, b, W, H).join(",")).join(" ")} fill="none" stroke="#ffb52e" strokeWidth={2} />}
        </svg>
        <ol className="ss-cues">{shots.map((s) => <li key={s.id} className={s.id === sel ? "on" : ""}><button className="link" onClick={() => setSel(s.id)} aria-label={`Select shot ${s.n}`}><b>{s.n}. {s.title}</b></button>
          <span className="dim"> {s.size} · {moveWords(s.move)} · {s.duration} s{s.because.length ? ` · because: ${s.because.join(", ")}` : ""}</span>
          {plan && <span> <select className="text-input" aria-label={`Approval of shot ${s.n}`} value={s.approval} onChange={(e) => void change(s.id, { approval: e.target.value })}><option value="suggested">Not decided</option><option value="approved">Approved</option><option value="rejected">Rejected</option></select></span>}
          {adviceFor(advice, s.id).map((a, i) => <p key={i} className={a.severity === "warning" ? "ss-warn" : "dim"}>{a.severity === "warning" ? "Warning: " : a.severity === "advice" ? "Advice: " : "Noted: "}{a.text}</p>)}</li>)}</ol>
      </section>}

      {plan && cur && <section aria-label="Selected shot"><h4>Shot {cur.n}: {cur.title}</h4>
        <div className="sm-row"><select className="text-input" aria-label="Shot size" value={cur.size} onChange={(e) => { const size = e.target.value; void go("place", async () => { const r = await api.directorCam<DcPlaced>("place_camera", dir, { set: setId, subjects: cur.subjects, size, focal_mm: cur.camera.focal_mm }); await change(cur.id, { size, camera: r.camera }); }); }}>{SIZES.map((x) => <option key={x} value={x}>{x}</option>)}</select>
          <span className="dim">Choosing a size places the camera for you.</span></div>
        <div className="sm-row"><N label="Camera across (m)" value={cur.camera.x} onChange={(v) => void change(cur.id, { camera: { x: v } })} /><N label="Camera height (m)" value={cur.camera.y} onChange={(v) => void change(cur.id, { camera: { y: v } })} />
          <N label="Camera depth (m)" value={cur.camera.z} onChange={(v) => void change(cur.id, { camera: { z: v } })} /><N label="Turn (°)" value={cur.camera.yaw} step={5} onChange={(v) => void change(cur.id, { camera: { yaw: v } })} />
          <N label="Tilt (°)" value={cur.camera.pitch} step={5} onChange={(v) => void change(cur.id, { camera: { pitch: v } })} /><N label="Lens (mm)" value={cur.camera.focal_mm ?? 35} step={5} onChange={(v) => void change(cur.id, { camera: { focal_mm: v } })} />
          <label>Picture <select className="text-input" aria-label="Aspect ratio" value={cur.camera.aspect ?? "16:9"} onChange={(e) => void change(cur.id, { camera: { aspect: e.target.value } })}>{["16:9", "2.39:1", "1.85:1", "4:3", "1:1", "9:16"].map((a) => <option key={a} value={a}>{a}</option>)}</select></label></div>
        <div className="sm-row"><select className="text-input" aria-label="Camera move" value={cur.move.kind} onChange={(e) => void change(cur.id, { move: { ...cur.move, kind: e.target.value } })}>{MOVES.map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select>
          <N label="Move amount" value={cur.move.amount} step={0.5} onChange={(v) => void change(cur.id, { move: { ...cur.move, amount: v } })} /><N label="Length (s)" value={cur.duration} step={0.5} onChange={(v) => void change(cur.id, { duration: v })} />
          <button className="btn sm ghost" disabled={!!busy} onClick={() => void go("path", async () => setPath(await api.directorCam<DcPath>("path", dir, { set: setId, view: cur.camera, move: cur.move, target: cur.subjects[0] || undefined, follow: cur.characters[0] ? { from_x: cur.characters[0].from.x, from_z: cur.characters[0].from.z, to_x: cur.characters[0].to.x, to_z: cur.characters[0].to.z } : undefined })))}>Check the move</button></div>
        {path && <p className={path.ok ? "dim" : "ss-warn"} role="status" aria-label="Move check">{path.ok ? "The whole move stays inside what the set covers." : path.warning}</p>}
        <div className="sm-row" role="group" aria-label="This shot is deliberate"><span className="dim">Overrule on purpose:</span>{RULES.map(([k, l]) => <label key={k} className="ov-check"><input type="checkbox" checked={cur.allow.includes(k)} onChange={(e) => void change(cur.id, { allow: e.target.checked ? [...cur.allow, k] : cur.allow.filter((x) => x !== k) })} /> {l}</label>)}</div>
        <div className="sm-row"><button className="btn sm" disabled={!!busy} onClick={() => void go("preview", async () => setPrev(await api.directorCam<DcPreview>("preview", dir, { set: setId, plan: plan.id, shot: cur.id })))}>Preview the first and last frame</button>
          <button className="btn sm" disabled={!!busy} onClick={() => void go("package", async () => { setPk(await api.directorCam<DcPackage>("package", dir, { set: setId, plan: plan.id, shot: cur.id, provider, model })); setSaid("The package is made. Nothing was sent."); })}>Make the shot package</button>
          <button className="btn sm ghost" disabled={!!busy} onClick={() => void go("remove", async () => { setPlan(await api.directorCam<DcPlan>("shot_remove", dir, { set: setId, plan: plan.id, shot: cur.id })); setSel(null); setPrev(null); setPk(null); })}>Take this shot out</button></div>
        <div className="sm-row" aria-label="Make a clip"><select className="text-input" aria-label="Drawn by" value={renderer} onChange={(e) => setRenderer(e.target.value as "builtin" | "blender")}><option value="builtin">Drawn by FilmCrafter (fast)</option><option value="blender" disabled={!blenderOn}>{blenderOn ? "Drawn by Blender (real shadows, slower)" : "Blender not found"}</option></select>
          <button className="btn sm" disabled={!!busy} onClick={() => void go("clip", async () => { const r = await api.directorCam<DcClip>("clip", dir, { set: setId, plan: plan.id, shot: cur.id, renderer, width: 960 }); setClip(r); setSaid(`The clip is made (${r.frames} frames, ${r.took} s). Nothing was sent.`); })}>{busy === "clip" ? "Making the clip…" : "Make a clip of this shot"}</button></div>
        {clip && clip.shot === cur.id && <figure aria-label="Clip" style={{ margin: 0 }}><video controls src={`${api.mediaUrl(`${dir}/${clip.file}`)}?v=${clip.file}`} style={{ maxWidth: 480, borderRadius: 6 }} /><figcaption className="dim">{clip.renderer} · {clip.seconds} s · {clip.size[0]}×{clip.size[1]}{clip.people_note ? ` · ${clip.people_note}` : ""}</figcaption></figure>}
        {clip && clip.shot === cur.id && <FinishClip dir={dir} clip={clip.file} set={setId} />}
        {prev && prev.shot === cur.id && <div className="sm-row" aria-label="Previews">{([["First frame", prev.first], ["Last frame", prev.last]] as const).map(([l, v]) => <figure key={l} style={{ margin: 0 }}><img alt={l} src={`${api.mediaUrl(`${dir}/${v.file}`)}?v=${v.file}`} style={{ width: 240, borderRadius: 6 }} /><figcaption className="dim">{l}{v.uncovered > 0.02 ? ` · ${Math.round(v.uncovered * 100)}% not covered by the set` : ""}</figcaption></figure>)}</div>}
        <h4>Which model will make it? <span className="dim">what it can take of the package</span></h4>
        <div className="sm-row"><input className="text-input" aria-label="Provider" value={provider} onChange={(e) => setProvider(e.target.value)} style={{ width: 90 }} /><input className="text-input" aria-label="Model" placeholder="model name, e.g. kling/v2-5-turbo-image-to-video-pro" value={model} onChange={(e) => setModel(e.target.value)} />
          <button className="btn sm ghost" disabled={!!busy} onClick={() => void go("caps", async () => setCaps(await api.directorCam<DcCaps>("capabilities", dir, { provider, model })))}>What can it take?</button></div>
        {(caps || pk) && <ul className="ss-cues" aria-label="What the model can take">{(pk?.conditioning ?? caps!.conditioning).map((c) => <li key={c.input} className="sm-row"><b>{c.label}</b> <span className={c.status === "supported" ? "dim" : "ss-warn"}>{c.status}</span> <span className="dim">{c.why}{c.alternative ? ` Instead: ${c.alternative}` : ""}</span></li>)}</ul>}
        {pk && <p className="dim" aria-label="Package">Package folder: {pk.relative}. {pk.motion_words} The first frame leaves {Math.round(pk.frame_gap.first * 100)}% of the view uncovered by the set.</p>}
        <div className="sm-row"><select className="text-input" aria-label="Use for film shot" value={target} onChange={(e) => setTarget(e.target.value)}><option value="">Use this for the film's shot…</option>{filmShots.map((s) => <option key={s} value={s}>{s}</option>)}</select>
          <button className="btn sm" disabled={!!busy || !target} onClick={() => void go("apply", async () => { const r = await api.directorCam<DcPlan>("apply", dir, { set: setId, plan: plan.id, shot: cur.id, film_shot: target, provider, model }); setPlan(r.plan ?? plan); setSaid(`Shot ${target} now has this camera (${r.applied?.framing}, ${r.applied?.movement}) and the first frame as a reference.`); })}>Give it to that shot</button></div>
      </section>}
    </Sheet>
  );
}
