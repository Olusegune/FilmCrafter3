// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";

const invoke = vi.fn();
vi.mock("@tauri-apps/api/core", () => ({ invoke: (cmd: string, args: unknown) => invoke(cmd, args), convertFileSrc: (p: string) => p }));

import { FinishClip } from "../../FinishClip";
import type { PlRun } from "../../api";

const STAGES = ["inspect", "continuity", "calm", "enhance", "finish", "validate"];
const LABELS = { inspect: "Read and measure the clip", continuity: "Check the set's continuity", calm: "Calm flicker", enhance: "Enhance (Fidelity)", finish: "Finish and deliver", validate: "Check the delivered file" };
const mkRun = (status: Record<string, "pending" | "done" | "failed">, extra: Partial<PlRun> = {}): PlRun => ({ id: "pl-12345678", source: "clip.mp4", options: { set: null, look: "none", profile: "web", calm: "auto", enhance: false, strength: 0.5 },
  stages: Object.fromEntries(STAGES.map((s) => [s, { status: status[s] ?? "pending", seconds: status[s] === "done" ? 1.2 : undefined, error: status[s] === "failed" ? "The disk was full." : undefined,
    result: s === "validate" && status[s] === "done" ? { ok: true, checks: [{ check: "It plays", ok: true, detail: "48 frames read" }, { check: "Sound kept", ok: false, detail: "no sound" }] } : s === "calm" && status[s] === "done" ? { note: "Calm enough: left as it is." } : undefined }])) as PlRun["stages"],
  done: false, delivered: null, valid: null, total_seconds: 0, labels: LABELS, ...extra });
let results: { run: PlRun[]; get: PlRun };
const backend = (_c: string, a: { action: string; data: Record<string, unknown> }) => {
  switch (a.action) {
    case "presets": return Promise.resolve({ looks: [{ id: "none", label: "No look", note: "" }, { id: "film", label: "Film grain", note: "" }], profiles: [{ id: "web", label: "Web (H.264)", note: "", ext: "mp4" }, { id: "master", label: "Master", note: "", ext: "mp4" }], strengths: [] });
    case "plan": return Promise.resolve({ source: "clip.mp4", info: { seconds: 2, frames: 48, fps: 24, width: 320, height: 180, audio: true, codec: "h264" }, options: a.data.options, stages: [], seconds_estimate: 6.4, note: "" });
    case "start": return Promise.resolve(mkRun({}));
    case "get": return Promise.resolve(results.get);
    case "run": { const r = results.run.shift()!; if (!r) return Promise.reject("x"); return r.stages.finish.status === "failed" && !r.done ? Promise.reject("Finish and deliver: The disk was full.") : Promise.resolve(r); }
    default: return Promise.resolve({});
  }
};
const sent = (action: string) => invoke.mock.calls.filter(([, a]) => a.action === action).map(([, a]) => a.data);
afterEach(() => { cleanup(); invoke.mockReset(); });
const show = async () => { invoke.mockImplementation(backend); render(<FinishClip dir="film" clip="worldlock/ws-1/animations/c.mp4" set="ws-1" />); await screen.findByLabelText("Plan"); };

describe("finishing a clip made from a set", () => {
  it("says what the clip is and roughly how long this will take, and offers the finisher's own looks and profiles", async () => {
    results = { run: [], get: mkRun({}) };
    await show();
    expect(screen.getByLabelText("Plan")).toHaveTextContent("320×180 · 48 frames · 2 s · with sound. Roughly 6 s");
    expect(within(screen.getByLabelText("Finishing look")).getByRole("option", { name: "Film grain" })).toBeInTheDocument();
    expect(within(screen.getByLabelText("Delivery profile")).getByRole("option", { name: "Master" })).toBeInTheDocument();
  });

  it("sends the chosen options, shows each stage, plays the delivered file and lists the checks, a failing one in warning words", async () => {
    const done = mkRun(Object.fromEntries(STAGES.map((s) => [s, "done" as const])), { done: true, delivered: "project:finish/c_clean_web.mp4", valid: true, total_seconds: 4.2 });
    results = { run: [done], get: mkRun({}) };
    await show();
    fireEvent.click(screen.getByRole("checkbox", { name: /Enhance every frame/ }));
    fireEvent.change(screen.getByLabelText("Finishing look"), { target: { value: "film" } });
    await waitFor(() => expect(screen.getByRole("button", { name: "Finish this clip" })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: "Finish this clip" }));
    await waitFor(() => expect(sent("start")).toEqual([{ ref: "worldlock/ws-1/animations/c.mp4", set: "ws-1", options: { look: "film", profile: "web", enhance: true, strength: 0.5, calm: "auto" } }]));
    const box = await screen.findByLabelText("Delivered");
    expect(box).toHaveTextContent("Delivered and checked.");
    expect(box.querySelector("video")?.getAttribute("src")).toContain("film/finish/c_clean_web.mp4");
    expect(within(box).getByText(/Sound kept: no sound/).className).toContain("ss-warn");
    expect(screen.getByLabelText("Stage calm")).toHaveTextContent("Calm enough: left as it is.");
  });

  it("says which stage failed and why, keeps the earlier ones, and offers Resume", async () => {
    const failed = mkRun({ inspect: "done", continuity: "done", calm: "done", enhance: "done", finish: "failed" });
    results = { run: [failed, mkRun(Object.fromEntries(STAGES.map((s) => [s, "done" as const])), { done: true, delivered: "project:finish/c.mp4", valid: true })], get: failed };
    await show();
    fireEvent.click(screen.getByRole("button", { name: "Finish this clip" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Finish and deliver: The disk was full.");
    expect(screen.getByLabelText("Stage finish")).toHaveTextContent("The disk was full.");
    expect(screen.getByLabelText("Stage inspect")).toHaveTextContent("1.2 s");
    fireEvent.click(screen.getByRole("button", { name: "Resume" }));
    await waitFor(() => expect(sent("run")).toHaveLength(2));
    expect(sent("start")).toHaveLength(1);                                                  // resuming does not start a new run
    expect(await screen.findByLabelText("Delivered")).toBeInTheDocument();
  });

  it("shows a refusal from the plan in words", async () => {
    invoke.mockImplementation((_c: string, a: { action: string }) => (a.action === "plan" ? Promise.reject("That clip is longer than 10 minutes: finish it in parts.") : Promise.resolve({ looks: [], profiles: [], strengths: [] })));
    render(<FinishClip dir="film" clip="x.mp4" />);
    expect(await screen.findByRole("alert")).toHaveTextContent("longer than 10 minutes");
    expect(screen.getByRole("button", { name: "Finish this clip" })).toBeDisabled();
  });
});
