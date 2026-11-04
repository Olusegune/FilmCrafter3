import { useEffect, useState } from "react";
import { api, type AgentStudioState, type LoadedProject } from "./api";
import "./film-guide.css";

export function FilmGuide({ project, onOpen }: { project: LoadedProject; onOpen: () => void }) {
  const key = `fc-guide:${project.dir}`;
  const [open, setOpen] = useState(() => { try { return localStorage.getItem(key) !== "hidden"; } catch { return true; } });
  const [expanded, setExpanded] = useState(false);
  const [state, setState] = useState<AgentStudioState | null>(null);
  useEffect(() => { api.agentStudio(project.dir, "state").then(setState).catch(() => {}); }, [project.dir]);
  const hide = () => { setOpen(false); setExpanded(false); try { localStorage.setItem(key, "hidden"); } catch { /* optional */ } };
  const show = () => { setOpen(true); try { localStorage.setItem(key, "shown"); } catch { /* optional */ } };
  const current = state?.stages.find((s) => s.id === state.current);
  const ready = state?.stages.filter((s) => s.state === "complete").length ?? 0;
  if (!open) return <button className="film-guide-restore" onClick={show} aria-label="Show Film Guide" title="Show Film Guide"><GuideOrb /></button>;
  return <aside className={`film-guide ${expanded ? "expanded" : ""}`} aria-label="Film Guide">
    <button className="film-guide-orb" onClick={() => setExpanded((v) => !v)} aria-expanded={expanded} aria-label={expanded ? "Minimize Film Guide" : "Open Film Guide"}><GuideOrb /></button>
    {expanded && <div className="film-guide-panel"><header><div><b>Film Guide</b><span>{state?.paused ? "Paused" : current?.label ?? "Ready to help"}</span></div><button onClick={hide} aria-label="Hide Film Guide">×</button></header>
      <div className="guide-progress"><span style={{ width: `${Math.max(6, ready / 8 * 100)}%` }} /></div>
      <p>{!state || state.stages.every((s) => s.state === "not_started") ? "Give me your story. I’ll analyse it, suggest a visual direction, and wait for your decisions before building the film." : current?.state === "needs_approval" ? `Your ${current.label.toLowerCase()} is ready for review.` : `I’m tracking ${current?.label.toLowerCase() ?? "your production"}. Approved work stays protected.`}</p>
      <button className="btn hero" onClick={onOpen}>Open Agent Studio</button><small>You can hide me at any time. AI and generation costs are never approved silently.</small>
    </div>}
  </aside>;
}

function GuideOrb() { return <span className="guide-aperture" aria-hidden="true"><i /><i /><i /><i /><i /><i /></span>; }
