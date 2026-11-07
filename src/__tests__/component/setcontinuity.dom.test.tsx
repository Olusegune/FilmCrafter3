// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";

const invoke = vi.fn();
vi.mock("@tauri-apps/api/core", () => ({ invoke: (cmd: string, args: unknown) => invoke(cmd, args), convertFileSrc: (p: string) => p }));
const pick = vi.fn();
vi.mock("@tauri-apps/plugin-dialog", () => ({ open: (o: unknown) => pick(o), save: vi.fn() }));

import { SetContinuity } from "../../SetContinuity";
import type { ScFinding, ScReport } from "../../api";

const finding = (over: Partial<ScFinding> = {}): ScFinding => ({ key: "ck-0123456789", kind: "vanishes", severity: "warning", shots: ["S01-01", "S01-02"], thing: "wa-1", text: "Basket is in view in shot S01-01 and is gone from shot S01-02 on, without being seen to leave.", overridden: false, note: "", ...over });
const report = (findings: ScFinding[], over: Partial<ScReport> = {}): ScReport => {
  const live = findings.filter((f) => !f.overridden);
  return { timeline: [{ shot: "S01-01", camera: { id: "wk-a", name: "A" }, things: [{ id: "wa-1", kind: "asset", name: "Basket", x: 1, y: 0, z: 6, facing: null, state: "", in_frame: true }], events: [] },
    { shot: "S01-02", camera: { id: "wk-b", name: "B" }, things: [], events: ["Basket: leaves"] }, { shot: "S01-03", camera: null, things: [], events: [] }], findings,
    counts: { warning: live.filter((f) => f.severity === "warning").length, advice: live.filter((f) => f.severity === "advice").length, note: 0, deliberate: findings.length - live.length }, shots_without_camera: ["S01-03"], basis: "x", ...over };
};
let rep: ScReport;
const backend = (_c: string, a: { action: string; data: Record<string, unknown> }) => {
  switch (a.action) {
    case "inspect": return Promise.resolve(rep);
    case "override": rep = report([finding({ overridden: a.data.on as boolean, note: a.data.note as string })]); return Promise.resolve(rep);
    case "compare": return Promise.resolve({ file: "worldlock/ws-1/continuity/a.png", shot: a.data.shot, layout_match: 0.2, mean_difference: 0.4, cells: [], most_different: "bottom", uncovered: 0, words: "The broad layout is quite different. The picture differs most in the bottom.", note: "Advisory only. x" });
    default: return Promise.resolve({});
  }
};
const sent = (action: string) => invoke.mock.calls.filter(([, a]) => a.action === action).map(([, a]) => a.data);
const show = async (r: ScReport) => { rep = r; invoke.mockImplementation(backend); render(<SetContinuity dir="film" set="ws-1" />); await screen.findByLabelText("Continuity summary"); };
afterEach(() => { cleanup(); invoke.mockReset(); pick.mockReset(); });

describe("the continuity inspector", () => {
  it("says in words what it found, worst first, and what it could not check", async () => {
    await show(report([finding()]));
    expect(screen.getByLabelText("Continuity summary")).toHaveTextContent("1 likely problem · 0 worth a look");
    const li = screen.getByLabelText("Finding vanishes");
    expect(li).toHaveTextContent("Likely problem");
    expect(li).toHaveTextContent("Shots S01-01 → S01-02");
    expect(screen.getByText(/1 of 3 shots have no camera chosen/)).toBeInTheDocument();
  });

  it("lays the set out shot by shot with what each camera sees", async () => {
    await show(report([]));
    const t = screen.getByLabelText("Shot by shot");
    expect(within(t).getByText("Basket")).toBeInTheDocument();
    expect(within(t).getByText("Basket: leaves")).toBeInTheDocument();
    expect(within(t).getByText("not checked")).toBeInTheDocument();
  });

  it("says plainly when there is nothing to flag", async () => {
    await show(report([], { shots_without_camera: [] }));
    expect(screen.getByText("Nothing to flag.")).toBeInTheDocument();
  });

  it("marks a finding deliberate with the note typed, and takes the mark off again", async () => {
    await show(report([finding()]));
    fireEvent.change(screen.getByLabelText("Why it is deliberate (vanishes)"), { target: { value: "She takes it." } });
    fireEvent.click(screen.getByRole("button", { name: "It is deliberate" }));
    await waitFor(() => expect(sent("override")).toEqual([{ set: "ws-1", key: "ck-0123456789", note: "She takes it.", on: true }]));
    expect(await screen.findByText("Marked deliberate (1)")).toBeInTheDocument();
    fireEvent.click(screen.getByText("Marked deliberate (1)"));
    fireEvent.click(screen.getByRole("button", { name: "Check it again" }));
    await waitFor(() => expect(sent("override")[1]).toMatchObject({ on: false }));
  });

  it("compares a chosen picture with the set's view of a chosen shot and calls it advice", async () => {
    await show(report([]));
    fireEvent.change(screen.getByLabelText("Shot to compare"), { target: { value: "S01-02" } });
    pick.mockResolvedValueOnce("C:\P\gen.png");
    fireEvent.click(screen.getByRole("button", { name: "Choose a picture to compare…" }));
    await waitFor(() => expect(sent("compare")).toEqual([{ set: "ws-1", shot: "S01-02", picture: "C:\P\gen.png" }]));
    expect(await screen.findByLabelText("Picture comparison")).toHaveTextContent("The broad layout is quite different.");
    expect(screen.getByLabelText("Picture comparison")).toHaveTextContent("Advisory only");
    expect(pick.mock.calls[0][0].filters[0].extensions).toEqual(["png", "jpg", "jpeg", "webp"]);
  });

  it("shows an engine error in words", async () => {
    rep = report([]);
    invoke.mockImplementation((_c: string, a: { action: string }) => (a.action === "inspect" ? Promise.reject("Choose a set.") : Promise.resolve({})));
    render(<SetContinuity dir="film" set="ws-1" />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Choose a set.");
  });
});
