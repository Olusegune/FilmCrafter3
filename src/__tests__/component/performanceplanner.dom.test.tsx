// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";

const invoke = vi.fn();
vi.mock("@tauri-apps/api/core", () => ({ invoke: (cmd: string, args: unknown) => invoke(cmd, args), convertFileSrc: (p: string) => p }));

import { gapLabel, PerformancePlanner, tagWords } from "../../PerformancePlanner";
import type { PerformPlan, PerformPlanView } from "../../api";

const WORDS = ["I", "did", "not", "think", "you", "would", "come", "back"];
const blank = (over: Partial<PerformPlan> = {}): PerformPlan => ({ objective: "", subtext: "", outward: "", concealed: "", direction: "", arc: [], events: [], pauses: [], emphasis: [],
  physical: { activity: "still", effort: 0, fatigue: 0, pain: 0, breathlessness: 0, note: "" }, pace: 1, approved: false, ...over });
const view = (over: Partial<PerformPlanView> = {}, plan = blank()): PerformPlanView => ({ shot: "S01-01", person: "Chloe", text: WORDS.join(" "), words: WORDS, plan, saved: false, stale: false, applied: false, voice_model: "eleven_v4",
  compiled: { model: "eleven_v4", tagged: true, text: WORDS.join(" "), tags: [], unverified: [], not_carried: [], speed: 1, words: WORDS, stripped_tags: 0 },
  events: { gasp: { tag: "gasps", verified: true, group: "emotion" }, grunt: { tag: "grunts", verified: false, group: "effort" }, laugh: { tag: "laughs", verified: true, group: "laughter" }, breath: { tag: "exhales", verified: false, group: "breathing" } },
  emotions: { neutral: { tag: "", verified: true }, sad: { tag: "sad", verified: false } }, activities: ["still", "running", "eating"], ...over });

let current: PerformPlanView;
const backend = (_c: string, a: { action: string; data: Record<string, unknown> }) => {
  switch (a.action) {
    case "get": return Promise.resolve(current);
    case "set": current = view({ saved: true, compiled: { ...current.compiled, text: "I did [gasps] not think you would come back", tags: ["gasps"] } }, a.data.plan as PerformPlan); return Promise.resolve(current);
    case "apply": current = { ...current, applied: true, spoken_version: current.compiled.text }; return Promise.resolve(current);
    case "clear": current = view(); return Promise.resolve(current);
    default: return Promise.resolve({});
  }
};
const sent = (action: string) => invoke.mock.calls.filter(([, a]) => a.action === action).map(([, a]) => a.data);
const open = async (onChanged = () => {}) => { render(<PerformancePlanner dir="film" shotId="S01-01" who="Chloe" onChanged={onChanged} />); fireEvent.click(screen.getByRole("button", { name: "Plan the performance…" })); await screen.findByLabelText("What the model will read"); };
afterEach(() => { cleanup(); invoke.mockReset(); });

describe("the performance planner", () => {
  it("names a position in the line in words, and marks unchecked tags", () => {
    expect(gapLabel(WORDS, 0)).toBe("before the first word");
    expect(gapLabel(WORDS, 3)).toBe('after "not"');
    expect(gapLabel(WORDS, 8)).toBe('after "back" (the end)');
    expect(tagWords(["gasps", "grunts"], ["grunts"])).toBe("gasps, grunts (not checked)");
  });

  it("asks the engine for nothing until it is opened", () => {
    invoke.mockImplementation(backend);
    render(<PerformancePlanner dir="film" shotId="S01-01" who="Chloe" onChanged={() => {}} />);
    expect(invoke).not.toHaveBeenCalled();
    expect(screen.getByText(/Free; nothing is spoken until you press Speak/)).toBeInTheDocument();
  });

  it("builds a plan from sounds, feelings and stressed words, saves exactly that, and shows the compiled words", async () => {
    current = view();
    invoke.mockImplementation(backend);
    await open();
    expect(screen.getByRole("button", { name: "Save the plan" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Add a sound" }));
    fireEvent.change(screen.getByLabelText("Sound 1"), { target: { value: "gasp" } });
    fireEvent.change(screen.getByLabelText("Where sound 1 falls"), { target: { value: "2" } });
    fireEvent.click(screen.getByRole("button", { name: "Add a change of feeling" }));
    fireEvent.change(screen.getByLabelText("Feeling 1"), { target: { value: "sad" } });
    fireEvent.click(screen.getByRole("button", { name: "did" }));
    fireEvent.click(screen.getByRole("button", { name: "Save the plan" }));
    await waitFor(() => expect(sent("set")).toHaveLength(1));
    const plan = (sent("set")[0] as { plan: PerformPlan }).plan;
    expect(plan.events).toEqual([{ kind: "gasp", after_word: 2, intensity: 0.5 }]);
    expect(plan.arc).toMatchObject([{ at: 0, emotion: "sad" }]);
    expect(plan.emphasis).toEqual([1]);
    expect(await screen.findByText("I did [gasps] not think you would come back")).toBeInTheDocument();
    expect(screen.getByText(/Directions used: gasps/)).toBeInTheDocument();
  });

  it("labels sounds nobody has checked, grouped, and lists what the model cannot carry", async () => {
    current = view({ compiled: { model: "eleven_multilingual_v2", tagged: false, text: "I did not", tags: [], unverified: [], speed: 1, words: WORDS, stripped_tags: 0,
      not_carried: [{ what: "gasp after word 3", why: "This model would speak the sound's name aloud." }] } }, blank({ events: [{ kind: "grunt", after_word: 1, intensity: 0.5 }] }));
    invoke.mockImplementation(backend);
    await open();
    const opt = within(screen.getByLabelText("Sound 1")).getByRole("option", { name: "grunt (not checked)" });
    expect(opt).toBeInTheDocument();
    expect(within(screen.getByLabelText("Sound 1")).getByRole("option", { name: "gasp" })).toBeInTheDocument();
    const nc = screen.getByLabelText("Not carried");
    expect(within(nc).getByText(/gasp after word 3/)).toBeInTheDocument();
    expect(screen.getByText(/would speak \[tags\] aloud, so none are used/)).toBeInTheDocument();
  });

  it("applies only a saved, approved, current plan, and says when it is already the spoken version", async () => {
    current = view({ saved: true }, blank({ events: [{ kind: "gasp", after_word: 2, intensity: 0.5 }] }));
    invoke.mockImplementation(backend);
    const changed = vi.fn();
    await open(changed);
    const use = screen.getByRole("button", { name: "Use as the spoken version" });
    expect(use).toBeDisabled();                                                   // not approved yet
    fireEvent.click(screen.getByLabelText("I approve this plan"));
    expect(use).toBeDisabled();                                                   // the approval is not saved yet
    fireEvent.click(screen.getByRole("button", { name: "Save the plan" }));
    await waitFor(() => expect(sent("set")).toHaveLength(1));
    const use2 = await screen.findByRole("button", { name: "Use as the spoken version" });
    await waitFor(() => expect(use2).toBeEnabled());
    fireEvent.click(use2);
    await waitFor(() => expect(sent("apply")).toHaveLength(1));
    expect(await screen.findByRole("button", { name: "This is the spoken version" })).toBeDisabled();
    expect(changed).toHaveBeenCalled();
    expect(sent("apply")[0]).toEqual({ shot: "S01-01", speaker: "Chloe" });
  });

  it("warns when the line changed after the plan was made and will not apply it", async () => {
    current = view({ saved: true, stale: true }, blank({ approved: true }));
    invoke.mockImplementation(backend);
    await open();
    expect(screen.getByRole("alert")).toHaveTextContent("changed after this plan was made");
    expect(screen.getByRole("button", { name: "Use as the spoken version" })).toBeDisabled();
  });

  it("forgets the plan only when asked, and shows the engine's own words on failure", async () => {
    current = view({ saved: true }, blank());
    invoke.mockImplementation((c: string, a: { action: string; data: Record<string, unknown> }) => (a.action === "clear" ? Promise.reject("That person has no written line in that shot.") : backend(c, a)));
    await open();
    fireEvent.click(screen.getByRole("button", { name: "Forget the plan" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("no written line");
  });
});
