import { useEffect, useRef, useState } from "react";
import { api, errorText, type BlockingPlanData, type BlockingView } from "./api";
import { ask } from "./ask";
import { ROOM, along, bearing, clampRoom, coneEdges, initials, lineThrough, norm360, round1, toRoom, type Pt } from "./blockingMath";

type Drag = { kind: "person" | "face" | "cam" | "aim" | "prop"; i: number } | null;
const COLOURS = ["#e8b45c", "#64b7ff", "#5fd49a", "#f08ab6", "#b79cff", "#ff9b6b"];

/**
 * The floor plan of a shot: where each person stands and which way they face, where the camera is and what it looks at, the line between the first two people (the camera should stay on one
 * side of it), and the other shots of the scene as small ghost cameras. Drag anything. What it says, as the camera sees it, is added to the shot's prompts.
 */
export function BlockingPlan({ dir, shot, locked, plan, onSaved }: { dir: string; shot: string; locked: boolean; plan: BlockingPlanData | null; onSaved: (patch: Record<string, unknown>) => Promise<void> }) {
  const [view, setView] = useState<BlockingView | null>(null);
  const [draft, setDraft] = useState<BlockingPlanData | null>(plan);
  const [drag, setDrag] = useState<Drag>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const svg = useRef<SVGSVGElement | null>(null);

  const load = (mode: "get" | "suggest" | "carry" = "get") => api.shots<BlockingView>("blocking", dir, { id: shot, mode }).then((r) => { setView(r); return r; });
  useEffect(() => { setDraft(plan); setErr(""); load().catch((e) => setErr(errorText(e))); }, [shot, plan && JSON.stringify(plan)]);      // eslint-disable-line react-hooks/exhaustive-deps

  const save = async (next: BlockingPlanData | null) => {
    setErr("");
    try { await onSaved({ plan: next }); await load(); } catch (e) { setErr(errorText(e)); }
  };
  const suggest = async (mode: "suggest" | "carry") => {
    if (locked) return;
    if (draft && !await ask(mode === "carry" ? "Use the same floor as the shot before? Where you put people and the camera in this shot is replaced." : "Replace this plan with a suggested layout? Where you put people and the camera is replaced.", { ok: "Replace" })) return;
    setBusy(true);
    try { const r = await load(mode); if (r.suggested) { setDraft(r.suggested); await save(r.suggested); } } catch (e) { setErr(errorText(e)); } finally { setBusy(false); }
  };

  const point = (e: React.PointerEvent): Pt => toRoom(e.clientX, e.clientY, svg.current!.getBoundingClientRect());
  const start = (kind: NonNullable<Drag>["kind"], i: number) => (e: React.PointerEvent) => {
    if (locked || !draft) return;
    e.preventDefault();
    try { (e.currentTarget as Element).setPointerCapture?.(e.pointerId); } catch { /* a pointer that cannot be captured still drags while it moves over the plan */ }
    setDrag({ kind, i });
  };
  const move = (e: React.PointerEvent) => {
    if (!drag || !draft) return;
    const p = point(e);
    const d: BlockingPlanData = JSON.parse(JSON.stringify(draft));
    if (drag.kind === "person") Object.assign(d.people[drag.i], clampRoom(p));
    else if (drag.kind === "prop") Object.assign(d.props[drag.i], clampRoom(p));
    else if (drag.kind === "face") d.people[drag.i].facing = round1(bearing(d.people[drag.i], p));
    else if (drag.kind === "cam" && d.camera) Object.assign(d.camera, clampRoom(p));
    else if (drag.kind === "aim" && d.camera) d.camera.aim = round1(bearing(d.camera, p));
    setDraft(d);
  };
  const end = () => { if (drag && draft) void save(draft); setDrag(null); };
  const setFov = (fov: number) => { if (!draft?.camera || locked) return; const d = { ...draft, camera: { ...draft.camera, fov } }; setDraft(d); void save(d); };
  const turn = (i: number, by: number) => { if (!draft || locked) return; const d: BlockingPlanData = JSON.parse(JSON.stringify(draft)); d.people[i].facing = norm360(d.people[i].facing + by); setDraft(d); void save(d); };

  const people = draft?.people ?? [];
  const cam = draft?.camera ?? null;
  const line = people.length >= 2 ? lineThrough(people[0], people[1]) : null;
  const cone = cam ? coneEdges(cam, cam.aim, cam.fov, 46) : null;
  const here = view?.crossings.find((x) => x.shot === shot);
  const ghosts = (view?.scene_shots ?? []).filter((s) => s.id !== shot && s.plan?.camera);

  return (
    <div className="bp">
      <div className="bp-bar">
        <button className="btn sm" disabled={locked || busy} onClick={() => suggest("suggest")}>Suggest a layout</button>
        {view?.has_previous && <button className="btn ghost sm" disabled={locked || busy} onClick={() => suggest("carry")}>Same floor as the shot before</button>}
        {draft && <button className="btn ghost sm" disabled={locked || busy} onClick={async () => { if (await ask("Clear this shot's blocking plan?", { ok: "Clear" })) { setDraft(null); await save(null); } }}>Clear</button>}
        <span className="dim">{locked ? "This shot's storyboard is locked, so its blocking is fixed. Unlock it to change the plan." : "A top-down view, as if from the ceiling. Drag people, the camera and the arrows."}</span>
      </div>
      {err && <p className="error-text" role="alert">{err}</p>}
      <svg ref={svg} className={`bp-room ${locked ? "locked" : ""}`} viewBox={`0 0 ${ROOM.w} ${ROOM.h}`} role="img" aria-label="Top-down blocking plan of this shot"
           onPointerMove={move} onPointerUp={end} onPointerCancel={end}>
        <defs><pattern id="bp-grid" width="10" height="10" patternUnits="userSpaceOnUse"><path d="M10 0H0V10" fill="none" stroke="rgba(244,247,250,0.06)" strokeWidth="0.25" /></pattern></defs>
        <rect x="0" y="0" width={ROOM.w} height={ROOM.h} fill="url(#bp-grid)" />
        <text x="50" y="5" className="bp-note" textAnchor="middle">far wall</text>
        <text x="50" y={ROOM.h - 1.6} className="bp-note" textAnchor="middle">near wall (the audience side)</text>
        {line && <line x1={line[0].x} y1={line[0].y} x2={line[1].x} y2={line[1].y} className={`bp-line ${here ? "cross" : ""}`} />}
        {ghosts.map((g) => <g key={g.id} className="bp-ghost"><circle cx={g.plan!.camera!.x} cy={g.plan!.camera!.y} r="1.8" /><text x={g.plan!.camera!.x + 2.6} y={g.plan!.camera!.y + 1}>{g.id.replace(/^S0*/, "")}</text></g>)}
        {cone && cam && <polygon points={`${cam.x},${cam.y} ${cone[0].x},${cone[0].y} ${cone[1].x},${cone[1].y}`} className="bp-cone" />}
        {(draft?.props ?? []).map((p, i) => <g key={p.name + i} onPointerDown={start("prop", i)} className="bp-prop"><rect x={p.x - 2} y={p.y - 2} width="4" height="4" rx="0.6" /><text x={p.x} y={p.y + 5.6} textAnchor="middle">{p.name}</text></g>)}
        {people.map((p, i) => {
          const tip = along(p, p.facing, 8.5);
          const c = COLOURS[i % COLOURS.length];
          return (
            <g key={p.name} className="bp-person">
              <line x1={p.x} y1={p.y} x2={tip.x} y2={tip.y} stroke={c} strokeWidth="0.6" />
              <circle cx={tip.x} cy={tip.y} r="1.6" fill={c} className="bp-handle" onPointerDown={start("face", i)} onDoubleClick={() => turn(i, 180)}><title>{`Drag to turn ${p.name}; double-click to turn around`}</title></circle>
              <circle cx={p.x} cy={p.y} r="3.6" fill="#10131a" stroke={c} strokeWidth="0.8" className="bp-dot" onPointerDown={start("person", i)} />
              <text x={p.x} y={p.y + 1.3} textAnchor="middle" className="bp-init" pointerEvents="none">{initials(p.name)}</text>
              <text x={p.x} y={p.y - 5.2} textAnchor="middle" className="bp-name" pointerEvents="none">{p.name}</text>
            </g>);
        })}
        {cam && (() => {
          const tip = along(cam, cam.aim, 11);
          return (
            <g className="bp-cam">
              <line x1={cam.x} y1={cam.y} x2={tip.x} y2={tip.y} stroke="#e8b45c" strokeWidth="0.5" strokeDasharray="1 1" />
              <circle cx={tip.x} cy={tip.y} r="1.6" fill="#e8b45c" className="bp-handle" onPointerDown={start("aim", 0)}><title>Drag to aim the camera</title></circle>
              <g transform={`translate(${cam.x} ${cam.y}) rotate(${cam.aim})`} onPointerDown={start("cam", 0)} className="bp-camicon"><rect x="-3.4" y="-2.4" width="5" height="4.8" rx="0.8" /><path d="M1.6 -1.6 L4.6 -3 L4.6 3 L1.6 1.6 Z" /></g>
            </g>);
        })()}
        {!draft && <g><rect x="22" y="26" width="56" height="18" rx="1" className="bp-empty" /><text x="50" y="35.5" textAnchor="middle" className="bp-emptytext">No plan yet. Press “Suggest a layout”.</text></g>}
      </svg>
      <div className="bp-side">
        {cam && <label className="field"><span>Lens width of view: {Math.round(cam.fov)}°</span>
          <input type="range" min="15" max="100" value={cam.fov} disabled={locked} onChange={(e) => setDraft({ ...draft!, camera: { ...cam, fov: Number(e.target.value) } })} onPointerUp={(e) => setFov(Number((e.target as HTMLInputElement).value))} onKeyUp={(e) => setFov(Number((e.target as HTMLInputElement).value))} />
          <span className="dim">Narrow is a close, long lens; wide takes in the room.</span></label>}
        {here && <div className="bp-warn" role="status"><b>The camera crossed the line.</b> {here.message} <span className="dim">{here.fix}</span></div>}
        <div className="bp-words"><span className="dim">What this adds to the prompt, as the camera sees it</span>
          <p>{view?.text || (draft ? "Nobody is in the camera's view yet. Aim the camera at the people." : "Nothing yet.")}</p></div>
      </div>
    </div>
  );
}
