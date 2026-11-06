// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";

const invoke = vi.fn();
vi.mock("@tauri-apps/api/core", () => ({ invoke: (cmd: string, args: unknown) => invoke(cmd, args), convertFileSrc: (p: string) => p }));
const openDialog = vi.fn();
vi.mock("@tauri-apps/plugin-dialog", () => ({ open: (o: unknown) => openDialog(o), save: vi.fn() }));

import { allFindings, AudioCheck, checkedWords } from "../../AudioCheck";
import type { AudioQaReport, QaFinding } from "../../api";

const f = (severity: QaFinding["severity"], code: string, where: string, what: string, extra: Partial<QaFinding> = {}): QaFinding => ({ severity, code, where, what, measured: 1, limit: 0, ...extra });
const report = (over: Partial<AudioQaReport> = {}): AudioQaReport => ({ summary: { fix: 1, look: 1, note: 1, files: 3 }, target_lufs: null, notes: [], says: "1 to fix and 1 worth a listen. These are measurements, not a quality score.",
  not_measured: ["How clear the speech is.", "How good anything sounds."], consistency: [f("note", "level_outlier", "Sarah in S01-04", "This line averages -40 dBFS.", { confidence: "low" })],
  items: [{ where: "Sarah in S01-01", role: "voice", ok: true, findings: [f("look", "noise", "Sarah in S01-01", "Steady background noise under the voice.")] },
    { where: "rain (ambience)", role: "ambience", ok: true, findings: [f("fix", "clipping", "rain (ambience)", "The sound is flattened at the top 30 times.")] },
    { where: "broken.wav", role: "voice", ok: false, why: "FilmCrafter cannot read any sound in that file.", findings: [] }], ...over });

let rep: AudioQaReport;
const backend = () => Promise.resolve(rep);
const sent = () => invoke.mock.calls.filter(([c]) => c === "film_audioqa").map(([, a]) => ({ action: a.action, data: a.data }));
afterEach(() => { cleanup(); invoke.mockReset(); openDialog.mockReset(); });

describe("the sound check", () => {
  it("orders findings with what to fix first and counts the files", () => {
    const all = allFindings(report());
    expect(all.map((x) => x.severity)).toEqual(["fix", "look", "note"]);
    expect(checkedWords(report())).toBe("3 sound files checked.");
    expect(checkedWords(report({ summary: { fix: 0, look: 0, note: 0, files: 1 } }))).toBe("1 sound file checked.");
  });

  it("measures nothing until it is asked", () => {
    invoke.mockImplementation(backend);
    render(<AudioCheck dir="film" />);
    expect(invoke).not.toHaveBeenCalled();
    expect(screen.getByText(/reads files and changes nothing/)).toBeInTheDocument();
  });

  it("runs the check and groups what it found by how serious it is, saying where each one is", async () => {
    rep = report();
    invoke.mockImplementation(backend);
    render(<AudioCheck dir="film" />);
    fireEvent.click(screen.getByRole("button", { name: "Check the sound" }));
    const res = await screen.findByLabelText("Sound check result");
    expect(sent()).toEqual([{ action: "film", data: {} }]);
    expect(within(res).getByRole("status")).toHaveTextContent("not a quality score");
    const heads = within(res).getAllByRole("heading", { level: 4 }).map((h) => h.textContent);
    expect(heads[0]).toContain("To fix");
    expect(heads[1]).toContain("Worth a listen");
    expect(heads[2]).toContain("For information");
    expect(within(res).getByText("rain (ambience)")).toBeInTheDocument();
    expect(within(res).getByText("The sound is flattened at the top 30 times.")).toBeInTheDocument();
    expect(within(res).getByText(/low confidence/)).toBeInTheDocument();
  });

  it("says what it could not read, and what it never measures", async () => {
    rep = report();
    invoke.mockImplementation(backend);
    render(<AudioCheck dir="film" />);
    fireEvent.click(screen.getByRole("button", { name: "Check the sound" }));
    expect(await screen.findByText(/broken.wav: FilmCrafter cannot read any sound/)).toBeInTheDocument();
    fireEvent.click(screen.getByText("What this does not measure"));
    expect(screen.getByText("How good anything sounds.")).toBeInTheDocument();
    expect(screen.getByText(/not an industry standard/)).toBeInTheDocument();
  });

  it("says plainly when nothing needs a listen", async () => {
    rep = report({ summary: { fix: 0, look: 0, note: 0, files: 2 }, items: [], consistency: [], says: "Nothing here needs a second listen. These are measurements, not a quality score." });
    invoke.mockImplementation(backend);
    render(<AudioCheck dir="film" />);
    fireEvent.click(screen.getByRole("button", { name: "Check the sound" }));
    expect(await screen.findByRole("status")).toHaveTextContent("Nothing here needs a second listen.");
    expect(screen.queryByRole("heading", { level: 4 })).toBeNull();
  });

  it("includes a finished film only when one is chosen, and can leave it out again", async () => {
    rep = report();
    invoke.mockImplementation(backend);
    openDialog.mockResolvedValue("C:\\Films\\cut.mp4");
    render(<AudioCheck dir="film" />);
    fireEvent.click(screen.getByRole("button", { name: "Also check a finished film…" }));
    await waitFor(() => expect(sent()).toEqual([{ action: "film", data: { file: "C:\\Films\\cut.mp4" } }]));
    expect(await screen.findByText(/Including cut.mp4/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Leave it out" }));
    fireEvent.click(screen.getByRole("button", { name: "Check the sound" }));
    await waitFor(() => expect(sent()[1]).toEqual({ action: "film", data: {} }));
  });

  it("does nothing when the file chooser is cancelled, and shows the engine's own words on failure", async () => {
    openDialog.mockResolvedValue(null);
    invoke.mockImplementation(() => Promise.reject("That file is not inside this film."));
    render(<AudioCheck dir="film" />);
    fireEvent.click(screen.getByRole("button", { name: "Also check a finished film…" }));
    await waitFor(() => expect(openDialog).toHaveBeenCalled());
    expect(invoke).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Check the sound" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("not inside this film");
  });
});
