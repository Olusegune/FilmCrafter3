// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";

const invoke = vi.fn();
vi.mock("@tauri-apps/api/core", () => ({ invoke: (cmd: string, args: unknown) => invoke(cmd, args), convertFileSrc: (p: string) => p }));

import { adviceFor, DirectorCam, moveWords } from "../../DirectorCam";
import type { DcAdvice, DcCondition, DcDraft, DcPlan, DcShot, WlCamera, WlSet } from "../../api";

const bounds = { x: [-10, 10] as [number, number], y: [0, 10] as [number, number], z: [0, 30] as [number, number] };
const cam = (over: Partial<WlCamera> = {}): WlCamera => ({ id: "wk-1", name: "Camera", x: 0, y: 1.6, z: 0, yaw: 0, pitch: 0, fov: 54, note: "", focal_mm: 35, aspect: "16:9", ...over });
const shot = (n: number, over: Partial<DcShot> = {}): DcShot => ({ id: `ds-${n}`, n, title: `Shot ${n}`, size: "medium", camera: cam(), move: { kind: "static", amount: 0, ease: "smooth" }, duration: 3, subjects: ["wc-1"], characters: [], because: ["enters"], looking_at: "Girl", notes: "",
  allow: [], approval: "suggested", film_shot: null, ...over });
const set: WlSet = { id: "ws-1", name: "Market", version: 3, locked: false, world: { units: "m", up: "y", bounds }, assets: [], characters: [{ id: "wc-1", name: "Girl", x: -2, z: 6, facing: 90, asset: null }], cameras: [cam()], lights: [], events: [], removed: [], shots: [],
  environment: { time: "", weather: "", atmosphere: "" }, axis: [], can_undo: false, can_redo: false, undo_label: "", redo_label: "", saved_versions: [] };
const advice = (over: Partial<DcAdvice> = {}): DcAdvice => ({ rule: "line", shot: "ds-2", n: 2, severity: "warning", deliberate: false, text: "The camera crosses the line between Girl and Vendor here: left and right swap on screen.", ...over });
const planOf = (shots: DcShot[], items: DcAdvice[] = [], over: Partial<DcPlan> = {}): DcPlan => ({ id: "dp-1", name: "Market arrival", beat: "The girl enters.", set: "ws-1", set_version: 3, shots, advice: { items, ok: !items.some((i) => i.severity === "warning"),
  counts: { warning: items.filter((i) => i.severity === "warning").length, advice: items.filter((i) => i.severity === "advice").length, note: items.filter((i) => i.severity === "note").length } }, set_changed: false, set_version_now: 3, ...over });
const draft: DcDraft = { beat: "The girl enters.", shots: [shot(1, { title: "Establish the place", size: "establishing" }), shot(2, { title: "Girl enters", size: "wide", move: { kind: "tracking", amount: 0, ease: "smooth" } })], people: ["Girl"], things: [], actions: ["enters"], not_found: ["dog"], note: "A draft from the words of the beat only: no model was asked and nothing is saved." };
const conds: DcCondition[] = [{ input: "last_frame", label: "Last-frame render", status: "supported", why: "documented", alternative: "" }, { input: "camera_path", label: "Camera path", status: "not supported", why: "No model here accepts a camera path as data. The motion is given in words and is approximate.", alternative: "Use the motion words and the path strip." }];

let plan: DcPlan;
let blenderFound = false;
const backend = (c: string, a: { action: string; data: Record<string, unknown> }) => {
  if (c === "film_blender") return Promise.resolve({ found: blenderFound, path: "", version: "5.2.2", note: "" });
  switch (a.action) {
    case "clip": return Promise.resolve({ shot: a.data.shot, renderer: a.data.renderer === "blender" ? "Blender 5.2.2" : "FilmCrafter", file: "worldlock/ws-1/animations/c.mp4", seconds: 3, frames: 72, size: [960, 540], took: 4.2, people_note: "People stand where the shot starts." });
    case "list": return Promise.resolve({ sets: [{ id: "ws-1", name: "Market", version: 3, locked: false, assets: 2, cameras: 1, updated: 0 }], limits: { sets: 40, assets: 200, cameras: 30, events: 200 } });
    case "get": return Promise.resolve(a.data && "set" in a.data ? set : { shots: [{ id: "S01-01" }, { id: "S01-02" }] });
    case "plans": return Promise.resolve({ plans: [{ id: "dp-1", name: "Market arrival", beat: "x", shots: plan.shots.length, approved: 0, set_version: 3, updated: 0 }] });
    case "plan_beat": return Promise.resolve(draft);
    case "plan_save": plan = planOf(draft.shots); return Promise.resolve(plan);
    case "plan_get": return Promise.resolve(plan);
    case "shot_set": plan = { ...plan, shots: plan.shots.map((s) => (s.id === a.data.shot ? { ...s, ...(a.data as object), camera: { ...s.camera, ...((a.data.camera as object) ?? {}) } } : s)) }; return Promise.resolve(plan);
    case "shot_remove": plan = { ...plan, shots: plan.shots.filter((s) => s.id !== a.data.shot) }; return Promise.resolve(plan);
    case "place_camera": return Promise.resolve({ camera: cam({ x: 1, z: 3 }), looking_at: "Girl", framing: a.data.size, because: "x" });
    case "path": return Promise.resolve({ poses: [], worst: { i: 5, uncovered: 0.4 }, ok: false, warning: "This move shows a gap of 40% of the view at step 5: the set does not cover where the camera goes." });
    case "preview": return Promise.resolve({ shot: a.data.shot, first: { file: "worldlock/ws-1/views/f.png", uncovered: 0.3 }, last: { file: "worldlock/ws-1/views/l.png", uncovered: 0 }, path: [{ x: 0, y: 1.6, z: 0, yaw: 0, pitch: 0, fov: 54 }, { x: 1, y: 1.6, z: 2, yaw: 0, pitch: 0, fov: 54 }] });
    case "package": return Promise.resolve({ shot: a.data.shot, folder: "C:\\f", relative: "worldlock/ws-1/packages/dp-1-02", files: {}, conditioning: conds, frame_gap: { first: 0.1, last: 0 }, motion_words: "The camera tracks alongside the person as they move." });
    case "capabilities": return Promise.resolve({ model: "kie/x", conditioning: conds });
    case "apply": return Promise.resolve({ plan, package: {}, film_shot: a.data.film_shot, applied: { framing: "medium", angle: "eye level", lens: "normal (35mm)", movement: "tracking" } });
    default: return Promise.resolve({});
  }
};
const sent = (action: string) => invoke.mock.calls.filter(([, a]) => a.action === action).map(([, a]) => a.data);
afterEach(() => { cleanup(); invoke.mockReset(); blenderFound = false; });
const show = async () => { plan = planOf([shot(1), shot(2)]); render(<DirectorCam dir="film" onClose={() => {}} />); await screen.findByLabelText("Set"); };
const openSet = async () => { fireEvent.change(screen.getByLabelText("Set"), { target: { value: "ws-1" } }); await screen.findByLabelText("Story beat"); };
const openPlan = async () => { await openSet(); fireEvent.change(await screen.findByLabelText("Plan"), { target: { value: "dp-1" } }); await screen.findByLabelText("Advice summary"); };

describe("words for the plan", () => {
  it("says a move in a sentence and orders the advice worst first", () => {
    expect(moveWords({ kind: "static", amount: 0, ease: "smooth" })).toBe("The camera does not move.");
    expect(moveWords({ kind: "tracking", amount: 0, ease: "smooth" })).toBe("The camera goes with the person.");
    expect(moveWords({ kind: "pan", amount: 30, ease: "smooth" })).toBe("Pan: 30 (degrees, right is positive).");
    const items = [advice({ severity: "note" }), advice({ severity: "advice", rule: "thirty" }), advice(), advice({ shot: "ds-9" })];
    expect(adviceFor(items, "ds-2").map((i) => i.severity)).toEqual(["warning", "advice", "note"]);
  });
});

describe("DirectorCam", () => {
  it("says up front that no model is asked and nothing is sent, and lists the sets", async () => {
    invoke.mockImplementation(backend);
    await show();
    expect(screen.getByText(/no model is asked and nothing is generated or sent/i)).toBeInTheDocument();
    expect(screen.getByText(/not guaranteed to match the set/i)).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "Market" })).toBeInTheDocument();
  });

  it("plans the shots of a beat as a draft, says what it could not find, and saves nothing until it is kept", async () => {
    invoke.mockImplementation(backend);
    await show();
    await openSet();
    const go = screen.getByRole("button", { name: "Plan the shots" });
    expect(go).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Story beat"), { target: { value: "The girl enters and sees the dog." } });
    fireEvent.click(go);
    const box = await screen.findByLabelText("Draft");
    expect(box).toHaveTextContent("2 shots");
    expect(box).toHaveTextContent("Not found in the set: dog.");
    expect(sent("plan_beat")).toEqual([{ set: "ws-1", beat: "The girl enters and sees the dog." }]);
    expect(sent("plan_save")).toHaveLength(0);
    expect(screen.queryByLabelText("Approval of shot 1")).toBeNull();                                          // a draft cannot be approved: it is kept first
    fireEvent.click(screen.getByRole("button", { name: "Keep this plan" }));
    await waitFor(() => expect(sent("plan_save")).toHaveLength(1));
    expect(sent("plan_save")[0]).toMatchObject({ set: "ws-1", beat: "The girl enters and sees the dog.", shots: [{ id: "ds-1" }, { id: "ds-2" }] });
    expect(await screen.findByLabelText("Approval of shot 1")).toBeInTheDocument();
  });

  it("discards a draft", async () => {
    invoke.mockImplementation(backend);
    await show();
    await openSet();
    fireEvent.change(screen.getByLabelText("Story beat"), { target: { value: "The girl enters." } });
    fireEvent.click(screen.getByRole("button", { name: "Plan the shots" }));
    await screen.findByLabelText("Draft");
    fireEvent.click(screen.getByRole("button", { name: "Discard the draft" }));
    expect(screen.queryByLabelText("Draft")).toBeNull();
    expect(sent("plan_save")).toHaveLength(0);
  });

  it("shows the shots with the advice under each and approves one", async () => {
    invoke.mockImplementation(backend);
    await show();
    plan = planOf([shot(1), shot(2)], [advice(), advice({ rule: "thirty", severity: "advice", text: "Nearly the same view as the one before." })]);
    await openPlan();
    expect(screen.getByLabelText("Advice summary")).toHaveTextContent("1 warning, 1 advice, 0 deliberate.");
    expect(screen.getByText(/Warning: The camera crosses the line/)).toBeInTheDocument();
    expect(screen.getByText(/Advice: Nearly the same view/)).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Approval of shot 2"), { target: { value: "approved" } });
    await waitFor(() => expect(sent("shot_set")).toEqual([{ set: "ws-1", plan: "dp-1", shot: "ds-2", approval: "approved" }]));
  });

  it("marks a rule as deliberate for a shot and a size choice places the camera for you", async () => {
    invoke.mockImplementation(backend);
    await show();
    await openPlan();
    fireEvent.click(screen.getByRole("button", { name: "Select shot 2" }));
    const sec = await screen.findByLabelText("Selected shot");
    fireEvent.click(within(sec).getByLabelText("Crossing the line"));
    await waitFor(() => expect(sent("shot_set")[0]).toEqual({ set: "ws-1", plan: "dp-1", shot: "ds-2", allow: ["line"] }));
    fireEvent.change(within(sec).getByLabelText("Shot size"), { target: { value: "close-up" } });
    await waitFor(() => expect(sent("place_camera")).toEqual([{ set: "ws-1", subjects: ["wc-1"], size: "close-up", focal_mm: 35 }]));
    await waitFor(() => expect(sent("shot_set").some((d) => (d as { size?: string }).size === "close-up" && (d as { camera?: { x: number } }).camera?.x === 1)).toBe(true));
  });

  it("moves a camera by typing and changes the move, the length and the picture shape", async () => {
    invoke.mockImplementation(backend);
    await show();
    await openPlan();
    fireEvent.click(screen.getByRole("button", { name: "Select shot 1" }));
    const sec = await screen.findByLabelText("Selected shot");
    const x = within(sec).getByLabelText("Camera across (m)");
    fireEvent.change(x, { target: { value: "2.5" } });
    fireEvent.blur(x);
    await waitFor(() => expect(sent("shot_set")[0]).toEqual({ set: "ws-1", plan: "dp-1", shot: "ds-1", camera: { x: 2.5 } }));
    fireEvent.change(within(sec).getByLabelText("Camera move"), { target: { value: "orbit" } });
    await waitFor(() => expect(sent("shot_set").some((d) => (d as { move?: { kind: string } }).move?.kind === "orbit")).toBe(true));
    fireEvent.change(within(sec).getByLabelText("Aspect ratio"), { target: { value: "2.39:1" } });
    await waitFor(() => expect(sent("shot_set").some((d) => (d as { camera?: { aspect?: string } }).camera?.aspect === "2.39:1")).toBe(true));
  });

  it("checks a move and says where it leaves the set", async () => {
    invoke.mockImplementation(backend);
    await show();
    await openPlan();
    fireEvent.click(screen.getByRole("button", { name: "Select shot 1" }));
    fireEvent.click(await screen.findByRole("button", { name: "Check the move" }));
    expect(await screen.findByLabelText("Move check")).toHaveTextContent("gap of 40% of the view at step 5");
    expect(sent("path")[0]).toMatchObject({ set: "ws-1", move: { kind: "static" } });
  });

  it("previews the first and last frame and says how much the set leaves uncovered", async () => {
    invoke.mockImplementation(backend);
    await show();
    await openPlan();
    fireEvent.click(screen.getByRole("button", { name: "Select shot 1" }));
    fireEvent.click(await screen.findByRole("button", { name: "Preview the first and last frame" }));
    const box = await screen.findByLabelText("Previews");
    expect(within(box).getByAltText("First frame")).toBeInTheDocument();
    expect(box).toHaveTextContent("30% not covered by the set");
    expect(sent("preview")).toEqual([{ set: "ws-1", plan: "dp-1", shot: "ds-1" }]);
  });

  it("makes a package for a chosen model and lists, input by input, what the model can take and the alternative", async () => {
    invoke.mockImplementation(backend);
    await show();
    await openPlan();
    fireEvent.click(screen.getByRole("button", { name: "Select shot 1" }));
    await screen.findByLabelText("Selected shot");
    fireEvent.change(screen.getByLabelText("Model"), { target: { value: "kling/v2-5-turbo-image-to-video-pro" } });
    fireEvent.click(screen.getByRole("button", { name: "Make the shot package" }));
    await waitFor(() => expect(sent("package")).toEqual([{ set: "ws-1", plan: "dp-1", shot: "ds-1", provider: "kie", model: "kling/v2-5-turbo-image-to-video-pro" }]));
    const list = await screen.findByLabelText("What the model can take");
    expect(list).toHaveTextContent("Last-frame render");
    expect(list).toHaveTextContent("not supported");
    expect(list).toHaveTextContent("Instead: Use the motion words and the path strip.");
    expect(screen.getByLabelText("Package")).toHaveTextContent("worldlock/ws-1/packages/dp-1-02");
    expect(screen.getByText("The package is made. Nothing was sent.")).toBeInTheDocument();
  });

  it("asks what a model can take without making anything", async () => {
    invoke.mockImplementation(backend);
    await show();
    await openPlan();
    fireEvent.click(screen.getByRole("button", { name: "Select shot 1" }));
    await screen.findByLabelText("Selected shot");
    fireEvent.click(screen.getByRole("button", { name: "What can it take?" }));
    expect(await screen.findByLabelText("What the model can take")).toBeInTheDocument();
    expect(sent("capabilities")).toEqual([{ provider: "kie", model: "" }]);
    expect(sent("package")).toHaveLength(0);
  });

  it("gives a planned shot's camera to a film shot", async () => {
    invoke.mockImplementation(backend);
    await show();
    await openPlan();
    fireEvent.click(screen.getByRole("button", { name: "Select shot 2" }));
    await screen.findByLabelText("Selected shot");
    const give = screen.getByRole("button", { name: "Give it to that shot" });
    expect(give).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Use for film shot"), { target: { value: "S01-02" } });
    fireEvent.click(give);
    await waitFor(() => expect(sent("apply")).toEqual([{ set: "ws-1", plan: "dp-1", shot: "ds-2", film_shot: "S01-02", provider: "kie", model: "" }]));
    expect(await screen.findByText("Shot S01-02 now has this camera (medium, tracking) and the first frame as a reference.")).toBeInTheDocument();
  });

  it("warns that the set has changed since the plan was made, and removes a shot", async () => {
    invoke.mockImplementation(backend);
    await show();
    plan = planOf([shot(1), shot(2)], [], { set_changed: true, set_version_now: 5 });
    await openPlan();
    expect(screen.getByRole("status")).toHaveTextContent("The set has changed since this plan was made (version 3 then, 5 now)");
    fireEvent.click(screen.getByRole("button", { name: "Select shot 2" }));
    fireEvent.click(await screen.findByRole("button", { name: "Take this shot out" }));
    await waitFor(() => expect(sent("shot_remove")).toEqual([{ set: "ws-1", plan: "dp-1", shot: "ds-2" }]));
    expect(screen.queryByLabelText("Approval of shot 2")).toBeNull();
  });

  it("draws the plan from above with one wedge per shot and selects by clicking it", async () => {
    invoke.mockImplementation(backend);
    await show();
    await openPlan();
    expect(screen.getByRole("img", { name: "Plan from above" })).toBeInTheDocument();
    fireEvent.click(screen.getByTestId("shot-2"));
    expect(await screen.findByLabelText("Selected shot")).toHaveTextContent("Shot 2: Shot 2");
  });

  it("shows the engine's refusal in plain words", async () => {
    invoke.mockImplementation((c: string, a: { action: string; data: Record<string, unknown> }) => (a.action === "plan_beat" ? Promise.reject("No action the planner knows was found in that beat.") : backend(c, a)));
    await show();
    await openSet();
    fireEvent.change(screen.getByLabelText("Story beat"), { target: { value: "Nothing happens." } });
    fireEvent.click(screen.getByRole("button", { name: "Plan the shots" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("No action the planner knows");
  });

  it("shows why it cannot load", async () => {
    invoke.mockRejectedValue("No film is open.");
    render(<DirectorCam dir="film" onClose={() => {}} />);
    expect(await screen.findByRole("alert")).toHaveTextContent("No film is open.");
  });

  it("makes a clip of a shot with FilmCrafter by default and plays it", async () => {
    invoke.mockImplementation(backend);
    await show();
    await openPlan();
    fireEvent.click(screen.getByRole("button", { name: "Select shot 1" }));
    expect(await screen.findByRole("option", { name: "Blender not found" })).toBeDisabled();
    fireEvent.click(await screen.findByRole("button", { name: "Make a clip of this shot" }));
    await waitFor(() => expect(sent("clip")).toEqual([{ set: "ws-1", plan: "dp-1", shot: "ds-1", renderer: "builtin", width: 960 }]));
    const fig = await screen.findByLabelText("Clip");
    expect(fig).toHaveTextContent("FilmCrafter · 3 s · 960×540 · People stand where the shot starts.");
  });

  it("offers Blender for the clip when Blender is there", async () => {
    blenderFound = true;
    invoke.mockImplementation(backend);
    await show();
    await openPlan();
    fireEvent.click(screen.getByRole("button", { name: "Select shot 1" }));
    await waitFor(() => expect(screen.getByRole("option", { name: /Drawn by Blender/ })).toBeEnabled());
    fireEvent.change(screen.getByLabelText("Drawn by"), { target: { value: "blender" } });
    fireEvent.click(screen.getByRole("button", { name: "Make a clip of this shot" }));
    await waitFor(() => expect(sent("clip")[0]).toMatchObject({ renderer: "blender" }));
    expect(await screen.findByLabelText("Clip")).toHaveTextContent("Blender 5.2.2");
  });
});
