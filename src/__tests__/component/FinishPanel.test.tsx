// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";
const invoke = vi.fn();
vi.mock("@tauri-apps/api/core", () => ({ invoke: (cmd: string, args: unknown) => invoke(cmd, args), convertFileSrc: (p: string) => p }));
vi.mock("@tauri-apps/plugin-opener", () => ({ revealItemInDir: vi.fn(() => Promise.resolve()) }));
import { FinishPanel } from "../../FinishPanel";

afterEach(() => { cleanup(); invoke.mockReset(); });
const presets = { looks: [{ id: "none", label: "No look", note: "n" }, { id: "film", label: "Film grain", note: "Fine grain." }], profiles: [{ id: "web", label: "Web (H.264)", note: "Plays everywhere.", ext: "mp4" }, { id: "prores", label: "ProRes 422 HQ", note: "For editors.", ext: "mov" }], strengths: ["gentle", "balanced", "strong"] };
const rep = (level: string, score: number) => ({ frames: 72, level, confidence: "high", global: score, local: 0, score, note: "Brightness pulses clearly from frame to frame." });

describe("Finish and deliver", () => {
  it("tells you to export first when there is no film", async () => {
    invoke.mockImplementation((_c: string, a: { action: string }) => Promise.resolve(a.action === "videos" ? { videos: [] } : presets));
    render(<FinishPanel dir="p" />);
    expect(await screen.findByText(/Export a film first/)).toBeInTheDocument();
  });
  it("measures flicker, shows the measured gain from a calmer copy, and makes a delivery copy; only the local command is used", async () => {
    invoke.mockImplementation((_c: string, a: { action: string; data?: { profile?: string } }) => {
      if (a.action === "videos") return Promise.resolve({ videos: [{ ref: "project:exports/film.mp4", name: "film.mp4", bytes: 50e6, at: 1 }] });
      if (a.action === "presets") return Promise.resolve(presets);
      if (a.action === "flicker") return Promise.resolve({ ref: "x", report: rep("Strong", 7.2), limits: "Measured on brightness." });
      if (a.action === "restore") return Promise.resolve({ id: "r1", source: "x", output: "project:restore/r.mp4", output_path: "C:/p/restore/r.mp4", strength: "balanced", before: rep("Strong", 7.25), after: rep("Calm", 0.38), gain: 6.9, better: true, note: "Calmer than the original." });
      return Promise.resolve({ id: "f1", source: "project:exports/film.mp4", output: "project:finish/f.mp4", output_path: "C:/p/finish/f.mp4", look: "film", profile: a.data?.profile, bytes: 20e6, source_bytes: 50e6 });
    });
    render(<FinishPanel dir="p" />);
    fireEvent.click(await screen.findByText(/Finish and deliver/));
    fireEvent.click(await screen.findByRole("button", { name: "Check for flicker" }));
    expect(await screen.findByText("Strong")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Make a calmer copy" }));
    expect(await screen.findByText(/Strong \(7.25\) → Calm \(0.38\)/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Make the delivery copy" }));
    await waitFor(() => expect(invoke).toHaveBeenCalledWith("video_finish", { dir: "p", action: "finish", data: { ref: "project:exports/film.mp4", look: "none", profile: "web" } }));
    expect(await screen.findByText(/Made 20 MB from 50 MB/)).toBeInTheDocument();
    expect(invoke.mock.calls.every(([c]) => c === "video_finish")).toBe(true);
  });
});
