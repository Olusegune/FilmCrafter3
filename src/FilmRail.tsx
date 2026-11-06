import { useState, type ReactNode } from "react";
import * as I from "./icons";
import type { FilmProgress } from "./api";
import { STAGES, stageDone } from "./storyView";

export type ToolId = "project" | "library" | "looks" | "review" | "agent" | "supervisor" | "acting" | "continuity" | "layers" | "lighting" | "presets" | "color" | "colourmatch" | "clean";
export type RailStep = { id: string; label: string; icon: ReactNode; active?: boolean; done?: boolean; next?: boolean; disabled?: boolean; title?: string; onClick?: () => void };

const NEEDS = "Needs a shot plan first: make the shots in the Shots or Studio step.";

/** Every tool of the rail, in the order it is shown. The same list is used on every screen of a film, so the rail never changes as you move around. A tool that cannot act yet is greyed with the reason, never hidden. */
export const TOOLS: { id: ToolId; label: string; icon: ReactNode; more?: boolean; needsShots?: boolean; why?: string }[] = [
  { id: "project", label: "Project", icon: <I.Folder /> },
  { id: "library", label: "Library", icon: <I.Assets /> },
  { id: "looks", label: "Looks", icon: <I.Mountain /> },
  { id: "review", label: "Review", icon: <I.Review />, needsShots: true, why: NEEDS },
  { id: "agent", label: "AI Agent", icon: <I.Wand />, why: "Give FilmCrafter an instruction, review its plan and approve production milestones." },
  { id: "supervisor", label: "Supervisor", icon: <I.Wand />, more: true, needsShots: true, why: NEEDS },
  { id: "acting", label: "Acting", icon: <I.User />, more: true, needsShots: true, why: NEEDS },
  { id: "continuity", label: "Continuity", icon: <I.Film />, more: true, needsShots: true, why: NEEDS },
  { id: "layers", label: "Layers", icon: <I.Layers />, more: true, needsShots: true, why: NEEDS },
  { id: "lighting", label: "Lighting", icon: <I.Light />, more: true, needsShots: true, why: NEEDS },
  { id: "presets", label: "Presets", icon: <I.Wand />, more: true, needsShots: true, why: NEEDS },
  { id: "color", label: "Color", icon: <I.Sliders />, more: true, needsShots: true, why: NEEDS },
  { id: "colourmatch", label: "Colour match", icon: <I.Lens />, more: true, needsShots: true, why: NEEDS },
  { id: "clean", label: "Clean up", icon: <I.Trash />, more: true, needsShots: true, why: NEEDS },
];

const moreStored = (): boolean => { try { return localStorage.getItem("pf-rail-more") === "1"; } catch { return false; } };

/**
 * The one left rail of a film, used by every screen of it (the story, cast, shots, studio and export steps, the timeline Studio and Agent Studio). Top to bottom: Home, the steps of the golden path in order
 * (a tick when a step is done, a dot on the one to do next), the tools, a More/Fewer switch for the less common tools, and Settings. What a tool does is decided by the screen it is pressed on:
 * the timeline Studio opens it in place, any other screen takes you to the Studio with it open.
 */
export function FilmRail({ steps, onHome, onSettings, onTool, hasShots, activeTool, badges, alwaysMore }: {
  steps: RailStep[]; onHome: () => void; onSettings?: () => void; onTool: (id: ToolId) => void; hasShots: boolean; activeTool?: ToolId | null; badges?: Partial<Record<ToolId, number>>; alwaysMore?: boolean;
}) {
  const [more, setMore] = useState(moreStored);
  const toggle = () => setMore((v) => { try { localStorage.setItem("pf-rail-more", v ? "0" : "1"); } catch { /* remembering it is a convenience only */ } return !v; });
  const shownMore = more || !!alwaysMore || (!!activeTool && !!TOOLS.find((t) => t.id === activeTool)?.more);
  const tool = (t: (typeof TOOLS)[number]) => {
    const off = !!t.needsShots && !hasShots, n = badges?.[t.id];
    return (
      <button key={t.id} data-k={t.id} className={activeTool === t.id ? "active" : ""} disabled={off} onClick={() => onTool(t.id)} title={off ? `${t.label}: ${t.why}` : t.why ? `${t.label}: ${t.why}` : t.label} aria-current={activeTool === t.id ? "true" : undefined}>
        {t.icon}<span>{t.label}</span>{n ? <i className="rail-badge" aria-label={`${n} need attention`}>{n}</i> : null}
      </button>);
  };
  return (
    <nav className="rail film-rail" aria-label="Main">
      <div className="logo"><I.Mark size={26} /></div>
      <button data-k="home" onClick={onHome} title="Home: all your films"><I.Home /><span>Home</span></button>
      <div className="rail-sep" role="separator" />
      {steps.map((it) => (
        <button key={it.id} data-k={it.id} className={[it.active ? "active" : "", it.done ? "done" : "", it.next ? "next" : ""].filter(Boolean).join(" ")} disabled={it.disabled} onClick={it.onClick}
                title={it.title ?? it.label} aria-current={it.active ? "step" : undefined}>
          {it.icon}<span>{it.label}</span>
          {it.done ? <i className="rail-tick" aria-label="done"><I.Check size={9} /></i> : it.next ? <i className="rail-next" aria-label="next step" /> : null}
        </button>))}
      <div className="rail-sep" role="separator" />
      {TOOLS.filter((t) => !t.more).map(tool)}
      <button data-k="more" className="rail-more" aria-expanded={shownMore} onClick={toggle} title="The tools a first film does not need: Supervisor, Acting, Continuity, Layers, Lighting, Presets, Color, Colour match and Clean up."><I.Sliders /><span>{shownMore ? "Fewer" : "More"}</span></button>
      {shownMore && <><div className="rail-sep" role="separator" />{TOOLS.filter((t) => t.more).map(tool)}</>}
      <div className="spacer" />
      {onSettings && <button data-k="settings" onClick={onSettings} title="Settings"><I.Gear /><span>Settings</span></button>}
    </nav>
  );
}

const STEP_ICON: Record<string, ReactNode> = { story: <I.Script />, cast: <I.User />, shots: <I.Film />, make: <I.Studio />, export: <I.Export /> };

/** The steps of the golden path for the rail: Story, Cast, Shots (Pro only), Studio, Export. `active` is the step the screen belongs to; the first step not done yet (before Export) carries the "next" dot. */
export function railSteps({ pro, progress, active, go, disabled }: { pro: boolean; progress: FilmProgress | null; active: string; go: (id: string) => void; disabled?: Partial<Record<string, string>> }): RailStep[] {
  const list = STAGES.filter((s) => s.ready && (pro || s.id !== "shots"));
  const done = list.filter((s) => stageDone(s.id, progress)).map((s) => s.id);
  const nextId = list.find((s) => !done.includes(s.id) && s.id !== "export")?.id;
  return list.map((s, i) => ({ id: s.id, label: s.id === "cast" ? "Cast" : s.label, icon: STEP_ICON[s.id], active: s.id === active, done: done.includes(s.id), next: s.id === nextId && s.id !== active, disabled: !!disabled?.[s.id],
    title: disabled?.[s.id] ?? `Step ${i + 1}: ${s.label}${done.includes(s.id) ? " (done)" : s.id === nextId ? " (next)" : ""}`, onClick: () => go(s.id) }));
}
