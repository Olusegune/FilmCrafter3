// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";

const invoke = vi.fn();
vi.mock("@tauri-apps/api/core", () => ({ invoke: (cmd: string, args: unknown) => invoke(cmd, args), convertFileSrc: (p: string) => p }));
const pick = vi.fn();
vi.mock("@tauri-apps/plugin-dialog", () => ({ open: (o: unknown) => pick(o), save: vi.fn() }));

import { cameraWedge, gapWords, planPoint, SetBuilder } from "../../SetBuilder";
import type { WlCamera, WlSet, WlView } from "../../api";

const bounds = { x: [-10, 10] as [number, number], y: [0, 10] as [number, number], z: [0, 30] as [number, number] };
const cam = (over: Partial<WlCamera> = {}): WlCamera => ({ id: "wk-1", name: "Main camera", x: 0, y: 1.6, z: 0, yaw: 0, pitch: 0, fov: 60, note: "", ...over });
const mkSet = (over: Partial<WlSet> = {}): WlSet => ({ id: "ws-1", name: "Market", version: 3, locked: false, world: { units: "m", up: "y", bounds }, assets: [{ id: "wa-1", name: "Fruit stall", kind: "landmark", x: -2, y: 0, z: 8, width: 3, height: 3, file: "worldlock/ws-1/assets/wa-1.png", pixels: [200, 200], tags: [], note: "" }],
  characters: [], cameras: [cam()], lights: [], events: [], removed: [], shots: [], environment: { time: "", weather: "", atmosphere: "" }, axis: [], can_undo: true, can_redo: false, undo_label: "Change a picture", redo_label: "", saved_versions: [], ...over });
const view = (over: Partial<WlView> = {}): WlView => ({ id: "ws-1", file: "worldlock/ws-1/views/a.png", width: 960, height: 540, camera: {}, drawn: ["wa-1"], skipped: [], uncovered: 0, coverage: 1, warnings: [], shot: null, set_version: 3, ...over });

let st: WlSet;
const backend = (_c: string, a: { action: string; data: Record<string, unknown> }) => {
  switch (a.action) {
    case "list": return Promise.resolve({ sets: [{ id: st.id, name: st.name, version: st.version, locked: st.locked, assets: st.assets.length, cameras: st.cameras.length, updated: 0 }], limits: { sets: 40, assets: 200, cameras: 30, events: 200 } });
    case "get": return Promise.resolve(a.data && "set" in (a.data as object) ? st : { shots: [{ id: "S01-01" }, { id: "S01-02" }, { id: "S02-01" }] });
    case "create": st = mkSet({ name: a.data.name as string, assets: [] }); return Promise.resolve(st);
    case "asset_add": st = { ...st, assets: [...st.assets, { ...st.assets[0], id: "wa-new", name: "Cart" }] }; return Promise.resolve({ ...st, id_: "wa-new" });
    case "asset_set": st = { ...st, assets: st.assets.map((x) => (x.id === a.data.id ? { ...x, ...(a.data as object) } : x)) }; return Promise.resolve(st);
    case "camera_set": st = a.data.id ? { ...st, cameras: st.cameras.map((c) => (c.id === a.data.id ? { ...c, ...(a.data as object) } : c)) } : { ...st, cameras: [...st.cameras, cam({ id: "wk-2", name: a.data.name as string })] }; return Promise.resolve(st);
    case "lock": st = { ...st, locked: true }; return Promise.resolve(st);
    case "unlock": st = { ...st, locked: false }; return Promise.resolve(st);
    case "render": return Promise.resolve(view(a.data.shot ? { shot: a.data.shot as string } : {}));
    case "check_move": return Promise.resolve({ steps: [], worst: { t: 0.6, uncovered: 0.4 }, ok: false, warning: "This move shows a gap of 40% of the view at 60% of the way." });
    case "check": return Promise.resolve({ issues: [{ kind: "outside", id: "wa-1", text: "'Fruit stall' stands outside the set's bounds." }], ok: false, checked: { pictures: 1, cameras: 1, events: 0 } });
    case "event_set": st = { ...st, events: [{ id: "we-1", shot: a.data.shot as string, asset: a.data.asset as string, kind: "move", to: a.data.to as never, state: a.data.state as string, note: "" }] }; return Promise.resolve(st);
    case "shot_camera": st = { ...st, shots: [{ shot: a.data.shot as string, camera: a.data.camera as string }] }; return Promise.resolve(st);
    case "version_save": st = { ...st, saved_versions: [{ number: 1, name: a.data.name as string, at: 0, set_version: 3, assets: 1 }] }; return Promise.resolve(st);
    default: return Promise.resolve(st);
  }
};
const sent = (action: string) => invoke.mock.calls.filter(([, a]) => a.action === action).map(([, a]) => a.data);
afterEach(() => { cleanup(); invoke.mockReset(); pick.mockReset(); });
const show = async (set = mkSet()) => { st = set; render(<SetBuilder dir="film" onClose={() => {}} />); await screen.findByLabelText("Sets"); };
const choose = async () => { fireEvent.change(screen.getByLabelText("Sets"), { target: { value: "ws-1" } }); await screen.findByLabelText("Set controls"); };
const tab = (n: RegExp) => fireEvent.click(screen.getByRole("tab", { name: n }));

describe("the floor plan maths", () => {
  it("puts the front left of the set at the bottom left of the plan and further in higher up", () => {
    expect(planPoint(-10, 0, bounds, 420, 320)).toEqual([14, 306]);
    expect(planPoint(10, 30, bounds, 420, 320)).toEqual([406, 14]);
    const [, y1] = planPoint(0, 5, bounds, 420, 320), [, y2] = planPoint(0, 15, bounds, 420, 320);
    expect(y2).toBeLessThan(y1);
  });
  it("draws a camera as a triangle that opens the way it looks", () => {
    const [o, l, r] = cameraWedge(cam({ yaw: 0, fov: 60 }), bounds, 420, 320, 6).split(" ").map((p) => p.split(",").map(Number));
    expect(l[0]).toBeLessThan(o[0]); expect(r[0]).toBeGreaterThan(o[0]); expect(l[1]).toBeLessThan(o[1]);
    const [, l2, r2] = cameraWedge(cam({ yaw: 90, fov: 60 }), bounds, 420, 320, 6).split(" ").map((p) => p.split(",").map(Number));
    expect(l2[0]).toBeGreaterThan(o[0]); expect(r2[0]).toBeGreaterThan(o[0]);                                   // turned right: both edges point to the right
  });
  it("says the gap in words", () => {
    expect(gapWords(view({ uncovered: 0.31 }))).toBe("31% of this view shows nothing the set has.");
    expect(gapWords(view())).toBe("The set covers this view.");
  });
});

describe("the set builder", () => {
  it("lists the sets, says nothing is generated or sent, and opens one", async () => {
    invoke.mockImplementation(backend);
    await show();
    expect(screen.getByText(/nothing is generated or sent/i)).toBeInTheDocument();
    await choose();
    expect(screen.getByText("version 3")).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "Floor plan" })).toBeInTheDocument();
    expect(sent("get").some((d) => (d as { set?: string }).set === "ws-1")).toBe(true);
  });

  it("makes a set only with a name", async () => {
    invoke.mockImplementation(backend);
    await show();
    const make = screen.getByRole("button", { name: "Make a set" });
    expect(make).toBeDisabled();
    fireEvent.change(screen.getByLabelText("New set name"), { target: { value: "Mama's kitchen" } });
    fireEvent.click(make);
    await waitFor(() => expect(sent("create")).toEqual([{ name: "Mama's kitchen" }]));
    expect(await screen.findByLabelText("Set controls")).toHaveTextContent("Mama's kitchen");
  });

  it("selects a picture on the plan and moves it by typing metres", async () => {
    invoke.mockImplementation(backend);
    await show();
    await choose();
    fireEvent.click(screen.getByTestId("asset-wa-1"));
    const box = await screen.findByLabelText("Selected picture");
    const depth = within(box).getByLabelText("Depth (m)");
    fireEvent.change(depth, { target: { value: "12" } });
    fireEvent.blur(depth);
    await waitFor(() => expect(sent("asset_set")).toEqual([{ set: "ws-1", id: "wa-1", z: 12 }]));
    fireEvent.blur(within(box).getByLabelText("Width (m)"));
    expect(sent("asset_set")).toHaveLength(1);                                                                    // an untouched field sends nothing
  });

  it("stands a chosen picture in the set and selects it", async () => {
    invoke.mockImplementation(backend);
    pick.mockResolvedValue("C:\\Pictures\\cart.png");
    await show();
    await choose();
    fireEvent.click(screen.getByRole("button", { name: /Stand a picture in the set/ }));
    await waitFor(() => expect(sent("asset_add")).toEqual([{ set: "ws-1", path: "C:\\Pictures\\cart.png", height: 2.5, z: 6 }]));
    expect(await screen.findByLabelText("Selected picture")).toHaveTextContent("Cart");
  });

  it("locks the set and then greys every change but still lets you look", async () => {
    invoke.mockImplementation(backend);
    await show();
    await choose();
    fireEvent.click(screen.getByRole("button", { name: "Lock this set" }));
    expect(await screen.findByText(/it is the approved place/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Stand a picture in the set/ })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Undo" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Unlock this set" })).toBeEnabled();
    tab(/Cameras/);
    expect(screen.getByRole("button", { name: /See from Main camera/ })).toBeEnabled();
  });

  it("sees the set from a camera as at a shot and shows a gap warning", async () => {
    invoke.mockImplementation((c: string, a: { action: string; data: Record<string, unknown> }) => (a.action === "render" ? Promise.resolve(view({ uncovered: 0.4, shot: (a.data.shot as string) ?? null, skipped: [{ id: "wa-1", why: "x" }] })) : backend(c, a)));
    await show();
    await choose();
    tab(/Cameras/);
    fireEvent.change(screen.getByLabelText("As at shot"), { target: { value: "S01-02" } });
    fireEvent.click(screen.getByRole("button", { name: "See from Main camera" }));
    await waitFor(() => expect(sent("render")).toEqual([{ set: "ws-1", camera: "wk-1", size: [960, 540], shot: "S01-02" }]));
    expect(await screen.findByAltText("The view from the camera")).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("40% of this view shows nothing the set has. As at shot S01-02.");
    expect(screen.getByText(/1 picture is not in this view \(Fruit stall\)/)).toBeInTheDocument();
  });

  it("checks a camera move between two cameras and says where it leaves the set", async () => {
    invoke.mockImplementation(backend);
    await show(mkSet({ cameras: [cam(), cam({ id: "wk-2", name: "Turned", yaw: 80 })] }));
    await choose();
    tab(/Cameras/);
    const go = screen.getByRole("button", { name: "Check the move" });
    expect(go).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Move from"), { target: { value: "wk-1" } });
    fireEvent.change(screen.getByLabelText("Move to"), { target: { value: "wk-2" } });
    fireEvent.click(go);
    expect(await screen.findByLabelText("Move check")).toHaveTextContent("gap of 40% of the view at 60% of the way");
    expect(sent("check_move")).toEqual([{ set: "ws-1", from: "wk-1", to: "wk-2", steps: 10 }]);
  });

  it("assigns a camera to a shot and records an event that changes the set at a shot", async () => {
    invoke.mockImplementation(backend);
    await show();
    await choose();
    tab(/Over the shots/);
    fireEvent.change(await screen.findByLabelText("Camera for S01-01"), { target: { value: "wk-1" } });
    await waitFor(() => expect(sent("shot_camera")).toEqual([{ set: "ws-1", shot: "S01-01", camera: "wk-1" }]));
    const rec = screen.getByRole("button", { name: "Record it" });
    expect(rec).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Event shot"), { target: { value: "S02-01" } });
    fireEvent.change(screen.getByLabelText("Event thing"), { target: { value: "wa-1" } });
    fireEvent.change(screen.getByLabelText("Event across"), { target: { value: "1.2" } });
    fireEvent.change(screen.getByLabelText("Event state"), { target: { value: "on the floor" } });
    fireEvent.click(rec);
    await waitFor(() => expect(sent("event_set")).toEqual([{ set: "ws-1", shot: "S02-01", asset: "wa-1", kind: "move", to: { x: 1.2 }, state: "on the floor" }]));
    expect(await screen.findByLabelText("Remove the event at S02-01")).toBeInTheDocument();
    expect(screen.getByText(/the set as built is never changed/)).toBeInTheDocument();
  });

  it("checks the set and lists what it found, and saves a named version", async () => {
    invoke.mockImplementation(backend);
    await show();
    await choose();
    tab(/Checks and versions/);
    fireEvent.click(screen.getByRole("button", { name: "Check the set" }));
    expect(await screen.findByLabelText("Check result")).toHaveTextContent("'Fruit stall' stands outside the set's bounds.");
    const save = screen.getByRole("button", { name: "Save this version" });
    expect(save).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Version name"), { target: { value: "Opening layout" } });
    fireEvent.click(save);
    await waitFor(() => expect(sent("version_save")).toEqual([{ set: "ws-1", name: "Opening layout" }]));
    expect(await screen.findByLabelText("Restore Opening layout")).toBeInTheDocument();
  });

  it("shows the engine's refusal in plain words", async () => {
    invoke.mockImplementation((c: string, a: { action: string; data: Record<string, unknown> }) => (a.action === "asset_set" ? Promise.reject("This set is locked. Unlock it to change it.") : backend(c, a)));
    await show();
    await choose();
    fireEvent.click(screen.getByTestId("asset-wa-1"));
    const x = within(await screen.findByLabelText("Selected picture")).getByLabelText("Across (m)");
    fireEvent.change(x, { target: { value: "3" } });
    fireEvent.blur(x);
    expect(await screen.findByRole("alert")).toHaveTextContent("This set is locked");
  });

  it("shows why it cannot load", async () => {
    invoke.mockRejectedValue("No film is open.");
    render(<SetBuilder dir="film" onClose={() => {}} />);
    expect(await screen.findByRole("alert")).toHaveTextContent("No film is open.");
  });
});
