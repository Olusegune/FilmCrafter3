// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";
const invoke = vi.fn();
vi.mock("@tauri-apps/api/core", () => ({ invoke: (cmd: string, args: unknown) => invoke(cmd, args), convertFileSrc: (p: string) => `asset://${p}` }));
import { FidelitySheet } from "../../FidelitySheet";

afterEach(() => { cleanup(); invoke.mockReset(); });
const rep = (verdict: string) => ({ width: 1536, height: 1024, aspect: "3:2", format: "PNG", analysed_at: "1536×1024", reduced: false, verdict, action: verdict === "ok" ? "Ready to animate. No clean-up needed." : "Optional: Clean Enhance can tidy this up.", low_resolution: false,
  not_assessed: ["Faces and hands (needs an image model)"], rows: [{ id: "sharpness", label: "Sharpness", level: "Moderate", value: 0.2, confidence: "high", note: "Gently defined." }, { id: "noise", label: "Noise", level: "Low", value: 0.5, confidence: "low", note: "Clean." }] });

describe("Picture quality sheet", () => {
  it("shows the measured report, cleans, compares the real files, and can use then undo", async () => {
    invoke.mockImplementation((_cmd: string, a: { action?: string }) => {
      if (a.action === "check") return Promise.resolve({ shot: "S01", ref: "project:k.png", report: rep("optional") });
      if (a.action === "enhance") return Promise.resolve({ id: "f1", shot: "S01", source: "project:k.png", output: "project:fidelity/f1.png", strength: 0.5, state: "ready", size: [1536, 1024], source_path: "C:/p/k.png", output_path: "C:/p/fidelity/f1.png", before_report: rep("optional"), after_report: rep("ok") });
      return Promise.resolve({});
    });
    const changed = vi.fn();
    render(<FidelitySheet dir="p" shot="S01" onClose={() => {}} onChanged={changed} />);
    expect(await screen.findByText("Optional: Clean Enhance can tidy this up.")).toBeInTheDocument();
    expect(screen.getByText(/low confidence/)).toBeInTheDocument();                       // uncertainty is shown, not hidden
    expect(screen.getByText(/Not assessed: Faces and hands/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Clean up (free)" }));
    const before = await screen.findByAltText("Original");
    const after = screen.getByAltText("Cleaned");
    expect(before).toHaveAttribute("src", "asset://C:/p/k.png");
    expect(after).toHaveAttribute("src", "asset://C:/p/fidelity/f1.png");
    fireEvent.click(screen.getByRole("button", { name: "Cleaned at 100%" }));
    expect(screen.getByAltText("Cleaned at 100%")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Back to the slider" }));
    fireEvent.click(screen.getByRole("button", { name: "Use the cleaned picture" }));
    await waitFor(() => expect(invoke).toHaveBeenCalledWith("fidelity", { dir: "p", action: "apply", data: { id: "f1" } }));
    expect(changed).toHaveBeenCalled();
    fireEvent.click(await screen.findByRole("button", { name: "Go back to the original" }));
    await waitFor(() => expect(invoke).toHaveBeenCalledWith("fidelity", { dir: "p", action: "revert", data: { shot: "S01" } }));
  });
  it("never spends: it only ever calls the local fidelity command", async () => {
    invoke.mockResolvedValue({ shot: "S01", ref: "x", report: rep("ok") });
    render(<FidelitySheet dir="p" shot="S01" onClose={() => {}} onChanged={() => {}} />);
    await screen.findByText("Ready to animate. No clean-up needed.");
    expect(invoke.mock.calls.every(([c]) => c === "fidelity")).toBe(true);
  });
  it("offers local upscaling only when the tool is installed, and says how to get it when not", async () => {
    invoke.mockImplementation((_c: string, a: { action?: string }) => Promise.resolve(a.action === "upscale_status" ? { available: false, models: [], help: "Local upscaling needs the free Real-ESRGAN tool. Nothing is downloaded for you." } : { shot: "S01", ref: "x", report: rep("ok") }));
    render(<FidelitySheet dir="p" shot="S01" onClose={() => {}} onChanged={() => {}} />);
    expect(await screen.findByText(/Nothing is downloaded for you/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "2× larger" })).toBeNull();
  });
  it("enlarges with the installed tool, shows the real files and the factor, and stays local", async () => {
    invoke.mockImplementation((_c: string, a: { action?: string }) => {
      if (a.action === "upscale_status") return Promise.resolve({ available: true, models: ["realesrgan-x4plus"], help: "" });
      if (a.action === "upscale") return Promise.resolve({ id: "u1", shot: "S01", source: "project:k.png", output: "project:fidelity/u1.png", strength: 0, method: "local_upscale", model: "realesrgan-x4plus", scale: 2, state: "ready", size: [3072, 2048], source_path: "C:/p/k.png", output_path: "C:/p/fidelity/u1.png", before_report: rep("optional"), after_report: rep("ok") });
      return Promise.resolve({ shot: "S01", ref: "x", report: rep("ok") });
    });
    render(<FidelitySheet dir="p" shot="S01" onClose={() => {}} onChanged={() => {}} />);
    fireEvent.click(await screen.findByRole("button", { name: "2× larger" }));
    expect(await screen.findByAltText("Cleaned")).toHaveAttribute("src", "asset://C:/p/fidelity/u1.png");
    expect(screen.getByText(/2× larger \(3072 × 2048\) with realesrgan-x4plus/)).toBeInTheDocument();
    expect(invoke).toHaveBeenCalledWith("fidelity", { dir: "p", action: "upscale", data: { shot: "S01", scale: 2, anime: false } });
    fireEvent.click(screen.getByRole("button", { name: "Use as the animation master" }));
    await waitFor(() => expect(invoke).toHaveBeenCalledWith("fidelity", { dir: "p", action: "master_set", data: { id: "u1" } }));
    expect(await screen.findByText(/animation master: the video model is given this picture/)).toBeInTheDocument();
    expect(invoke.mock.calls.every(([c]) => c === "fidelity")).toBe(true);
  });
});
