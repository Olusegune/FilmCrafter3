// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";

const invoke = vi.fn();
vi.mock("@tauri-apps/api/core", () => ({ invoke: (cmd: string, args: unknown) => invoke(cmd, args), convertFileSrc: (p: string) => p }));

import { curvePath, dbWords, MixerAutomation } from "../../MixerAutomation";
import type { AutoPoint, Cue, MixSettings } from "../../api";

const base = (over: Partial<MixSettings> = {}): MixSettings => ({ schema: 1, ducking_db: -9, duck_attack: 0.05, duck_release: 0.6, target_lufs: null, peak_db: -1, mute_lanes: [], solo: null, automation: {}, groups: {}, markers: [], ...over });
const cue = (id: string, over: Partial<Cue> = {}): Cue => ({ id, kind: "sfx", asset_id: "a", asset_name: id, asset_file: null, asset_seconds: 4, scene: 1, shot: null, start: 0, duration: null, gain_db: 0, fade_in: 0, fade_out: 0, loop: false, ducking: "auto",
  approval: "approved", note: "", source: "manual", fresh: [], needs_sound: false, created: 0, updated: 0, ...over });

let state: MixSettings;
const backend = (_c: string, a: { action: string; data: Record<string, unknown> }) => {
  if (a.action === "automation_set") state = { ...state, automation: { ...state.automation, [a.data.lane as string]: a.data.points as AutoPoint[] } };
  if (a.action === "group_set") state = { ...state, groups: { ...state.groups, [a.data.name as string]: { gain_db: (a.data.gain_db as number) ?? state.groups?.[a.data.name as string]?.gain_db ?? 0, muted: (a.data.muted as boolean) ?? false } } };
  if (a.action === "marker_add") state = { ...state, markers: [...(state.markers ?? []), { t: a.data.t as number, name: a.data.name as string }] };
  if (a.action === "crossfade") return Promise.resolve({ a: a.data.a, b: a.data.b, seconds: a.data.seconds, b_starts: 1.5 });
  return Promise.resolve(state);
};
const sent = (action: string) => invoke.mock.calls.filter(([, a]) => a.action === action).map(([, a]) => a.data);
const last = <T,>(xs: T[]): T | undefined => xs[xs.length - 1];
afterEach(() => { cleanup(); invoke.mockReset(); });
const show = async (cues: Cue[] = [], onChanged = vi.fn()) => { render(<MixerAutomation dir="film" cues={cues} onChanged={onChanged} />); await screen.findByText(/No curve/); return onChanged; };

describe("volume curves and groups", () => {
  it("says a level in words and draws a curve the way the mixer reads it", () => {
    expect(dbWords(0)).toBe("unchanged");
    expect(dbWords(-6)).toBe("-6 dB");
    expect(dbWords(3)).toBe("+3 dB");
    expect(curvePath([], 10)).toBe("");
    const flat = curvePath([{ t: 2, db: 0, curve: "linear" }], 10);
    expect(flat.startsWith("M0 ")).toBe(true);                                                                   // held before the first point
    const step = curvePath([{ t: 0, db: 0, curve: "hold" }, { t: 5, db: -30, curve: "linear" }], 10);
    expect(step).toContain("L150.0");                                                                            // runs flat to the next point before dropping
    const eased = curvePath([{ t: 0, db: 0, curve: "smooth" }, { t: 5, db: -30, curve: "linear" }], 10);
    expect(eased.split(" L").length).toBeGreaterThan(step.split(" L").length);                                  // the eased shape has extra points
  });

  it("starts with no curve, groups or markers and sends nothing until the user acts", async () => {
    state = base();
    invoke.mockImplementation(backend);
    await show();
    expect(invoke).toHaveBeenCalledTimes(1);
    expect(sent("settings")).toHaveLength(1);
    expect(screen.getByText(/No groups yet/)).toBeInTheDocument();
    expect(screen.getByText(/Needs two planned sounds/)).toBeInTheDocument();
  });

  it("adds a point to the chosen lane, then edits its level and shape and removes it", async () => {
    state = base();
    invoke.mockImplementation(backend);
    const changed = await show();
    fireEvent.click(screen.getByRole("button", { name: "Voices" }));
    fireEvent.click(screen.getByRole("button", { name: "Add a point" }));
    await waitFor(() => expect(sent("automation_set")).toEqual([{ lane: "dialogue", points: [{ t: 0, db: -6, curve: "linear" }] }]));
    expect(changed).toHaveBeenCalled();
    const level = await screen.findByLabelText("Point 1 level in dB");
    fireEvent.change(level, { target: { value: "-12" } });
    fireEvent.blur(level);
    await waitFor(() => expect(last(sent("automation_set"))).toEqual({ lane: "dialogue", points: [{ t: 0, db: -12, curve: "linear" }] }));
    fireEvent.change(await screen.findByLabelText("Point 1 shape"), { target: { value: "smooth" } });
    await waitFor(() => expect(last(sent("automation_set"))).toEqual({ lane: "dialogue", points: [{ t: 0, db: -12, curve: "smooth" }] }));
    expect(screen.getByRole("img", { name: "1 point curve" })).toBeInTheDocument();
    fireEvent.click(await screen.findByRole("button", { name: "Remove point 1" }));
    await waitFor(() => expect(last(sent("automation_set"))).toEqual({ lane: "dialogue", points: [] }));
    expect(await screen.findByText(/No curve/)).toBeInTheDocument();
  });

  it("does not resend a point the user did not change", async () => {
    state = base({ automation: { music: [{ t: 1, db: -6, curve: "linear" }] } });
    invoke.mockImplementation(backend);
    render(<MixerAutomation dir="film" cues={[]} />);
    const level = await screen.findByLabelText("Point 1 level in dB");
    fireEvent.blur(level);
    expect(sent("automation_set")).toHaveLength(0);
  });

  it("shows the engine's refusal in plain words and keeps working", async () => {
    state = base();
    invoke.mockImplementation((c: string, a: { action: string; data: Record<string, unknown> }) => (a.action === "marker_add" ? Promise.reject("A marker needs a name.") : backend(c, a)));
    await show();
    fireEvent.change(screen.getByLabelText("Marker time in seconds"), { target: { value: "3" } });
    fireEvent.change(screen.getByLabelText("Marker name"), { target: { value: "Hit" } });
    fireEvent.click(screen.getByRole("button", { name: "Add a marker" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("A marker needs a name.");
    await waitFor(() => expect(screen.getByRole("button", { name: "Add a marker" })).toBeEnabled());
    expect(screen.getByLabelText("Marker name")).toHaveValue("Hit");                                             // a refused marker is not thrown away
  });

  it("makes a group, sets its level, mutes it and removes it", async () => {
    state = base();
    invoke.mockImplementation(backend);
    await show();
    const make = screen.getByRole("button", { name: "Make a group" });
    expect(make).toBeDisabled();
    fireEvent.change(screen.getByLabelText("New group name"), { target: { value: "Rain bed" } });
    fireEvent.click(make);
    await waitFor(() => expect(sent("group_set")).toEqual([{ name: "Rain bed", gain_db: 0 }]));
    const lvl = await screen.findByLabelText("Rain bed level in dB");
    fireEvent.change(lvl, { target: { value: "-6" } });
    fireEvent.blur(lvl);
    await waitFor(() => expect(last(sent("group_set"))).toEqual({ name: "Rain bed", gain_db: -6 }));
    fireEvent.click(await screen.findByRole("checkbox", { name: "Muted" }));
    await waitFor(() => expect(last(sent("group_set"))).toEqual({ name: "Rain bed", muted: true }));
    fireEvent.click(await screen.findByRole("button", { name: "Remove group Rain bed" }));
    await waitFor(() => expect(sent("group_remove")).toEqual([{ name: "Rain bed" }]));
  });

  it("puts a cue in a group through the cue's own update", async () => {
    state = base({ groups: { Rain: { gain_db: 0, muted: false } } });
    invoke.mockImplementation(backend);
    render(<MixerAutomation dir="film" cues={[cue("c1"), cue("c2", { group: "Rain" })]} />);
    expect(await screen.findByText("1 cue(s)")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Cue to group"), { target: { value: "c1" } });
    await waitFor(() => expect(invoke.mock.calls.some(([cmd, a]) => cmd === "film_cues" && a.action === "update" && a.data.id === "c1" && a.data.group === "Rain")).toBe(true));
  });

  it("adds a marker only with a time and a name, and clears the fields after", async () => {
    state = base();
    invoke.mockImplementation(backend);
    await show();
    const add = screen.getByRole("button", { name: "Add a marker" });
    expect(add).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Marker time in seconds"), { target: { value: "2.5" } });
    expect(add).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Marker name"), { target: { value: "Door slam" } });
    fireEvent.click(add);
    await waitFor(() => expect(sent("marker_add")).toEqual([{ t: 2.5, name: "Door slam" }]));
    expect(await screen.findByText("Door slam")).toBeInTheDocument();
    expect(screen.getByLabelText("Marker name")).toHaveValue("");
  });

  it("crossfades two planned sounds and says where the second one now starts", async () => {
    state = base();
    invoke.mockImplementation(backend);
    const changed = await show([cue("rain"), cue("thunder"), cue("todo", { needs_sound: true })]);
    const fade = screen.getByRole("button", { name: "Crossfade" });
    expect(fade).toBeDisabled();
    expect(screen.getByLabelText("First sound").querySelectorAll("option")).toHaveLength(3);                     // a cue still needing a sound is not offered
    fireEvent.change(screen.getByLabelText("First sound"), { target: { value: "rain" } });
    expect(Array.from(screen.getByLabelText("Second sound").querySelectorAll("option")).map((o) => o.textContent)).not.toContain("rain");
    fireEvent.change(screen.getByLabelText("Second sound"), { target: { value: "thunder" } });
    fireEvent.change(screen.getByLabelText("Crossfade seconds"), { target: { value: "1.5" } });
    fireEvent.click(fade);
    await waitFor(() => expect(sent("crossfade")).toEqual([{ a: "rain", b: "thunder", seconds: 1.5 }]));
    expect(await screen.findByRole("status")).toHaveTextContent("starts at 1.5 s and the two overlap for 1.5 s");
    expect(changed).toHaveBeenCalled();
  });

  it("shows why it cannot load instead of an empty panel", async () => {
    invoke.mockRejectedValue("No film is open.");
    render(<MixerAutomation dir="film" cues={[]} />);
    expect(await screen.findByRole("alert")).toHaveTextContent("No film is open.");
  });
});
