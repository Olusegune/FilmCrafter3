// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";

const invoke = vi.fn();
vi.mock("@tauri-apps/api/core", () => ({ invoke: (cmd: string, args: unknown) => invoke(cmd, args), convertFileSrc: (p: string) => p }));
const pick = vi.fn();
vi.mock("@tauri-apps/plugin-dialog", () => ({ open: (o: unknown) => pick(o), save: vi.fn() }));

import { SetBuilder } from "../../SetBuilder";
import type { WlModel, WlSet } from "../../api";

const bounds = { x: [-10, 10] as [number, number], y: [0, 10] as [number, number], z: [0, 30] as [number, number] };
const model = (over: Partial<WlModel> = {}): WlModel => ({ id: "wm-1", name: "Tomb", file: "worldlock/ws-1/models/wm-1.glb", x: 0, y: 0, z: 8, yaw: 0, pitch: 0, roll: 0, scale: 1, parent: null, visible: true, solid: true,
  summary: { triangles: 1200, bbox: [[0, 0, 0], [3, 2, 2]], size: [3, 2, 2], warnings: ["Animations are ignored."], materials: 2, textures: 0 }, ...over });
let st: WlSet;
const mk = (over: Partial<WlSet> = {}): WlSet => ({ id: "ws-1", name: "Garden", version: 4, locked: false, world: { units: "m", up: "y", bounds }, assets: [], characters: [], cameras: [], lights: [], events: [], removed: [], shots: [], environment: { time: "", weather: "", atmosphere: "" },
  axis: [], can_undo: false, can_redo: false, undo_label: "", redo_label: "", saved_versions: [], models: [model()], groups: [], ground: { visible: false, y: 0, colours: ["#c9c4b8", "#8d887c"], extent: 60 }, sky: { top: null, horizon: null, fog: 0 }, ...over });
const backend = (_c: string, a: { action: string; data: Record<string, unknown> }) => {
  switch (a.action) {
    case "list": return Promise.resolve({ sets: [{ id: "ws-1", name: "Garden", version: 4, locked: st.locked, assets: 0, cameras: 0, updated: 0 }], limits: { sets: 40, assets: 200, cameras: 30, events: 200 } });
    case "get": return Promise.resolve(a.data && "set" in a.data ? st : { shots: [] });
    case "model_add": st = { ...st, models: [...(st.models ?? []), model({ id: "wm-2", name: "Stone", summary: { ...model().summary, warnings: [] } })] }; return Promise.resolve({ ...st, id: "wm-2" });
    case "model_set": st = { ...st, models: (st.models ?? []).map((m) => (m.id === a.data.id ? { ...m, ...(a.data as object) } : m)) }; return Promise.resolve(st);
    case "model_remove": st = { ...st, models: (st.models ?? []).filter((m) => m.id !== a.data.id) }; return Promise.resolve(st);
    case "ground_set": st = { ...st, ground: { ...st.ground!, ...(a.data as object) } }; return Promise.resolve(st);
    case "sky_set": st = { ...st, sky: { ...st.sky!, ...(a.data as object) } }; return Promise.resolve(st);
    case "group_set": st = { ...st, groups: [...(st.groups ?? []), { id: "wg-1", name: a.data.name as string, x: 0, y: 0, z: 0, yaw: 0, pitch: 0, roll: 0, scale: 1, parent: null }] }; return Promise.resolve(st);
    case "views3d": return Promise.resolve({ views: ["Front", "Side", "Reverse", "Elevated"].map((n, i) => ({ name: n, id: "ws-1", file: `worldlock/ws-1/views/${i}.png`, width: 480, height: 270, camera: {}, drawn: ["wm-1"], skipped: [], uncovered: i === 3 ? 0.3 : 0, coverage: 1, warnings: [], shot: null, set_version: 4 })), target: [0, 1, 8], distance: 9 });
    case "collisions": return Promise.resolve({ issues: [{ kind: "overlap", ids: ["wm-1", "wm-2"], depth_m: 0.5, text: "'Tomb' and 'Stone' overlap by 0.50 m (their boxes)." }], ok: false, measured: "world boxes of the models", checked: { models: 2, cameras: 0 } });
    case "status": return Promise.resolve({ found: false, path: "", version: "", note: "Blender was not found. It is optional: FilmCrafter draws 3D sets without it." });
    case "export": return Promise.resolve({ found: false, path: "", version: "", note: "", relative: "worldlock/ws-1/blender", script: "build_scene.py", ran: false, rendered: [] });
    default: return Promise.resolve(st);
  }
};
const sent = (action: string) => invoke.mock.calls.filter(([, a]) => a.action === action).map(([, a]) => a.data);
afterEach(() => { cleanup(); invoke.mockReset(); pick.mockReset(); });
const show = async (set = mk()) => { st = set; render(<SetBuilder dir="film" onClose={() => {}} />); await screen.findByLabelText("Sets"); fireEvent.change(screen.getByLabelText("Sets"), { target: { value: "ws-1" } }); await screen.findByLabelText("Set controls"); fireEvent.click(screen.getByRole("tab", { name: "3D" })); await screen.findByLabelText("3D"); };

describe("the 3D tab of the set builder", () => {
  it("says what the renderer is and is not, and lists the models with their size and what was ignored", async () => {
    invoke.mockImplementation(backend);
    await show();
    expect(screen.getByText(/flat shading under the set's lights, no shadows, no animation/)).toBeInTheDocument();
    const li = screen.getByLabelText("Model Tomb");
    expect(li).toHaveTextContent("1,200 triangles · 3 × 2 × 2 m");
    expect(li).toHaveTextContent("Animations are ignored.");
  });

  it("stands a chosen model in the set and reports what the reader ignored", async () => {
    invoke.mockImplementation(backend);
    pick.mockResolvedValue("C:\\Models\\stone.glb");
    await show();
    fireEvent.click(screen.getByRole("button", { name: /Stand a 3D model in the set/ }));
    await waitFor(() => expect(sent("model_add")).toEqual([{ set: "ws-1", path: "C:\\Models\\stone.glb", y: 0, z: 6 }]));
    expect(pick.mock.calls[0][0].filters[0].extensions).toEqual(["glb", "gltf"]);
    expect(await screen.findByLabelText("Model Stone")).toBeInTheDocument();
  });

  it("moves, turns and scales a model by typing, sends nothing for an untouched field, and hides or removes it", async () => {
    invoke.mockImplementation(backend);
    await show();
    const turn = screen.getByLabelText("Tomb turn (°)");
    fireEvent.change(turn, { target: { value: "90" } });
    fireEvent.blur(turn);
    await waitFor(() => expect(sent("model_set")).toEqual([{ set: "ws-1", id: "wm-1", yaw: 90 }]));
    fireEvent.blur(screen.getByLabelText("Tomb size (×)"));
    expect(sent("model_set")).toHaveLength(1);
    fireEvent.click(within(screen.getByLabelText("Model Tomb")).getByRole("checkbox", { name: "Shown" }));
    await waitFor(() => expect(sent("model_set")[1]).toEqual({ set: "ws-1", id: "wm-1", visible: false }));
    fireEvent.click(screen.getByRole("button", { name: "Remove Tomb" }));
    await waitFor(() => expect(sent("model_remove")).toEqual([{ set: "ws-1", id: "wm-1" }]));
    expect(await screen.findByText("No 3D models yet.")).toBeInTheDocument();
  });

  it("shows the ground and sets the sky and the fog", async () => {
    invoke.mockImplementation(backend);
    await show();
    fireEvent.click(screen.getByRole("checkbox", { name: /Show the ground/ }));
    await waitFor(() => expect(sent("ground_set")).toEqual([{ set: "ws-1", visible: true }]));
    fireEvent.change(screen.getByLabelText("Sky overhead"), { target: { value: "#102050" } });
    await waitFor(() => expect(sent("sky_set")[0]).toEqual({ set: "ws-1", top: "#102050" }));
    const fog = screen.getByLabelText("Fog (0 to 1)");
    fireEvent.change(fog, { target: { value: "0.05" } });
    fireEvent.blur(fog);
    await waitFor(() => expect(sent("sky_set")[1]).toEqual({ set: "ws-1", fog: 0.05 }));
  });

  it("makes a group and then offers it on each model", async () => {
    invoke.mockImplementation(backend);
    await show();
    expect(screen.queryByLabelText("Group of Tomb")).toBeNull();
    const make = screen.getByRole("button", { name: "Make a group" });
    expect(make).toBeDisabled();
    fireEvent.change(screen.getByLabelText("New group name"), { target: { value: "Garden" } });
    fireEvent.click(make);
    await waitFor(() => expect(sent("group_set")).toEqual([{ set: "ws-1", name: "Garden" }]));
    fireEvent.change(await screen.findByLabelText("Group of Tomb"), { target: { value: "wg-1" } });
    await waitFor(() => expect(sent("model_set")).toEqual([{ set: "ws-1", id: "wm-1", parent: "wg-1" }]));
  });

  it("shows the four sides and says how much of one is empty", async () => {
    invoke.mockImplementation(backend);
    await show();
    fireEvent.click(screen.getByRole("button", { name: "See it from four sides" }));
    const box = await screen.findByLabelText("Four views");
    expect(within(box).getAllByRole("img").map((i) => i.getAttribute("alt"))).toEqual(["Front view", "Side view", "Reverse view", "Elevated view"]);
    expect(box).toHaveTextContent("Elevated · 30% empty");
    expect(sent("views3d")).toEqual([{ set: "ws-1", size: [480, 270] }]);
  });

  it("lists collisions in plain words and says they are measured on boxes", async () => {
    invoke.mockImplementation(backend);
    await show();
    fireEvent.click(screen.getByRole("button", { name: "Check for collisions" }));
    expect(await screen.findByLabelText("Collision result")).toHaveTextContent("'Tomb' and 'Stone' overlap by 0.50 m (their boxes).");
  });

  it("looks for Blender without installing anything and writes the script, saying what comes across", async () => {
    invoke.mockImplementation(backend);
    await show();
    fireEvent.click(screen.getByRole("button", { name: "Look for Blender" }));
    expect(await screen.findByLabelText("Blender")).toHaveTextContent("It is optional");
    fireEvent.click(screen.getByRole("button", { name: "Write the Blender script" }));
    await waitFor(() => expect(sent("export")).toEqual([{ set: "ws-1" }]));
    expect(await screen.findByText(/experimental: the models and cameras come across/)).toBeInTheDocument();
    expect(invoke.mock.calls.every(([cmd]) => ["film_worldlock", "film_blender", "film_shots"].includes(cmd))).toBe(true);
  });

  it("greys every change on a locked set", async () => {
    invoke.mockImplementation(backend);
    await show(mk({ locked: true }));
    expect(screen.getByRole("button", { name: /Stand a 3D model in the set/ })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Remove Tomb" })).toBeDisabled();
    expect(screen.getByRole("checkbox", { name: /Show the ground/ })).toBeDisabled();
    expect(screen.getByRole("button", { name: "See it from four sides" })).toBeEnabled();
  });

  it("opens an older set that has no 3D fields", async () => {
    invoke.mockImplementation(backend);
    await show(mk({ models: undefined, groups: undefined, ground: undefined, sky: undefined }));
    expect(screen.getByText("No 3D models yet.")).toBeInTheDocument();
  });
});
