// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";

const invoke = vi.fn();
vi.mock("@tauri-apps/api/core", () => ({ invoke: (cmd: string, args: unknown) => invoke(cmd, args), convertFileSrc: (p: string) => p }));
const pick = vi.fn();
vi.mock("@tauri-apps/plugin-dialog", () => ({ open: (o: unknown) => pick(o), save: vi.fn() }));

import { PlaceSet } from "../../PlaceSet";
import type { PlaceSetStatus } from "../../api";

const none = (over: Partial<PlaceSetStatus> = {}): PlaceSetStatus => ({ place: "e_kitchen", name: "Kitchen", pictures: 2, blender: { found: true, version: "5.2.2" }, next: "Make a set from this place's pictures: one press, and you can change it later.", set: null, ...over });
const made = (mode: "pictures" | "model" | "blender", over: Partial<NonNullable<PlaceSetStatus["set"]>> = {}): PlaceSetStatus => none({ next: "The set is ready: look from the camera, or plan the shots.", set: { id: "ws-1", name: "Kitchen", version: 2, locked: false, mode, pictures: 2, models: mode === "pictures" ? 0 : 1, cameras: 1, ...over } });
let st: PlaceSetStatus;
const backend = (_c: string, a: { action: string; data: Record<string, unknown> }) => {
  switch (a.action) {
    case "status": return Promise.resolve(st);
    case "from_pictures": st = made("pictures"); return Promise.resolve(st);
    case "from_model": st = made("model"); return Promise.resolve(st);
    case "from_blend": st = made("blender"); return Promise.resolve(st);
    case "blender_new": st = made("blender", { models: 0 }); return Promise.resolve(st);
    case "bring_back": st = made("blender"); return Promise.resolve(st);
    case "open_blender": return Promise.resolve({ opened: "x" });
    case "preview": return Promise.resolve({ set: "ws-1", file: "worldlock/ws-1/views/a.png", uncovered: 0.3, warnings: [] });
    case "unlink": st = none(); return Promise.resolve(st);
    default: return Promise.resolve({});
  }
};
const sent = (action: string) => invoke.mock.calls.filter(([, a]) => a.action === action).map(([, a]) => a.data);
const show = async (s: PlaceSetStatus, pictures = 2, extra: { onOpenSet?: (id: string) => void; onPlan?: (id: string) => void } = {}) => { st = s; invoke.mockImplementation(backend); render(<PlaceSet dir="film" place="e_kitchen" name="Kitchen" pictures={pictures} onOpenSet={extra.onOpenSet ?? (() => {})} onPlan={extra.onPlan ?? (() => {})} />); await screen.findByLabelText("Set for this place"); };
afterEach(() => { cleanup(); invoke.mockReset(); pick.mockReset(); });

describe("the set for a place", () => {
  it("offers two plain ways in, pictures first, and says what the picture way needs", async () => {
    await show(none());
    await screen.findByLabelText("From pictures");
    expect(screen.getByRole("button", { name: "Make a set from 2 pictures" })).toBeEnabled();
    expect(screen.getByLabelText("From 3D")).toHaveTextContent("For power users");
  });

  it("makes the set from the pictures in one press and then shows what was made", async () => {
    await show(none());
    fireEvent.click(await screen.findByRole("button", { name: "Make a set from 2 pictures" }));
    await waitFor(() => expect(sent("from_pictures")).toEqual([{ place: "e_kitchen" }]));
    expect(await screen.findByText("From pictures")).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("The set is ready");
  });

  it("will not offer the picture way with no pictures and says to add one", async () => {
    await show(none({ pictures: 0, next: "Add a picture to this place, or use a 3D model, or make it in Blender." }), 0);
    expect(await screen.findByRole("button", { name: "Add a picture first" })).toBeDisabled();
  });

  it("takes a model file with the right filters and a Blender file with its own", async () => {
    await show(none());
    pick.mockResolvedValueOnce("C:\M\room.glb");
    fireEvent.click(await screen.findByRole("button", { name: "Choose a model…" }));
    await waitFor(() => expect(sent("from_model")).toEqual([{ place: "e_kitchen", path: "C:\M\room.glb" }]));
    expect(pick.mock.calls[0][0].filters[0].extensions).toEqual(["glb", "gltf"]);
    fireEvent.click(await screen.findByRole("button", { name: "Take the link off" }));
    pick.mockResolvedValueOnce("C:\M\room.blend");
    fireEvent.click(await screen.findByRole("button", { name: "From a Blender file…" }));
    await waitFor(() => expect(sent("from_blend")).toEqual([{ place: "e_kitchen", path: "C:\M\room.blend" }]));
    expect(pick.mock.calls[1][0].filters[0].extensions).toEqual(["blend"]);
  });

  it("greys the Blender ways, with the reason, when Blender is not there, and still offers pictures and models", async () => {
    await show(none({ blender: { found: false, version: "" } }));
    expect(await screen.findByRole("button", { name: "From a Blender file…" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Build it in Blender" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Choose a model…" })).toBeEnabled();
    expect(screen.getByLabelText("From 3D")).toHaveTextContent("Blender is optional and was not found");
  });

  it("builds in Blender and brings the work back", async () => {
    await show(none());
    fireEvent.click(await screen.findByRole("button", { name: "Build it in Blender" }));
    await waitFor(() => expect(sent("blender_new")).toHaveLength(1));
    fireEvent.click(await screen.findByRole("button", { name: "Open in Blender" }));
    await waitFor(() => expect(sent("open_blender")).toHaveLength(1));
    fireEvent.click(screen.getByRole("button", { name: "Bring it back from Blender" }));
    await waitFor(() => expect(sent("bring_back")).toHaveLength(1));
  });

  it("looks from the camera and says how much of the view is empty", async () => {
    await show(made("pictures"));
    fireEvent.click(await screen.findByRole("button", { name: "Look from the camera" }));
    expect(await screen.findByLabelText("The set from its camera")).toHaveTextContent("30% of this view is empty");
  });

  it("opens the full set builder and the shot planner on this place's set", async () => {
    const onOpenSet = vi.fn(), onPlan = vi.fn();
    await show(made("model"), 2, { onOpenSet, onPlan });
    fireEvent.click(await screen.findByRole("button", { name: "Edit the set" }));
    fireEvent.click(screen.getByRole("button", { name: "Plan the shots" }));
    expect(onOpenSet).toHaveBeenCalledWith("ws-1");
    expect(onPlan).toHaveBeenCalledWith("ws-1");
  });

  it("shows an engine error in words and keeps the offer", async () => {
    await show(none());
    invoke.mockImplementation((_c: string, a: { action: string }) => (a.action === "status" ? Promise.resolve(st) : Promise.reject("Blender could not turn that file into a model: boom")));
    pick.mockResolvedValueOnce("C:\M\bad.blend");
    fireEvent.click(await screen.findByRole("button", { name: "From a Blender file…" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Blender could not turn that file into a model: boom");
    expect(screen.getByRole("button", { name: "Make a set from 2 pictures" })).toBeEnabled();
  });
});
