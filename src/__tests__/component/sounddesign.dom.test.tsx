// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";

const invoke = vi.fn();
vi.mock("@tauri-apps/api/core", () => ({ invoke: (cmd: string, args: unknown) => invoke(cmd, args), convertFileSrc: (p: string) => p }));
const askFn = vi.fn();
vi.mock("../../ask", () => ({ ask: (...a: unknown[]) => askFn(...a) }));

import { coverageWords, placementWords, SoundDesign } from "../../SoundDesign";
import type { AudioAsset, FoleyEvent, SoundDesignScene } from "../../api";

const asset = (id: string, name: string) => ({ id, name, kind: "sfx", description: "", category: "", file: "", original_name: "", sha1: "", bytes: 1, seconds: 1 }) as unknown as AudioAsset;
const ASSETS = [asset("a-1", "rain loop"), asset("a-2", "basket hit")];
const ev = (over: Partial<FoleyEvent> = {}): FoleyEvent => ({ id: "fx-00000001", scene: 1, shot: "S01-01", action: "impact", source_object: "basket of oranges", by: "LILA", material: "fruit", surface: "wet pavement", distance: "mid", side: "centre",
  perspective: "", intensity: 0.75, start: 5.6, duration: null, asset_id: null, variations: [], approval: "suggested", note: "", motivated_by: "drops a basket", source: "derived", cue_id: null, placement: { gain_db: -4.5, pan: 0 }, cue: null, ...over });
const scene = (over: Partial<SoundDesignScene> = {}): SoundDesignScene => ({ scene: 1, environment: { id: "e_kitchen", name: "Kitchen" }, profile: null, layers: [], events: [], shots: [{ id: "S01-01", duration: 10 }],
  coverage: { events: 0, approved: 0, without_sound: [], layers: 0, layers_without_sound: [], has_profile: false, environment: "Kitchen" }, ...over });

let cur: SoundDesignScene;
const backend = (_c: string, a: { action: string; data: Record<string, unknown> }) => {
  switch (a.action) {
    case "scene": return Promise.resolve(cur);
    case "profile_set": cur = scene({ profile: a.data.profile as never, coverage: { ...cur.coverage, has_profile: true } }); return Promise.resolve(cur);
    case "suggest": return Promise.resolve({ proposals: [{ action: "impact", source_object: "basket of oranges", by: "LILA", material: "fruit", surface: "wet pavement", intensity: 0.75, distance: "mid", side: "centre", start: 5.6, motivated_by: "drops a basket" }], note: "Only sounds the written action names are proposed." });
    case "event_add": cur = scene({ events: [ev()] }); return Promise.resolve(cur);
    case "event_update": cur = scene({ events: [ev({ ...(a.data as object) } as Partial<FoleyEvent>)] }); return Promise.resolve(cur);
    case "event_remove": cur = scene(); return Promise.resolve(cur);
    case "candidates": return Promise.resolve({ candidates: [{ id: "a-2", name: "basket hit", why: ["basket"] }] });
    case "to_cues": cur = { ...cur, made: ["ly-1", "fx-00000001"], updated: [], waiting: [{ kind: "event", id: "fx-2", name: "door" }] }; return Promise.resolve(cur);
    default: return Promise.resolve({});
  }
};
const sent = (action: string) => invoke.mock.calls.filter(([, a]) => a.action === action).map(([, a]) => a.data);
const open = async (onChanged = () => {}) => { render(<SoundDesign dir="film" scene={1} assets={ASSETS} onChanged={onChanged} />); fireEvent.click(screen.getByRole("button", { name: "Open sound design…" })); await screen.findByText(/How this place sounds/); };
afterEach(() => { cleanup(); invoke.mockReset(); askFn.mockReset(); });

describe("sound design", () => {
  it("says a placement and what is missing in plain words", () => {
    expect(placementWords({ gain_db: -6, pan: -0.6 })).toBe("-6 dB, to the left");
    expect(placementWords({ gain_db: 1.5, pan: 0.6 })).toBe("+1.5 dB, to the right");
    expect(placementWords({ gain_db: 0, pan: 0 })).toBe("0 dB, in the centre");
    const c = scene().coverage;
    expect(coverageWords(c)).toContain("no soundscape yet");
    expect(coverageWords({ ...c, has_profile: true, without_sound: ["a", "b"], layers_without_sound: ["x"] })).toBe("Still to do: 1 ambience layer still need a sound; 2 sounds still need a sound from the library.");
    expect(coverageWords({ ...c, has_profile: true })).toBe("Nothing is waiting for a sound.");
  });

  it("asks the engine for nothing until it is opened", () => {
    invoke.mockImplementation(backend);
    render(<SoundDesign dir="film" scene={1} assets={ASSETS} onChanged={() => {}} />);
    expect(invoke).not.toHaveBeenCalled();
  });

  it("saves how a place sounds, with its ambience layers and their distance, only when something changed", async () => {
    cur = scene();
    invoke.mockImplementation(backend);
    await open();
    const save = screen.getByRole("button", { name: "Save how this place sounds" });
    expect(save).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Weather"), { target: { value: "heavy rain" } });
    fireEvent.change(screen.getByLabelText(/Surfaces underfoot/), { target: { value: "wet pavement, gravel" } });
    fireEvent.click(screen.getByRole("button", { name: "Add a layer" }));
    fireEvent.change(screen.getByLabelText("Layer 1 name"), { target: { value: "Rain on the roof" } });
    fireEvent.change(screen.getByLabelText("Layer 1 distance"), { target: { value: "near" } });
    fireEvent.change(screen.getByLabelText("Layer 1 sound"), { target: { value: "a-1" } });
    fireEvent.click(save);
    await waitFor(() => expect(sent("profile_set")).toHaveLength(1));
    const d = sent("profile_set")[0] as { environment: string; profile: { weather: string; surfaces: string[]; layers: { name: string; distance: string; asset_id: string }[] } };
    expect(d.environment).toBe("e_kitchen");
    expect(d.profile.weather).toBe("heavy rain");
    expect(d.profile.surfaces).toEqual(["wet pavement", "gravel"]);
    expect(d.profile.layers).toMatchObject([{ name: "Rain on the roof", distance: "near", asset_id: "a-1" }]);
  });

  it("proposes only what the action names, shows why, and adds one to the plan as derived", async () => {
    cur = scene();
    invoke.mockImplementation(backend);
    await open();
    fireEvent.click(screen.getByRole("button", { name: "Suggest sounds for S01-01" }));
    const list = await screen.findByLabelText("Suggestions");
    expect(within(list).getByText(/drops a basket/)).toBeInTheDocument();
    expect(within(list).getByText(/Only sounds the written action names/)).toBeInTheDocument();
    expect(sent("event_add")).toEqual([]);
    fireEvent.click(within(list).getByRole("button", { name: "Add to the plan" }));
    await waitFor(() => expect(sent("event_add")).toHaveLength(1));
    expect(sent("event_add")[0]).toMatchObject({ shot: "S01-01", action: "impact", source_object: "basket of oranges", source: "derived", start: 5.6 });
    expect(await screen.findByLabelText("Foley sounds")).toHaveTextContent("impact: basket of oranges");
  });

  it("changes distance, side, sound and approval of one event through the engine", async () => {
    cur = scene({ events: [ev()] });
    invoke.mockImplementation(backend);
    await open();
    fireEvent.change(screen.getByLabelText("Distance of fx-00000001"), { target: { value: "far" } });
    await waitFor(() => expect(sent("event_update")[0]).toEqual({ id: "fx-00000001", distance: "far" }));
    fireEvent.change(screen.getByLabelText("Side of fx-00000001"), { target: { value: "left" } });
    await waitFor(() => expect(sent("event_update")[1]).toEqual({ id: "fx-00000001", side: "left" }));
    fireEvent.change(screen.getByLabelText("Sound of fx-00000001"), { target: { value: "a-2" } });
    await waitFor(() => expect(sent("event_update")[2]).toEqual({ id: "fx-00000001", asset_id: "a-2" }));
    fireEvent.click(screen.getByLabelText("Approve fx-00000001"));
    await waitFor(() => expect(sent("event_update")[3]).toEqual({ id: "fx-00000001", approval: "approved" }));
  });

  it("looks in the library first and uses what it finds", async () => {
    cur = scene({ events: [ev()] });
    invoke.mockImplementation(backend);
    await open();
    fireEvent.click(screen.getByRole("button", { name: "Find in my library" }));
    fireEvent.click(await screen.findByRole("button", { name: "basket hit" }));
    await waitFor(() => expect(sent("event_update")).toEqual([{ id: "fx-00000001", asset_id: "a-2" }]));
  });

  it("asks before taking a sound out of the plan, and does nothing on no", async () => {
    cur = scene({ events: [ev()] });
    invoke.mockImplementation(backend);
    askFn.mockResolvedValueOnce(false).mockResolvedValueOnce(true);
    await open();
    fireEvent.click(screen.getByRole("button", { name: "Remove fx-00000001" }));
    await waitFor(() => expect(askFn).toHaveBeenCalledTimes(1));
    expect(sent("event_remove")).toEqual([]);
    fireEvent.click(screen.getByRole("button", { name: "Remove fx-00000001" }));
    await waitFor(() => expect(sent("event_remove")).toEqual([{ id: "fx-00000001" }]));
  });

  it("puts the plan into the film as cues, says what was made and what is waiting, and refreshes the scene", async () => {
    cur = scene({ events: [ev({ approval: "approved", asset_id: "a-2" })] });
    invoke.mockImplementation(backend);
    const changed = vi.fn();
    await open(changed);
    fireEvent.click(screen.getByRole("button", { name: "Put into the film" }));
    await waitFor(() => expect(sent("to_cues")).toEqual([{ scene: 1 }]));
    expect(await screen.findByText(/2 made, 0 brought up to date, 1 waiting for a sound/)).toBeInTheDocument();
    expect(screen.getByLabelText("Waiting")).toHaveTextContent("door");
    expect(changed).toHaveBeenCalled();
  });

  it("shows the engine's own words when something fails", async () => {
    cur = scene();
    invoke.mockImplementation((c: string, a: { action: string; data: Record<string, unknown> }) => (a.action === "suggest" ? Promise.reject("That shot isn't in the film.") : backend(c, a)));
    await open();
    fireEvent.click(screen.getByRole("button", { name: "Suggest sounds for S01-01" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("isn't in the film");
  });
});
