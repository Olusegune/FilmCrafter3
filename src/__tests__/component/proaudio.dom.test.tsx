// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";

const invoke = vi.fn();
vi.mock("@tauri-apps/api/core", () => ({ invoke: (cmd: string, args: unknown) => invoke(cmd, args), convertFileSrc: (p: string) => p }));
const reveal = vi.fn();
vi.mock("@tauri-apps/plugin-opener", () => ({ revealItemInDir: (p: string) => reveal(p) }));

import { DEFAULT_SPEC, planWords, ProAudio, sizeWords } from "../../ProAudio";
import type { ProAudioPlan, ProAudioResult } from "../../api";

const plan = (over: Partial<ProAudioPlan> = {}): ProAudioPlan => ({ seconds: 36, shots: 4, spec: DEFAULT_SPEC, lanes: { dialogue: "yes", foley: "no sound", sfx: "yes", ambience: "left out in your mix settings", music: "yes" }, files: 5, estimated_bytes: 62_000_000, skipped: [],
  positions: "Shots in scene order at their lengths; a trimmed cut may differ.", ...over });
const result = (over: Partial<ProAudioResult> = {}): ProAudioResult => ({ folder: "C:\\Films\\My Film\\exports\\audio\\My Film 1", relative: "exports/audio/My Film 1", files: 5, problems: [], ok: true, stems: [], lanes_without_sound: { foley: "No approved cue in this lane." },
  mixes: [{ file: "mixes/My Film FINAL.wav", lufs: -23, true_peak_db: -1.2, master_gain_db: 4.2, capped: false, note: "" }], cue_sheet: ["My Film cue sheet.csv"], otio: "My Film audio.otio", seconds: 36, not_checked: ["Whether any particular editor imports these files without a prompt."], ...over });

let planned: ProAudioPlan;
let made: ProAudioResult;
const backend = (_c: string, a: { action: string }) => Promise.resolve(a.action === "plan" ? planned : made);
const sent = (action: string) => invoke.mock.calls.filter(([, a]) => a.action === action).map(([, a]) => a.data);
afterEach(() => { cleanup(); invoke.mockReset(); reveal.mockReset(); });
const open = () => { render(<ProAudio dir="film" />); fireEvent.click(screen.getByRole("button", { name: "Open audio export…" })); };

describe("audio for a sound editor", () => {
  it("says sizes and a plan in plain words", () => {
    expect(sizeWords(62_000_000)).toBe("62 MB");
    expect(sizeWords(2_400_000_000)).toBe("2.4 GB");
    expect(sizeWords(10)).toBe("1 MB");
    const w = planWords(plan());
    expect(w).toContain("5 files, about 62 MB, each 36 s long.");
    expect(w).toContain("Foley (no sound)");
    expect(w).toContain("Ambience (left out in your mix settings)");
    expect(planWords(plan({ files: 1, lanes: { dialogue: "yes" } }))).toContain("1 file,");
  });

  it("does nothing until it is opened and then offers sensible defaults", () => {
    invoke.mockImplementation(backend);
    open();
    expect(invoke).not.toHaveBeenCalled();
    expect(screen.getByLabelText("Sample rate")).toHaveValue("48000");
    expect(screen.getByLabelText("Bit depth")).toHaveValue("24");
    expect(screen.getByLabelText(/Broadcast WAV/)).toBeChecked();
    expect(within(screen.getByRole("group", { name: "Stems" })).getAllByRole("checkbox")).toHaveLength(5);
  });

  it("asks what would be made with exactly the chosen settings and writes nothing", async () => {
    planned = plan();
    invoke.mockImplementation(backend);
    open();
    fireEvent.change(screen.getByLabelText("Sample rate"), { target: { value: "96000" } });
    fireEvent.change(screen.getByLabelText("Bit depth"), { target: { value: "16" } });
    fireEvent.change(screen.getByLabelText("Start timecode"), { target: { value: "01:00:00:00" } });
    fireEvent.change(screen.getByLabelText(/Loudness of the FINAL/), { target: { value: "-23" } });
    fireEvent.click(within(screen.getByRole("group", { name: "Stems" })).getByLabelText("Music"));
    fireEvent.click(screen.getByRole("button", { name: "What would be made" }));
    const box = await screen.findByLabelText("Plan");
    expect(within(box).getByText(/5 files, about 62 MB/)).toBeInTheDocument();
    expect(sent("plan")).toEqual([{ ...DEFAULT_SPEC, rate: 96000, bits: 16, start_tc: "01:00:00:00", target_lufs: -23, stems: ["dialogue", "foley", "sfx", "ambience"] }]);
    expect(sent("export")).toEqual([]);
  });

  it("exports with the chosen settings, reports each mix's loudness and gain, and shows the folder", async () => {
    made = result();
    invoke.mockImplementation(backend);
    open();
    fireEvent.click(screen.getByLabelText(/M&E \(no dialogue\)/));
    fireEvent.click(screen.getByRole("button", { name: "Export the audio" }));
    const box = await screen.findByLabelText("Export result");
    expect(sent("export")).toEqual([{ ...DEFAULT_SPEC, mixes: ["final"] }]);
    expect(within(box).getByRole("status")).toHaveTextContent("Done: 5 files in exports/audio/My Film 1. Every file was read back and checked.");
    expect(within(box).getByText(/My Film FINAL.wav: -23 LUFS, true peak -1.2 dBFS, master gain \+4.2 dB\./)).toBeInTheDocument();
    expect(within(box).getByText(/No stem for: Foley \(No approved cue in this lane\.\)/)).toBeInTheDocument();
    fireEvent.click(within(box).getByRole("button", { name: "Show the folder" }));
    expect(reveal).toHaveBeenCalledWith("C:\\Films\\My Film\\exports\\audio\\My Film 1");
  });

  it("says plainly what reading the files back found when something is wrong, and what was not checked", async () => {
    made = result({ ok: false, problems: ["01 DIALOGUE.wav is silent."], mixes: [{ file: "mixes/My Film FINAL.wav", lufs: -20, true_peak_db: -1, master_gain_db: 1, capped: true, note: "The loudness target could not be reached without peaks going over -1 dBFS, so the ceiling won (-20.0 LUFS)." }] });
    invoke.mockImplementation(backend);
    open();
    fireEvent.click(screen.getByRole("button", { name: "Export the audio" }));
    const box = await screen.findByLabelText("Export result");
    expect(within(box).getByRole("status")).toHaveTextContent("reading them back found problems");
    expect(within(box).getByText("01 DIALOGUE.wav is silent.")).toBeInTheDocument();
    expect(within(box).getByText(/the ceiling won/)).toBeInTheDocument();
    fireEvent.click(within(box).getByText("What was not checked"));
    expect(within(box).getByText(/editor imports these files/)).toBeInTheDocument();
  });

  it("will not ask for nothing: with no stem and no mix chosen both buttons are off", () => {
    invoke.mockImplementation(backend);
    open();
    for (const l of ["Dialogue", "Foley", "Effects", "Ambience", "Music"]) fireEvent.click(within(screen.getByRole("group", { name: "Stems" })).getByLabelText(l));
    fireEvent.click(screen.getByLabelText("FINAL"));
    fireEvent.click(screen.getByLabelText(/M&E \(no dialogue\)/));
    expect(screen.getByRole("button", { name: "What would be made" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Export the audio" })).toBeDisabled();
  });

  it("shows the engine's own words when it fails", async () => {
    invoke.mockImplementation(() => Promise.reject("There is no sound to export: no recording is attached and no cue is approved."));
    open();
    fireEvent.click(screen.getByRole("button", { name: "Export the audio" }));
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("no sound to export"));
  });
});
