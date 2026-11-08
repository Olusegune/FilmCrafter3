// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";

const invoke = vi.fn();
vi.mock("@tauri-apps/api/core", () => ({ invoke: (cmd: string, args: unknown) => invoke(cmd, args), convertFileSrc: (p: string) => p }));
const pick = vi.fn();
vi.mock("@tauri-apps/plugin-dialog", () => ({ open: (o: unknown) => pick(o), save: vi.fn() }));

import { Reconstruct } from "../../Reconstruct";
import type { RcItem, RcStatus } from "../../api";

const item = (over: Partial<RcItem> = {}): RcItem => ({ id: "it-01", name: "Table", kind: "furniture", picture: 0, bbox: [0.1, 0.5, 0.4, 0.9], distance_m: 3, width_m: 1.2, height_m: 0.8, depth_m: 0.8, facing: "toward the camera", on_floor: true, confidence: 0.8, reason: "A flat top on legs.", hidden: "the far side", status: "proposed", ...over });
const base = (over: Partial<RcStatus> = {}): RcStatus => ({ place: "e_k", name: "Kitchen", references: [], place_pictures: 2, limits: "From one viewpoint a picture shows only the surfaces facing the camera.", image_to_3d: "No image-to-3D generator is installed.", assumed: { fov: 55, camera_height: 1.6 }, proposal: null, built: null, approved: null, spend: [], ...over });
const proposal = (items: RcItem[]): NonNullable<RcStatus["proposal"]> => ({ model: "gpt-x", scene: { kind: "kitchen", summary: "A small kitchen.", indoor: true, room_width_m: 4, room_depth_m: 5, lighting: "" }, items, uncertainty: ["What is behind the table."], missing_views: ["The opposite wall."], reuse: [] });
let st: RcStatus;
let local = false;
const backend = (_c: string, a: { action: string; data: Record<string, unknown> }) => {
  switch (a.action) {
    case "status": return Promise.resolve(st);
    case "estimate": return Promise.resolve({ calls: 1, usd: 0.026, local, note: "A rough estimate.", pictures: st.references.length, sends: "1 picture, shrunk to 512 pixels wide, and the instructions. Nothing else from your film." });
    case "add_reference": st = { ...st, references: [...st.references, { id: "rf-1", file: "worldlock/reconstructions/e_k/refs/rf-1.png", name: "room", width: 800, height: 450 }] }; return Promise.resolve(st);
    case "propose": st = { ...st, proposal: proposal([item(), item({ id: "it-02", name: "Chair", confidence: 0.3 })]) }; return Promise.resolve(st);
    case "item_set": st = { ...st, proposal: proposal(st.proposal!.items.map((i) => (i.id === a.data.item ? { ...i, ...(a.data.patch as object) } : i))) }; return Promise.resolve(st);
    case "accept_all": st = { ...st, proposal: proposal(st.proposal!.items.map((i) => (i.confidence >= 0.4 ? { ...i, status: "accepted" as const } : i))) }; return Promise.resolve(st);
    case "build": st = { ...st, built: { set: "ws-1", mode: a.data.mode as "layers", items: [{ item: "it-01", x: 0, y: 0, z: 3, width: 1, height: 1 }] } }; return Promise.resolve(st);
    case "approve": st = { ...st, approved: 1 }; return Promise.resolve(st);
    default: return Promise.resolve(st);
  }
};
const sent = (action: string) => invoke.mock.calls.filter(([, a]) => a.action === action).map(([, a]) => a.data);
const show = async (s: RcStatus, onDone = () => {}) => { st = s; invoke.mockImplementation(backend); render(<Reconstruct dir="film" place="e_k" name="Kitchen" onClose={() => {}} onDone={onDone} />); await screen.findByText(/From one viewpoint a picture shows only/); };
afterEach(() => { cleanup(); invoke.mockReset(); pick.mockReset(); local = false; });

describe("a set from pictures, with AI help", () => {
  it("says up front what a picture cannot show and starts with the place's own pictures", async () => {
    await show(base());
    expect(screen.getByRole("note")).toHaveTextContent("only the surfaces facing the camera");
    fireEvent.click(await screen.findByRole("button", { name: "Use this place's 2 pictures" }));
    await waitFor(() => expect(sent("add_reference")).toEqual([{ place: "e_k", from_place: true }]));
  });

  it("sends nothing until the cost is understood and ticked", async () => {
    await show(base({ references: [{ id: "rf-1", file: "x.png", name: "room", width: 800, height: 450 }] }));
    const ask = await screen.findByRole("button", { name: "Ask the AI to list what it sees" });
    expect(await screen.findByLabelText("What this sends")).toHaveTextContent("about $0.026");
    expect(ask).toBeDisabled();
    fireEvent.click(screen.getByRole("checkbox", { name: /I understand this sends the pictures/ }));
    expect(ask).toBeEnabled();
    fireEvent.click(ask);
    await waitFor(() => expect(sent("propose")).toEqual([{ place: "e_k", confirmed: true }]));
    expect(await screen.findByLabelText("Inventory")).toBeInTheDocument();
  });

  it("needs no confirmation with a local model and says nothing leaves the computer", async () => {
    local = true;
    await show(base({ references: [{ id: "rf-1", file: "x.png", name: "room", width: 800, height: 450 }] }));
    expect(await screen.findByLabelText("What this sends")).toHaveTextContent("nothing leaves this computer");
    expect(screen.queryByRole("checkbox", { name: /I understand/ })).toBeNull();
    expect(screen.getByRole("button", { name: "Ask the AI to list what it sees" })).toBeEnabled();
  });

  it("shows each object with how sure the AI is and why, and lets the person correct it", async () => {
    await show(base({ references: [{ id: "rf-1", file: "x.png", name: "room", width: 800, height: 450 }], proposal: proposal([item(), item({ id: "it-02", name: "Chair", confidence: 0.3 })]) }));
    const li = await screen.findByLabelText("Item Table");
    expect(li).toHaveTextContent("80% sure");
    expect(li).toHaveTextContent("A flat top on legs. Not visible: the far side");
    const d = screen.getByLabelText("Table distance (m)");
    fireEvent.change(d, { target: { value: "4" } });
    fireEvent.blur(d);
    await waitFor(() => expect(sent("item_set")).toEqual([{ place: "e_k", item: "it-01", patch: { distance_m: 4 } }]));
    fireEvent.click(screen.getByRole("checkbox", { name: "Accept Table" }));
    await waitFor(() => expect(sent("item_set")[1]).toMatchObject({ patch: { status: "accepted" } }));
    expect(screen.getByRole("img", { name: "Floor plan of the draft" })).toBeInTheDocument();
    expect(screen.getByText(/What the AI could not tell/)).toBeInTheDocument();
    expect(screen.getByText(/Pictures that would improve this/)).toBeInTheDocument();
  });

  it("accepts what the AI is at least 40% sure of and leaves the rest to the person", async () => {
    await show(base({ references: [{ id: "rf-1", file: "x.png", name: "room", width: 800, height: 450 }], proposal: proposal([item(), item({ id: "it-02", name: "Chair", confidence: 0.3 })]) }));
    fireEvent.click(await screen.findByRole("button", { name: /Accept everything it is at least 40% sure of/ }));
    await waitFor(() => expect(sent("accept_all")).toEqual([{ place: "e_k", min_confidence: 0.4 }]));
    expect(await screen.findByText("1 of 2 accepted")).toBeInTheDocument();
  });

  it("will not build with nothing accepted, builds the chosen kind, and calls it a draft until approved", async () => {
    await show(base({ references: [{ id: "rf-1", file: "x.png", name: "room", width: 800, height: 450 }], proposal: proposal([item()]) }));
    const build = await screen.findByRole("button", { name: "Build the draft" });
    expect(build).toBeDisabled();
    fireEvent.click(screen.getByRole("checkbox", { name: "Accept Table" }));
    await waitFor(() => expect(build).toBeEnabled());
    fireEvent.change(screen.getByLabelText("How to build it"), { target: { value: "boxes" } });
    fireEvent.click(build);
    await waitFor(() => expect(sent("build")).toEqual([{ place: "e_k", mode: "boxes" }]));
    expect(await screen.findByText(/It is a draft until you approve it/)).toBeInTheDocument();
  });

  it("approves and locks, then closes back to the place", async () => {
    const done = vi.fn();
    await show(base({ references: [{ id: "rf-1", file: "x.png", name: "room", width: 800, height: 450 }], proposal: proposal([item({ status: "accepted" })]), built: { set: "ws-1", mode: "layers", items: [{ item: "it-01", x: 0, y: 0, z: 3, width: 1, height: 1 }] } }), done);
    fireEvent.click(await screen.findByRole("button", { name: "Approve and lock the set" }));
    await waitFor(() => expect(sent("approve")).toEqual([{ place: "e_k" }]));
    expect(done).toHaveBeenCalled();
  });

  it("shows an engine refusal in words and keeps the screen", async () => {
    await show(base({ references: [{ id: "rf-1", file: "x.png", name: "room", width: 800, height: 450 }] }));
    invoke.mockImplementation((_c: string, a: { action: string }) => (a.action === "propose" ? Promise.reject("The AI's answer could not be read. Nothing was changed.") : backend(_c, a as never)));
    fireEvent.click(await screen.findByRole("checkbox", { name: /I understand/ }));
    fireEvent.click(screen.getByRole("button", { name: "Ask the AI to list what it sees" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Nothing was changed.");
    expect(within(document.body).getByRole("button", { name: "Add pictures…" })).toBeEnabled();
  });
});
