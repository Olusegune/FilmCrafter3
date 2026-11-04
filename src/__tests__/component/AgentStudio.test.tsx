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
  activity: [], existing: { scenes: 1, shots: 3 }, spending: { actual: 1, committed: 2, limit: 30, pricing_known: true }, jobs: { ready: 0, working: 1, failed: 0 },
  inbox: planned ? [{ id: "approval:story", kind: "approval", stage: "story", title: "Story & shot plan", detail: "Creative approval required before production continues.", priority: 1, action: "review" }] : [],
  orchestration: { status: planned ? "waiting" : "ready", next_action: planned ? "Approve Story & shot plan" : "Continue Story & shot plan", blockers: [], active_jobs: 0, evidence: {}, safe_to_continue: !planned, message: "Reconciled" },
  first_scene_proof: { state: "ready", scene: 1, heading: "Street", shots: ["S01-01", "S01-02", "S01-03"], missing_keyframes: ["S01-01"], missing_video: ["S01-01", "S01-02", "S01-03"], estimated_usd: 0, requires_cost_review: false, can_start_local: true, blockers: [], message: "This proof scene can run locally without provider charges." } });
const project = { dir: "p", project: { title: "Bird", state: "ready", song: "" }, song_path: null, song_map: null, production: null, directed: null, jobs: [] } as LoadedProject;
afterEach(() => { cleanup(); invoke.mockReset(); });

describe("Agent Studio", () => {
  it("starts with a focused, non-spending story intake", async () => {
    invoke.mockResolvedValue(state(false));
    render(<AgentStudio project={project} onHome={() => {}} onManual={() => {}} />);
    expect(await screen.findByRole("heading", { name: "What should FilmCrafter make?" })).toBeInTheDocument();
    expect(screen.getByText(/Nothing is generated or charged yet/)).toBeInTheDocument();
    const create = screen.getByRole("button", { name: "Analyse script" });
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

  it("previews a focused revision impact before recording it", async () => {
    const planned = state(true);
    invoke.mockImplementation((cmd: string, args: { action?: string }) => cmd === "agent_studio" && args.action === "impact"
      ? Promise.resolve({ stage: "story", note: "Warm Chloe's shot", affected_shots: ["S01-01"], affected_scenes: [1], matched_entities: ["Chloe"], downstream_stages: ["direction"], preserved_approved_assets: 2, regeneration_count: 1, scope: "targeted", needs_clarification: false, warning: "Only matched work is marked for revision; unrelated approved assets stay locked." })
      : cmd === "agent_studio" ? Promise.resolve(planned) : Promise.resolve({ current: null, styles: [] }));
    render(<AgentStudio project={project} onHome={() => {}} onManual={() => {}} />);
    fireEvent.change(await screen.findByLabelText("Ask for a focused change"), { target: { value: "Warm Chloe's shot" } });
    fireEvent.click(screen.getByRole("button", { name: "Preview revision impact" }));
    expect(await screen.findByText("1 shot affected")).toBeInTheDocument();
    expect(screen.getByText("2 assets")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Record focused revision" })).toBeEnabled();
  });

  it("starts only the local first-scene proof and explains that later scenes stay untouched", async () => {
    invoke.mockResolvedValue(state(true));
    render(<AgentStudio project={project} onHome={() => {}} onManual={() => {}} />);
    expect(await screen.findByText(/Remaining scenes stay untouched/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Make first scene locally" }));
    await waitFor(() => expect(invoke).toHaveBeenCalledWith("agent_studio", { dir: "p", action: "start_first_scene", data: {} }));
  });

  it("shows a complete production package as suggestions and lets every department choose its model", async () => {
    const proposed = { ...state(false), analysis: { status: "proposed" as const, model: "claude", logline: "A child follows a paper bird.", genre: "Fantasy", tone: "Wonder", visual_style: "cinematic", visual_style_reason: "Grounded wonder", director_style_id: "", director_style_reason: "No named profile needed", questions: [],
      characters: [{ name: "Mia", role: "Lead", appearance: "Small silhouette", wardrobe: "Yellow coat", voice: "Quiet and curious" }], locations: [{ name: "Sleeping city", design: "Empty streets", lighting: "Moonlit" }], props: [{ name: "Bird", design: "Folded paper", continuity: "Torn left wing" }], scenes: [{ heading: "EXT. STREET", summary: "Mia follows." }], sound_direction: "A hushed city", score_prompt: "Felt piano and glass harmonics", sfx_plan: [{ scene: "Street", sound: "Paper wings", purpose: "Lead the child" }], motion_graphics: [{ type: "Title", text: "Paper Bird", when: "Opening" }] } };
    invoke.mockImplementation((cmd: string, args: { action?: string }) => cmd === "agent_studio" ? Promise.resolve(proposed) : cmd === "routing" && args.action === "models" ? Promise.resolve({ image: [{ label: "Image One", provider: "fal", model: "img-1" }], video: [{ label: "Video One", provider: "kie", model: "vid-1" }] }) : cmd === "film_audiogen" ? Promise.resolve({ providers: [{ id: "elevenlabs_music", label: "ElevenLabs Music", kind: "music", cost_words: "price shown first" }, { id: "elevenlabs_sfx", label: "ElevenLabs SFX", kind: "sfx", cost_words: "credits shown first" }] }) : Promise.resolve({ current: null, styles: [] }));
    render(<AgentStudio project={project} onHome={() => {}} onManual={() => {}} />);
    expect(await screen.findByRole("heading", { name: "Character design" })).toBeInTheDocument();
    expect(screen.getByText("Felt piano and glass harmonics")).toBeInTheDocument();
    expect(screen.getByText("Paper wings")).toBeInTheDocument();
    expect(screen.getByText(/Paper Bird/)).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "Filmmaker craft profile" })).toHaveValue("");
  });
});
