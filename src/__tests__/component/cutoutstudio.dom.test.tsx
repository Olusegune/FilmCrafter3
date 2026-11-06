// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";

const invoke = vi.fn();
vi.mock("@tauri-apps/api/core", () => ({ invoke: (cmd: string, args: unknown) => invoke(cmd, args), convertFileSrc: (p: string) => p }));
const pick = vi.fn();
vi.mock("@tauri-apps/plugin-dialog", () => ({ open: (o: unknown) => pick(o), save: vi.fn() }));
const reveal = vi.fn();
vi.mock("@tauri-apps/api/event", () => ({ listen: vi.fn(() => Promise.resolve(() => {})) }));
vi.mock("@tauri-apps/plugin-opener", () => ({ revealItemInDir: (p: string) => reveal(p) }));

import { CutoutStudio, keyWords, plateWords } from "../../CutoutStudio";
import type { KeyParams, KeyReport, PlateReport, VpCutout, VpState } from "../../api";

const defaults: KeyParams = { screen: "green", color: null, similarity: 0.06, softness: null, erode: 0, dilate: 0, feather: 0, fill_holes: false, despill: 0.8, decontaminate: true, clip_black: 0, clip_white: 1 };
const plateReport = (over: Partial<PlateReport> = {}): PlateReport => ({ screen: "green", color: [0.1, 0.7, 0.2], saturation: 0.5, border_on_screen: 0.97, spread: 0.02, usable: true, notes: ["A clean, even screen: a key should work well."], width: 320, height: 400, ...over });
const keyReport = (over: Partial<KeyReport> = {}): KeyReport => ({ subject: 0.31, removed: 0.55, soft_edge: 0.04, edge_spill: 0.01, plate: plateReport(), notes: [], ...over });
const cutout = (id = "cu-1", over: Partial<VpCutout> = {}): VpCutout => ({ id, name: "Sarah cutout", source: "vs-1", params: defaults, report: keyReport(), rgba: `vp/cutouts/${id}/cutout.png`, mask: `vp/cutouts/${id}/mask.png`, width: 320, height: 400, ...over });
const state = (over: Partial<VpState> = {}): VpState => ({ sources: [], cutouts: [], compositions: [], limits: { sources: 300, cutouts: 300, compositions: 100, layers: 24, side: 8192 }, defaults, ...over });

let st: VpState;
const backend = (_c: string, a: { action: string; data: Record<string, unknown> }) => {
  switch (a.action) {
    case "import": st = { ...st, sources: [...st.sources, { id: "vs-new", kind: a.data.kind as "plate", name: "plate", file: "vp/sources/vs-new.png", width: 320, height: 400, bytes: 1 }] }; return Promise.resolve({ ...st, id: "vs-new", already_there: false });
    case "plate_check": return Promise.resolve(plateReport());
    case "key": st = { ...st, cutouts: [...st.cutouts, cutout("cu-new")] }; return Promise.resolve({ ...st, id: "cu-new", report: keyReport({ notes: ["There is still screen colour on the edge: raise despill, or erode the edge by one pixel."] }) });
    case "export": return Promise.resolve({ id: a.data.id, files: { rgba: "exports/virtual-production/x rgba.png", mask: "x" }, folder: "C:\\Films\\exports\\virtual-production", has_alpha: true, transparent_share: 0.5, note: "" });
    case "cutout_remove": st = { ...st, cutouts: st.cutouts.filter((c) => c.id !== a.data.id) }; return Promise.resolve(st);
    case "compose_set": st = { ...st, compositions: [{ ...(a.data as object), id: "cp-1" } as never] }; return Promise.resolve({ ...st, id: "cp-1" });
    case "render": return Promise.resolve({ ...st, id: "cp-1", file: "vp/renders/cp-1-1.png", width: 1280, height: 720, layers: 1, missing: [] });
    case "capabilities": return Promise.resolve({ png: true, prores4444: true, webm: true, h264: true, note: "Transparent H.264 MP4 does not exist." });
    case "plate_prompt": return Promise.resolve({ prompt: "A woman against a flat green background.", screen: "green", notes: ["Check the screen before keying."], sent: false });
    default: return Promise.resolve(st);
  }
};
const sent = (action: string) => invoke.mock.calls.filter(([, a]) => a.action === action).map(([, a]) => a.data);
afterEach(() => { cleanup(); invoke.mockReset(); pick.mockReset(); reveal.mockReset(); });
const show = async () => { render(<CutoutStudio dir="film" onClose={() => {}} />); await screen.findByRole("tablist"); };
const tab = (n: RegExp) => fireEvent.click(screen.getByRole("tab", { name: n }));

describe("the cutout studio", () => {
  it("says the plate and the key in plain words", () => {
    expect(plateWords(plateReport())).toBe("Usable: green screen, 97% of the border is screen, unevenness 0.020. A clean, even screen: a key should work well.");
    expect(plateWords(plateReport({ usable: false, notes: ["Only 60% of the border is the screen colour."] }))).toMatch(/^Not ready: /);
    expect(keyWords(keyReport({ notes: ["x"] }))).toEqual(["31% kept as subject, 55% removed, 4% soft edge.", "x"]);
  });

  it("loads once, sends nothing else, and says up front that nothing is generated or sent", async () => {
    st = state();
    invoke.mockImplementation(backend);
    await show();
    expect(invoke.mock.calls.map(([cmd, a]) => `${cmd}:${a.action}`).sort()).toEqual(["film_vp:get", "film_vpvideo:capabilities"]);
    expect(screen.getByText(/nothing is generated or sent/i)).toBeInTheDocument();
    expect(screen.getByText(/does not know what a person is/i)).toBeInTheDocument();
  });

  it("brings a picture in through the file picker, as the kind chosen, and says the original is untouched", async () => {
    st = state();
    invoke.mockImplementation(backend);
    pick.mockResolvedValue("C:\\Pictures\\plate.png");
    await show();
    fireEvent.click(screen.getByRole("button", { name: /Bring in: Subject on a screen/ }));
    await waitFor(() => expect(sent("import")).toEqual([{ path: "C:\\Pictures\\plate.png", kind: "plate" }]));
    expect(await screen.findByRole("status")).toHaveTextContent("The original is untouched");
    expect(pick.mock.calls[0][0]).toMatchObject({ multiple: false });
  });

  it("does nothing when the picker is cancelled", async () => {
    st = state();
    invoke.mockImplementation(backend);
    pick.mockResolvedValue(null);
    await show();
    fireEvent.click(screen.getByRole("button", { name: /Bring in: Background/ }));
    await waitFor(() => expect(pick).toHaveBeenCalled());
    expect(sent("import")).toHaveLength(0);
  });

  it("writes the words for a clean plate and says they were not sent", async () => {
    st = state();
    invoke.mockImplementation(backend);
    await show();
    const write = screen.getByRole("button", { name: "Write the words" });
    expect(write).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Who or what"), { target: { value: "a woman in a red coat" } });
    fireEvent.change(screen.getByLabelText("Screen colour"), { target: { value: "blue" } });
    fireEvent.click(write);
    await waitFor(() => expect(sent("plate_prompt")).toEqual([{ subject: "a woman in a red coat", screen: "blue" }]));
    expect(await screen.findByText("A woman against a flat green background.")).toBeInTheDocument();
    expect(screen.getByText("Check the screen before keying.")).toBeInTheDocument();
  });

  it("asks for a plate first when there is none", async () => {
    st = state();
    invoke.mockImplementation(backend);
    await show();
    tab(/2 Cut out/);
    expect(screen.getByText("Bring in a plate first (step 1).")).toBeInTheDocument();
    tab(/3 Compose/);
    expect(screen.getByText("Make a cutout first (step 2).")).toBeInTheDocument();
  });

  it("checks the screen before keying and shows the verdict", async () => {
    st = state({ sources: [{ id: "vs-1", kind: "plate", name: "Sarah plate", file: "vp/sources/vs-1.png", width: 320, height: 400, bytes: 1 }] });
    invoke.mockImplementation(backend);
    await show();
    tab(/2 Cut out/);
    fireEvent.click(screen.getByRole("button", { name: "Check the screen" }));
    expect(await screen.findByLabelText("Plate check")).toHaveTextContent("Usable: green screen");
    expect(sent("plate_check")).toEqual([{ source: "vs-1", screen: "green" }]);
  });

  it("cuts out with the settings the person set and shows what to look at", async () => {
    st = state({ sources: [{ id: "vs-1", kind: "plate", name: "Sarah plate", file: "vp/sources/vs-1.png", width: 320, height: 400, bytes: 1 }] });
    invoke.mockImplementation(backend);
    await show();
    tab(/2 Cut out/);
    fireEvent.change(screen.getByLabelText("Similarity"), { target: { value: "0.12" } });
    fireEvent.change(screen.getByLabelText("Shrink edge (px)"), { target: { value: "2" } });
    fireEvent.click(screen.getByLabelText(/Fill holes/));
    fireEvent.click(screen.getByRole("button", { name: "Cut out" }));
    await waitFor(() => expect(sent("key")).toHaveLength(1));
    expect(sent("key")[0]).toMatchObject({ source: "vs-1", params: { similarity: 0.12, erode: 2, fill_holes: true, screen: "green" }, name: "Sarah plate cutout" });
    const box = await screen.findByLabelText("Key result");
    expect(box).toHaveTextContent("31% kept as subject");
    expect(box).toHaveTextContent("still screen colour on the edge");
    expect(await screen.findByAltText("Sarah cutout")).toBeInTheDocument();
  });

  it("exports a cutout, says when the PNG really has transparency, and removes one without a prompt", async () => {
    st = state({ sources: [{ id: "vs-1", kind: "plate", name: "p", file: "f", width: 1, height: 1, bytes: 1 }], cutouts: [cutout()] });
    invoke.mockImplementation(backend);
    await show();
    tab(/2 Cut out/);
    fireEvent.click(screen.getByRole("button", { name: "Export Sarah cutout" }));
    expect(await screen.findByRole("status")).toHaveTextContent("PNG with transparency");
    expect(reveal).toHaveBeenCalledWith("C:\\Films\\exports\\virtual-production");
    fireEvent.click(screen.getByRole("button", { name: "Remove Sarah cutout" }));
    await waitFor(() => expect(sent("cutout_remove")).toEqual([{ id: "cu-1" }]));
    expect(await screen.findByText("No cutouts yet.")).toBeInTheDocument();
  });

  it("composes a layer on a background and renders it", async () => {
    st = state({ sources: [{ id: "vs-b", kind: "background", name: "Street", file: "vp/sources/vs-b.jpg", width: 1280, height: 720, bytes: 1 }], cutouts: [cutout()] });
    invoke.mockImplementation(backend);
    await show();
    tab(/3 Compose/);
    fireEvent.click(screen.getByRole("button", { name: "Start a new one" }));
    expect(screen.getByLabelText("Background")).toHaveValue("vs-b");
    fireEvent.click(screen.getByRole("button", { name: "Add a cutout" }));
    const row = screen.getByLabelText("Layer 1");
    fireEvent.change(within(row).getByLabelText("Layer 1 across"), { target: { value: "0.3" } });
    fireEvent.change(within(row).getByLabelText("Layer 1 size"), { target: { value: "0.8" } });
    fireEvent.click(within(row).getByLabelText("Layer 1 flip"));
    fireEvent.click(screen.getByRole("button", { name: "Save and render a picture" }));
    await waitFor(() => expect(sent("render")).toEqual([{ id: "cp-1", time: 0 }]));
    const saved = sent("compose_set")[0] as { background: string; layers: { cutout: string; x: number; scale: number; flip: boolean; anchor: string }[] };
    expect(saved.background).toBe("vs-b");
    expect(saved.layers[0]).toMatchObject({ cutout: "cu-1", x: 0.3, scale: 0.8, flip: true, anchor: "feet" });
    expect(await screen.findByAltText("The rendered composition")).toBeInTheDocument();
    expect(await screen.findByRole("status")).toHaveTextContent("Drawn: 1 layer");
  });

  it("shows the engine's refusal in plain words and stays usable", async () => {
    st = state({ sources: [{ id: "vs-1", kind: "plate", name: "p", file: "f", width: 1, height: 1, bytes: 1 }] });
    invoke.mockImplementation((c: string, a: { action: string; data: Record<string, unknown> }) => (a.action === "key" ? Promise.reject("That picture is 9000 by 9000: too large to work on.") : backend(c, a)));
    await show();
    tab(/2 Cut out/);
    fireEvent.click(screen.getByRole("button", { name: "Cut out" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("too large to work on");
    await waitFor(() => expect(screen.getByRole("button", { name: "Cut out" })).toBeEnabled());
  });

  it("shows why it cannot load", async () => {
    invoke.mockRejectedValue("No film is open.");
    render(<CutoutStudio dir="film" onClose={() => {}} />);
    expect(await screen.findByRole("alert")).toHaveTextContent("No film is open.");
  });
});
