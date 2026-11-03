// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";

const invoke = vi.fn();
vi.mock("@tauri-apps/api/core", () => ({ invoke: (cmd: string, args: unknown) => invoke(cmd, args), convertFileSrc: (p: string) => p }));
vi.mock("@tauri-apps/plugin-dialog", () => ({ open: vi.fn() }));
import { AgentStudio } from "../../AgentStudio";
import type { AgentStudioState, LoadedProject } from "../../api";

const stages = ["story", "direction", "storyboard", "first_scene", "scenes", "audio", "preview", "export"].map((id, i) => ({ id, label: ["Story & shot plan", "Cast & visual direction", "Storyboard & keyframes", "First scene preview", "Remaining scenes", "Voices & sound", "Preview cut", "Final review & export"][i], state: "not_started" as const }));
const state = (planned = false): AgentStudioState => ({ version: 1, paused: false, current: "story", updated: 1,
  brief: { story: planned ? "A child follows a paper bird through a sleeping city." : "", style: "Storybook", duration: "3–4 minutes", aspect: "16:9", budget_limit: 30, checkin_mode: "balanced", checkpoints: ["story"] },
  stages: stages.map((s, i) => ({ ...s, state: planned && i === 0 ? "needs_approval" : "not_started" })), approvals: [], revisions: [],
  activity: [], existing: { scenes: 1, shots: 3 }, spending: { actual: 1, committed: 2, limit: 30, pricing_known: true }, jobs: { ready: 0, working: 1, failed: 0 } });
const project = { dir: "p", project: { title: "Bird", state: "ready", song: "" }, song_path: null, song_map: null, production: null, directed: null, jobs: [] } as LoadedProject;
afterEach(() => { cleanup(); invoke.mockReset(); });

describe("Agent Studio", () => {
  it("starts with a focused, non-spending story intake", async () => {
    invoke.mockResolvedValue(state(false));
    render(<AgentStudio project={project} onHome={() => {}} onManual={() => {}} />);
    expect(await screen.findByRole("heading", { name: "What should FilmCrafter make?" })).toBeInTheDocument();
    expect(screen.getByText(/Nothing is generated or charged yet/)).toBeInTheDocument();
    const create = screen.getByRole("button", { name: "Create production plan" });
    expect(create).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Story or idea"), { target: { value: "A child follows a paper bird through a sleeping city." } });
    expect(create).toBeEnabled();
  });

  it("shows actual budget categories and records approval without a render command", async () => {
    invoke.mockResolvedValue(state(true));
    render(<AgentStudio project={project} onHome={() => {}} onManual={() => {}} />);
    expect(await screen.findByText("$1.00 spent")).toBeInTheDocument();
    expect(screen.getByText("$2.00 committed")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Approve & continue" }));
    await waitFor(() => expect(invoke).toHaveBeenCalledWith("agent_studio", { dir: "p", action: "approve", data: { stage: "story", asset_versions: [] } }));
    expect(invoke.mock.calls.some(([cmd]) => cmd === "queue_render")).toBe(false);
  });

  it("switches to the precision editor and can pause future work", async () => {
    const manual = vi.fn(); invoke.mockResolvedValue(state(true));
    render(<AgentStudio project={project} onHome={() => {}} onManual={manual} />);
    fireEvent.click(await screen.findByRole("button", { name: "Manual Studio" }));
    expect(manual).toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: /Pause/ }));
    await waitFor(() => expect(invoke).toHaveBeenCalledWith("agent_studio", { dir: "p", action: "pause", data: {} }));
  });
});
