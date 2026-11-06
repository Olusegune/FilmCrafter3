// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";
import { readFileSync } from "node:fs";
import { FilmRail, railSteps, TOOLS } from "../../FilmRail";
import type { FilmProgress } from "../../api";

beforeEach(() => { try { localStorage.removeItem("pf-rail-more"); } catch { /* none */ } });
afterEach(cleanup);

const progress = (over: Partial<{ locked: boolean; chars: number; style: boolean; shots: number; made: number; video: number }> = {}): FilmProgress => {
  const o = { locked: false, chars: 0, style: false, shots: 0, made: 0, video: 0, ...over };
  return { story: { locked: o.locked, current: 1 }, cast: { characters: o.chars, places: 0, style: o.style }, shots: { count: o.shots }, make: { shots: o.made, keyframe: 0, video: o.video } } as unknown as FilmProgress;
};
const names = () => screen.getAllByRole("button").map((b) => b.textContent);
const rail = (over: Record<string, unknown> = {}) => {
  const go = vi.fn(), tool = vi.fn(), home = vi.fn(), settings = vi.fn();
  render(<FilmRail steps={railSteps({ pro: false, progress: progress({ locked: true }), active: "cast", go })} onHome={home} onSettings={settings} onTool={tool} hasShots {...over} />);
  return { go, tool, home, settings };
};

describe("the one left rail", () => {
  it("is Home, the steps in order, the tools, More, then Settings", () => {
    rail();
    expect(names()).toEqual(["Home", "Story", "Cast", "Studio", "Export", "Project", "Library", "Looks", "Review", "AI Agent", "More", "Settings"]);
  });

  it("adds Shots in Pro mode and marks done, here and next", () => {
    render(<FilmRail steps={railSteps({ pro: true, progress: progress({ locked: true }), active: "shots", go: () => {} })} onHome={() => {}} onTool={() => {}} hasShots />);
    expect(names().slice(1, 6)).toEqual(["Story", "Cast", "Shots", "Studio", "Export"]);
    expect(screen.getByRole("button", { name: /Story/ }).querySelector("[aria-label=done]")).not.toBeNull();
    expect(screen.getByRole("button", { name: /Cast/ }).querySelector("[aria-label='next step']")).not.toBeNull();            // the first step not done
    expect(screen.getByRole("button", { name: /Shots/ })).toHaveAttribute("aria-current", "step");
    expect(screen.getByRole("button", { name: /Shots/ }).querySelector("[aria-label='next step']")).toBeNull();                // you are there: no dot
  });

  it("never marks Export as the next step and has no ticks before there is any progress", () => {
    render(<FilmRail steps={railSteps({ pro: false, progress: progress({ locked: true, chars: 2, style: true, shots: 5, made: 5, video: 5 }), active: "story", go: () => {} })} onHome={() => {}} onTool={() => {}} hasShots />);
    expect(screen.getByRole("button", { name: /Export/ }).querySelector("[aria-label='next step']")).toBeNull();
    cleanup();
    render(<FilmRail steps={railSteps({ pro: false, progress: null, active: "story", go: () => {} })} onHome={() => {}} onTool={() => {}} hasShots />);
    expect(screen.queryByLabelText("done")).toBeNull();
  });

  it("hides the less common tools until More is pressed and remembers it", () => {
    rail();
    expect(screen.queryByRole("button", { name: /Lighting/ })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: /More/ }));
    expect(names()).toContain("Lighting");
    expect(names()).toContain("Clean up");
    expect(screen.getByRole("button", { name: /Fewer/ })).toHaveAttribute("aria-expanded", "true");
    expect(localStorage.getItem("pf-rail-more")).toBe("1");
    cleanup();
    rail();
    expect(names()).toContain("Lighting");                                                                                      // remembered
  });

  it("greys a tool that needs shots, with the reason, instead of hiding it", () => {
    rail({ hasShots: false });
    const review = screen.getByRole("button", { name: /Review/ });
    expect(review).toBeDisabled();
    expect(review.getAttribute("title")).toContain("Needs a shot plan first");
    expect(screen.getByRole("button", { name: /Library/ })).toBeEnabled();
  });

  it("goes where each button says", () => {
    const { go, tool, home, settings } = rail();
    fireEvent.click(screen.getByRole("button", { name: /Studio/ }));
    fireEvent.click(screen.getByRole("button", { name: /Library/ }));
    fireEvent.click(screen.getByRole("button", { name: /Home/ }));
    fireEvent.click(screen.getByRole("button", { name: /Settings/ }));
    expect(go).toHaveBeenCalledWith("make");
    expect(tool).toHaveBeenCalledWith("library");
    expect(home).toHaveBeenCalledOnce();
    expect(settings).toHaveBeenCalledOnce();
  });

  it("shows a badge on a tool and keeps More open while one of its tools is the active one", () => {
    render(<FilmRail steps={[]} onHome={() => {}} onTool={() => {}} hasShots badges={{ review: 2 }} activeTool="layers" />);
    expect(screen.getByLabelText("2 need attention")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Layers/ })).toHaveAttribute("aria-current", "true");
  });

  it("lists every tool the Studio can open, once each", () => {
    const ids = TOOLS.map((t) => t.id);
    expect(new Set(ids).size).toBe(ids.length);
    expect(ids).toEqual(["project", "library", "looks", "review", "agent", "supervisor", "acting", "continuity", "layers", "lighting", "presets", "color", "colourmatch", "clean", "cutouts"]);
  });
});

describe("every screen of a film uses this rail and no other", () => {
  const read = (f: string) => readFileSync(`src/${f}`, "utf8");
  it("the film steps and the timeline Studio render FilmRail, and Agent Studio is given the Studio's rail", () => {
    expect(read("FilmView.tsx")).toContain("<FilmRail");
    expect(read("Studio.tsx")).toContain("<FilmRail");
    expect(read("Studio.tsx")).not.toContain('<nav className="rail"');
    const agent = read("AgentStudio.tsx");
    expect(agent).toContain("{rail}");
    expect(agent).not.toContain("<FilmRail");
  });
  it("every tool of the rail is handled by the Studio, so pressing it from another screen lands somewhere", () => {
    const studio = read("Studio.tsx");
    for (const t of TOOLS) expect(studio, t.id).toContain(`case "${t.id}"`);
  });
  it("a tool pressed in Agent Studio first goes to the Manual Studio, where the tools open (Layers did nothing there)", () => {
    const studio = read("Studio.tsx");
    expect(studio).toContain('if (workspace === "agent" && id !== "agent") chooseWorkspace("manual");');
    expect(studio).toContain('activeTool={workspace === "agent" ? "agent" : layersOpen ? "layers" : null}');
  });
});
