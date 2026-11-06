// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";

const invoke = vi.fn();
vi.mock("@tauri-apps/api/core", () => ({ invoke: (cmd: string, args: unknown) => invoke(cmd, args), convertFileSrc: (p: string) => p }));

import { MusicDirector, planWords, spotWords } from "../../MusicDirector";
import type { AudioAsset, Motif, MusicPlan, MusicSpot } from "../../api";

const spot = (over: Partial<MusicSpot> = {}): MusicSpot => ({ id: "sp-1", scene: 2, start_shot: "S02-01", end_shot: "S02-02", decision: "score", role: "", energy_in: 2, energy_out: 4, mood: "tension", tempo: "", intent: "", enters: "", exits: "", note: "",
  instruments: [], motif_ids: [], level_db: -6, fade_in: 1.5, fade_out: 2, asset_id: null, approval: "suggested", source: "manual", cue_id: null, cue: null, ...over });
const motif = (over: Partial<Motif> = {}): Motif => ({ id: "mo-1", name: "Sarah's theme", kind: "character", subject: "Sarah", mood: "hopeful", tempo: "slow", key: "", description: "four rising notes", note: "", instruments: ["piano"], ...over });
const plan = (over: Partial<MusicPlan> = {}): MusicPlan => ({ motifs: [], spots: [], records: {}, report: { scenes: [], undecided: [1, 2, 3], motifs: [], jumps: [], records: [], music_share: 0, seconds: 30, needs_attention: true } as MusicPlan["report"], ...over });
const asset = (id: string, name: string, kind: "music" | "sfx" = "music"): AudioAsset => ({ id, kind, name } as AudioAsset);

let state: MusicPlan;
const shots = [{ id: "S02-01", seconds: 3 }, { id: "S02-02", seconds: 4 }];
const backend = (_c: string, a: { action: string; data: Record<string, unknown> }) => {
  if (a.action === "spot_set" && !a.data.id) state = { ...state, spots: [...state.spots, spot({ id: "sp-new", ...(a.data as Partial<MusicSpot>) })] };
  else if (a.action === "spot_set") state = { ...state, spots: state.spots.map((s) => (s.id === a.data.id ? { ...s, ...(a.data as Partial<MusicSpot>) } : s)) };
  if (a.action === "motif_set") state = { ...state, motifs: [...state.motifs, motif({ id: "mo-new", name: a.data.name as string })] };
  if (a.action === "suggest") return Promise.resolve({ scene: 2, proposal: { scene: 2, decision: "score", mood: "tension", energy_in: 3, energy_out: 4, start_shot: "S02-01", end_shot: "S02-02", source: "derived" }, because: [{ shot: "S02-01", word: "chases", mood: "tension" }], motifs: [], spoken_shots: 0, shots: 2, note: "A proposal from the written words only." });
  if (a.action === "prompt") return Promise.resolve({ spot: a.data.id, prompt: "Instrumental film score cue, no vocals.", duration: 7, instrumental: true, shots: [], how: "Nothing has been sent or charged." });
  if (a.action === "candidates") return Promise.resolve({ candidates: [{ id: "m1", name: "tense strings", why: ["mood"] }] });
  if (a.action === "to_cues") return Promise.resolve({ ...state, made: ["sp-1"], updated: [], waiting: [], blocked: [{ id: "sp-2", why: "x" }], silent: [] });
  return Promise.resolve(state);
};
const sent = (action: string) => invoke.mock.calls.filter(([, a]) => a.action === action).map(([, a]) => a.data);
afterEach(() => { cleanup(); invoke.mockReset(); });
const show = async (onChanged = vi.fn(), assets = [asset("m1", "tense strings"), asset("fx", "door", "sfx")]) => {
  render(<MusicDirector dir="film" scene={2} shots={shots} assets={assets} onChanged={onChanged} />);
  fireEvent.click(screen.getByRole("button", { name: "Open the music director…" }));
  await screen.findByLabelText("State of the music plan");
  return onChanged;
};

describe("the music director", () => {
  it("says the state of the plan and of a spot in plain words", () => {
    expect(planWords(plan())).toBe("3 scenes have no decision yet (1, 2, 3). Music plays in about 0% of the film.");
    const full = plan({ report: { ...plan().report, undecided: [], music_share: 0.426, records: [{ id: "a", name: "n", commercial: "unknown", status: "none", by: "", scenes: [], problems: ["x"] }], motifs: [{ id: "m", name: "M", kind: "theme", scenes: [], note: "Never used." }] } });
    expect(planWords(full)).toBe("1 piece of music in the plan needs a rights decision; 1 motif is not used anywhere. Music plays in about 43% of the film.");
    expect(spotWords(spot())).toBe("tension, energy 2 to 4 (quiet to driving)");
    expect(spotWords(spot({ decision: "silence" }))).toBe("Silence, on purpose");
    expect(spotWords(spot({ decision: "source" }))).toBe("Music in the world");
  });

  it("does nothing until it is opened", () => {
    state = plan();
    invoke.mockImplementation(backend);
    render(<MusicDirector dir="film" scene={2} shots={shots} assets={[]} onChanged={() => {}} />);
    expect(invoke).not.toHaveBeenCalled();
    expect(screen.getByText(/nothing is generated or sent/i)).toBeInTheDocument();
  });

  it("adds a spot for the open scene across its shots and changes its decision", async () => {
    state = plan();
    invoke.mockImplementation(backend);
    await show();
    fireEvent.click(screen.getByRole("button", { name: "Add a spot" }));
    await waitFor(() => expect(sent("spot_set")).toEqual([{ scene: 2, decision: "score", start_shot: "S02-01", end_shot: "S02-02" }]));
    fireEvent.change(await screen.findByLabelText("Decision"), { target: { value: "silence" } });
    await waitFor(() => expect(sent("spot_set")[sent("spot_set").length - 1]).toEqual({ id: "sp-new", decision: "silence" }));
    expect(screen.queryByLabelText("Mood")).toBeNull();                                                      // a silent spot has no mood to set
  });

  it("only offers the film's music to a spot, and chooses it", async () => {
    state = plan({ spots: [spot()] });
    invoke.mockImplementation(backend);
    await show();
    const sel = screen.getByLabelText("Music for this spot");
    expect(Array.from(sel.querySelectorAll("option")).map((o) => o.textContent)).toEqual(["No music chosen yet", "tense strings"]);
    fireEvent.change(sel, { target: { value: "m1" } });
    await waitFor(() => expect(sent("spot_set")).toEqual([{ id: "sp-1", asset_id: "m1" }]));
  });

  it("shows only this scene's spots", async () => {
    state = plan({ spots: [spot(), spot({ id: "sp-9", scene: 5 })] });
    invoke.mockImplementation(backend);
    await show();
    expect(screen.getAllByLabelText(/^Spot /)).toHaveLength(1);
  });

  it("suggests from the scene, says the words it acted on, and adds it only when asked", async () => {
    state = plan();
    invoke.mockImplementation(backend);
    await show();
    fireEvent.click(screen.getByRole("button", { name: "Suggest from the scene (free)" }));
    const box = await screen.findByLabelText("Suggestion");
    expect(box).toHaveTextContent("“chases” (S02-01)");
    expect(box).toHaveTextContent("A proposal from the written words only.");
    expect(sent("spot_set")).toHaveLength(0);
    fireEvent.click(within(box).getByRole("button", { name: "Add it as a spot" }));
    await waitFor(() => expect(sent("spot_set")).toHaveLength(1));
    expect(sent("spot_set")[0]).toMatchObject({ scene: 2, decision: "score", mood: "tension", approval: "suggested", source: "derived" });
  });

  it("shows the words to ask for the music and says nothing was sent", async () => {
    state = plan({ spots: [spot()] });
    invoke.mockImplementation(backend);
    await show();
    fireEvent.click(screen.getByRole("button", { name: "Words to ask for it" }));
    expect(await screen.findByText("Instrumental film score cue, no vocals.")).toBeInTheDocument();
    expect(screen.getByText("Nothing has been sent or charged.")).toBeInTheDocument();
    expect(invoke.mock.calls.every(([cmd]) => cmd === "film_music")).toBe(true);                             // no provider, no generation
  });

  it("finds music in the library and uses it", async () => {
    state = plan({ spots: [spot()] });
    invoke.mockImplementation(backend);
    await show();
    fireEvent.click(screen.getByRole("button", { name: "Find in library" }));
    fireEvent.click(await screen.findByRole("button", { name: "Use this" }));
    await waitFor(() => expect(sent("spot_set")).toEqual([{ id: "sp-1", asset_id: "m1" }]));
  });

  it("adds a motif with its instruments split on commas and clears the form", async () => {
    state = plan();
    invoke.mockImplementation(backend);
    await show();
    const add = screen.getByRole("button", { name: "Add the motif" });
    expect(add).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Motif name"), { target: { value: "Rain" } });
    fireEvent.change(screen.getByLabelText("Motif instruments"), { target: { value: "piano, cello ," } });
    fireEvent.click(add);
    await waitFor(() => expect(sent("motif_set")).toEqual([{ name: "Rain", kind: "theme", subject: "", mood: "", tempo: "", description: "", instruments: ["piano", "cello"] }]));
    expect(await screen.findByText("Rain")).toBeInTheDocument();
    expect(screen.getByLabelText("Motif name")).toHaveValue("");
  });

  it("puts the approved spots into the film and says what was left out", async () => {
    state = plan({ spots: [spot({ approval: "approved" })] });
    invoke.mockImplementation(backend);
    const changed = await show();
    fireEvent.click(screen.getByRole("button", { name: "Put into the film" }));
    expect(await screen.findByRole("status")).toHaveTextContent("1 made, 0 updated. 1 left out: the licence does not allow commercial use.");
    expect(changed).toHaveBeenCalled();
    expect(sent("to_cues")).toEqual([{ scene: 2 }]);
  });

  it("records who approved a piece of music, needing a name, and shows the licence problem it cannot fix", async () => {
    const rep = { ...plan().report, records: [{ id: "m1", name: "tense strings", commercial: "unknown", status: "none", by: "", scenes: [], problems: ["Commercial use is not known.", "No recorded decision."] }] };
    state = plan({ report: rep });
    invoke.mockImplementation(backend);
    await show();
    expect(screen.getByText("Commercial use is not known.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Record a decision…" }));
    const approve = screen.getByRole("button", { name: "Approve" });
    expect(approve).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Decided by"), { target: { value: "Ada" } });
    fireEvent.change(screen.getByLabelText("For scenes"), { target: { value: "1, 2, x" } });
    fireEvent.change(screen.getByLabelText("Licence note"), { target: { value: "receipt 7" } });
    fireEvent.click(approve);
    await waitFor(() => expect(sent("record_set")).toEqual([{ asset_id: "m1", status: "approved", by: "Ada", scenes: [1, 2], licence_ref: "receipt 7" }]));
  });

  it("shows the engine's refusal in plain words", async () => {
    state = plan();
    invoke.mockImplementation((c: string, a: { action: string; data: Record<string, unknown> }) => (a.action === "spot_set" ? Promise.reject("At most 6 spots in one scene.") : backend(c, a)));
    await show();
    fireEvent.click(screen.getByRole("button", { name: "Add a spot" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("At most 6 spots in one scene.");
  });
});
