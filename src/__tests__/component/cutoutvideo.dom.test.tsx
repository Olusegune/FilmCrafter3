// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";

const invoke = vi.fn();
vi.mock("@tauri-apps/api/core", () => ({ invoke: (cmd: string, args: unknown) => invoke(cmd, args), convertFileSrc: (p: string) => p }));
let progressHandler: ((e: { payload: unknown }) => void) | null = null;
vi.mock("@tauri-apps/api/event", () => ({ listen: vi.fn((_n: string, h: (e: { payload: unknown }) => void) => { progressHandler = h; return Promise.resolve(() => {}); }) }));
const pick = vi.fn();
vi.mock("@tauri-apps/plugin-dialog", () => ({ open: (o: unknown) => pick(o), save: vi.fn() }));
const reveal = vi.fn();
vi.mock("@tauri-apps/plugin-opener", () => ({ revealItemInDir: (p: string) => reveal(p) }));

import { CutoutStudio, keyWords, sourceWords } from "../../CutoutStudio";
import type { KeyParams, KeyReport, VpCutout, VpSource, VpState } from "../../api";

const defaults: KeyParams = { screen: "green", color: null, similarity: 0.06, softness: null, erode: 0, dilate: 0, feather: 0, fill_holes: false, despill: 0.8, decontaminate: true, clip_black: 0, clip_white: 1 };
const plate = { screen: "green", color: [0.1, 0.7, 0.2], saturation: 0.5, border_on_screen: 0.97, spread: 0.02, usable: true, notes: [], width: 192, height: 144 };
const rep = (over: Partial<KeyReport> = {}): KeyReport => ({ subject: 0.2, removed: 0.7, soft_edge: 0.03, edge_spill: 0.01, plate, notes: [], flicker_before: 0.0195, flicker_after: 0.0066, ...over });
const clipSrc = (over: Partial<VpSource> = {}): VpSource => ({ id: "vs-clip", kind: "plate", name: "Sarah walks", file: "vp/sources/vs-clip.mp4", width: 192, height: 144, bytes: 1, clip: true, fps: 12, seconds: 2, frames: 24, ...over });
const clipCut = (over: Partial<VpCutout> = {}): VpCutout => ({ id: "cu-clip", kind: "clip", name: "Sarah walks cutout", source: "vs-clip", params: defaults, report: rep(), rgba: "vp/cutouts/cu-clip/frames/00001.png", mask: "vp/cutouts/cu-clip/masks/00001.png", seq: "vp/cutouts/cu-clip/frames/%05d.png", frames: 24, fps: 12, width: 192, height: 144, ...over });
const state = (over: Partial<VpState> = {}): VpState => ({ sources: [], cutouts: [], compositions: [], limits: { sources: 300, cutouts: 300, compositions: 100, layers: 24, side: 8192 }, defaults, ...over });

let st: VpState;
let caps = { png: true, prores4444: true, webm: true, h264: true, note: "Transparent H.264 MP4 does not exist." };
const backend = (_c: string, a: { action: string; data: Record<string, unknown> }) => {
  switch (a.action) {
    case "capabilities": return Promise.resolve(caps);
    case "import_clip": st = { ...st, sources: [...st.sources, clipSrc({ kind: a.data.kind as "plate" })] }; return Promise.resolve({ ...st, id: "vs-clip", already_there: false });
    case "key_clip": st = { ...st, cutouts: [...st.cutouts, clipCut()] }; return Promise.resolve({ ...st, id: "cu-clip", report: rep() });
    case "export_clip": return Promise.resolve({ id: a.data.id, format: a.data.format, path: "C:\\Films\\exports\\virtual-production\\x", file: "x", frames: 24, fps: 12, has_alpha: a.data.format !== "webm", alpha_error: 0.01, note: "" });
    case "render_video": return Promise.resolve({ ...st, id: "cp-1", file: "vp/renders/cp-1-1.mp4", format: "mp4", frames: 36, fps: 24, seconds: 1.5, width: 192, height: 144 });
    case "compose_set": st = { ...st, compositions: [{ ...(a.data as object), id: "cp-1" } as never] }; return Promise.resolve({ ...st, id: "cp-1" });
    case "cancel": return Promise.resolve({ cancelled: true });
    default: return Promise.resolve(st);
  }
};
const sent = (action: string) => invoke.mock.calls.filter(([, a]) => a.action === action).map(([, a]) => a.data);
afterEach(() => { cleanup(); invoke.mockReset(); pick.mockReset(); reveal.mockReset(); progressHandler = null; caps = { png: true, prores4444: true, webm: true, h264: true, note: "Transparent H.264 MP4 does not exist." }; });
const show = async () => { render(<CutoutStudio dir="film" onClose={() => {}} />); await screen.findByRole("tablist"); };
const tab = (n: RegExp) => fireEvent.click(screen.getByRole("tab", { name: n }));

describe("the cutout studio, video", () => {
  it("says a clip in plain words and the flicker before and after smoothing", () => {
    expect(sourceWords(clipSrc())).toBe("Clip · Subject on a screen · 192 × 144 · 2.0 s at 12 per second");
    expect(sourceWords(clipSrc({ clip: false, kind: "background", seconds: undefined }))).toBe("Picture · Background · 192 × 144");
    expect(keyWords(rep())).toEqual(["20% kept as subject, 70% removed, 3% soft edge.", "Edge flicker from frame to frame: 0.0195 before smoothing, 0.0066 after."]);
    expect(keyWords(rep({ flicker_before: 0.001, flicker_after: 0.001 }))[1]).toBe("Edge flicker from frame to frame: 0.0010.");
    expect(keyWords(rep({ flicker_before: undefined, flicker_after: undefined }))).toHaveLength(1);
  });

  it("brings a clip in through a video picker, as a plate or a background", async () => {
    st = state();
    invoke.mockImplementation(backend);
    pick.mockResolvedValue("C:\\Videos\\walk.mp4");
    await show();
    fireEvent.click(screen.getByRole("button", { name: /Bring in a clip: subject on a screen/ }));
    await waitFor(() => expect(sent("import_clip")).toEqual([{ path: "C:\\Videos\\walk.mp4", kind: "plate" }]));
    expect(pick.mock.calls[0][0].filters[0].extensions).toContain("mp4");
    fireEvent.click(screen.getByRole("button", { name: /Bring in a clip: background/ }));
    await waitFor(() => expect(sent("import_clip")[1]).toEqual({ path: "C:\\Videos\\walk.mp4", kind: "background" }));
    expect(await screen.findByText(/Clip · Subject on a screen/)).toBeInTheDocument();
  });

  it("keys a clip with the smoothing the person set, shows progress, and offers Stop while it runs", async () => {
    st = state({ sources: [clipSrc()] });
    let finish: () => void = () => {};
    invoke.mockImplementation((c: string, a: { action: string; data: Record<string, unknown> }) => (a.action === "key_clip" ? new Promise((res) => { finish = () => res(backend(c, a)); }) : backend(c, a)));
    await show();
    tab(/2 Cut out/);
    expect(screen.queryByRole("button", { name: "Check the screen" })).toBeNull();                       // a clip is checked as it is keyed
    fireEvent.change(screen.getByLabelText("Calm the edge between frames"), { target: { value: "0.8" } });
    fireEvent.click(screen.getByRole("button", { name: "Cut out the clip" }));
    const stop = await screen.findByRole("button", { name: "Stop" });
    act(() => { progressHandler?.({ payload: { task: "vpvideo", event: "progress", stage: "keying frames", progress: 0.4 } }); });
    expect(await screen.findByRole("progressbar")).toHaveTextContent("keying frames 40%");
    act(() => { progressHandler?.({ payload: { task: "other", event: "progress", stage: "x", progress: 0.9 } }); });
    expect(screen.getByRole("progressbar")).toHaveTextContent("40%");                                     // another job's progress is not shown here
    fireEvent.click(stop);
    await waitFor(() => expect(sent("cancel")).toHaveLength(1));
    await act(async () => { finish(); });
    expect(sent("key_clip")[0]).toMatchObject({ source: "vs-clip", temporal: 0.8, params: { screen: "green" } });
    expect(await screen.findByLabelText("Key result")).toHaveTextContent(/before smoothing/);
    expect(screen.queryByRole("progressbar")).toBeNull();
  });

  it("exports a keyed clip as a PNG sequence or alpha video and says when the transparency was not found", async () => {
    st = state({ sources: [clipSrc()], cutouts: [clipCut()] });
    invoke.mockImplementation(backend);
    await show();
    tab(/2 Cut out/);
    expect(screen.getByText("Clip · 24 frames at 12 per second", { exact: false })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /as a PNG sequence/ }));
    await waitFor(() => expect(sent("export_clip")[0]).toEqual({ id: "cu-clip", format: "png" }));
    expect(await screen.findByText(/Saved 24 PNG frames with transparency/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /as ProRes 4444/ }));
    expect(await screen.findByText(/Saved with transparency \(read back and checked\)/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /as WebM/ }));
    expect(await screen.findByText(/NO transparency was found in the file/)).toBeInTheDocument();
    expect(reveal).toHaveBeenCalled();
  });

  it("greys a format this computer cannot make, with the reason", async () => {
    caps = { ...caps, prores4444: false };
    st = state({ cutouts: [clipCut()], sources: [clipSrc()] });
    invoke.mockImplementation(backend);
    await show();
    tab(/2 Cut out/);
    await waitFor(() => expect(screen.getByRole("button", { name: /as ProRes 4444/ })).toBeDisabled());
    expect(screen.getByRole("button", { name: /as ProRes 4444/ }).getAttribute("title")).toContain("cannot make it");
    expect(screen.getByRole("button", { name: /as WebM/ })).toBeEnabled();
    expect(screen.getByText(/Transparent H.264 MP4 does not exist/)).toBeInTheDocument();
  });

  it("puts a clip on a layer with a start time, repeat and keyframes, and renders a video", async () => {
    st = state({ sources: [clipSrc({ id: "vs-bg", kind: "background", name: "Street" }), clipSrc()], cutouts: [clipCut()] });
    invoke.mockImplementation(backend);
    await show();
    tab(/3 Compose/);
    fireEvent.click(screen.getByRole("button", { name: "Start a new one" }));
    fireEvent.click(screen.getByRole("button", { name: "Add a cutout" }));
    const row = screen.getByLabelText("Layer 1");
    expect(within(row).getByLabelText("Layer 1 loop")).toBeInTheDocument();                              // only a clip can be repeated
    fireEvent.change(within(row).getByLabelText("Layer 1 starts at"), { target: { value: "0.5" } });
    fireEvent.click(within(row).getByLabelText("Layer 1 loop"));
    fireEvent.click(within(row).getByRole("button", { name: "Add a keyframe to layer 1" }));
    fireEvent.click(within(row).getByRole("button", { name: "Add a keyframe to layer 1" }));
    fireEvent.change(within(row).getByLabelText("Keyframe 2 across"), { target: { value: "0.8" } });
    fireEvent.change(within(row).getByLabelText("Keyframe 2 movement"), { target: { value: "smooth" } });
    expect((within(row).getByLabelText("Keyframe 2 time") as HTMLInputElement).value).toBe("1");        // the next keyframe is a second later
    fireEvent.change(screen.getByLabelText("Frames per second"), { target: { value: "24" } });
    fireEvent.click(screen.getByRole("button", { name: "Save and render a video" }));
    await waitFor(() => expect(sent("render_video")).toEqual([{ id: "cp-1", fps: 24 }]));
    const saved = sent("compose_set")[0] as { layers: { start: number; loop: boolean; keys: { t: number; x: number; ease: string }[] }[] };
    expect(saved.layers[0]).toMatchObject({ start: 0.5, loop: true });
    expect(saved.layers[0].keys).toHaveLength(2);
    expect(saved.layers[0].keys[1]).toMatchObject({ t: 1, x: 0.8, ease: "smooth" });
    expect(await screen.findByLabelText("The rendered video")).toBeInTheDocument();
    expect(await screen.findByText("Video written: 36 frames, 1.5 s.")).toBeInTheDocument();
  });

  it("sends the length when one is chosen and removes a keyframe", async () => {
    st = state({ sources: [clipSrc({ id: "vs-bg", kind: "background", name: "Street" })], cutouts: [clipCut()] });
    invoke.mockImplementation(backend);
    await show();
    tab(/3 Compose/);
    fireEvent.click(screen.getByRole("button", { name: "Start a new one" }));
    fireEvent.click(screen.getByRole("button", { name: "Add a cutout" }));
    fireEvent.click(screen.getByRole("button", { name: "Add a keyframe to layer 1" }));
    fireEvent.click(screen.getByRole("button", { name: "Remove keyframe 1 of layer 1" }));
    expect(screen.queryByLabelText("Keyframe 1 time")).toBeNull();
    fireEvent.change(screen.getByLabelText("Seconds (0 = as long as its parts)"), { target: { value: "3" } });
    fireEvent.click(screen.getByRole("button", { name: "Save and render a video" }));
    await waitFor(() => expect(sent("render_video")).toEqual([{ id: "cp-1", fps: 24, seconds: 3 }]));
  });

  it("shows the engine's refusal for a clip in plain words", async () => {
    st = state({ sources: [clipSrc()] });
    invoke.mockImplementation((c: string, a: { action: string; data: Record<string, unknown> }) => (a.action === "key_clip" ? Promise.reject("That is 900 frames at 30 a second: this version keys at most 720.") : backend(c, a)));
    await show();
    tab(/2 Cut out/);
    fireEvent.click(screen.getByRole("button", { name: "Cut out the clip" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("keys at most 720");
    await waitFor(() => expect(screen.getByRole("button", { name: "Cut out the clip" })).toBeEnabled());
  });
});
