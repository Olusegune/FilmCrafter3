// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";

const invoke = vi.fn();
vi.mock("@tauri-apps/api/core", () => ({ invoke: (cmd: string, args: unknown) => invoke(cmd, args), convertFileSrc: (p: string) => p }));
const openDialog = vi.fn();
vi.mock("@tauri-apps/plugin-dialog", () => ({ open: (o: unknown) => openDialog(o), save: vi.fn() }));
const askFn = vi.fn();
vi.mock("../../ask", () => ({ ask: (...a: unknown[]) => askFn(...a) }));

import { moveWords, placeWords, TimingAdr } from "../../TimingAdr";
import type { LineTiming } from "../../api";

const timing = (over: Partial<LineTiming> = {}): LineTiming => ({ shot: "S01-01", person: "Sarah", key: "sarah", fps: [24, 1], fps_label: "24", shot_seconds: 5, recording: { file: "voice/S01-01/sarah.wav", seconds: 3, source: "recording" },
  offset_frames: 0, offset_seconds: 0, starts: "00:00:00:00", ends: "00:00:03:00", shot_ends: "00:00:05:00", runs_past_shot: false, starts_before_shot: false,
  fit: { fits: true, tempo: 1, target: 4.9, recording: 3, class: "fits", words: "It fits: 3.00 s in 4.90 s." }, adr: { needs: false, reason: "" }, ...over });

let cur: LineTiming;
const backend = (_c: string, a: { action: string; data: Record<string, unknown> }) => {
  switch (a.action) {
    case "get": return Promise.resolve(cur);
    case "nudge": { const n = a.data.to_frame !== undefined ? Number(a.data.to_frame) : cur.offset_frames + Number(a.data.frames); cur = timing({ offset_frames: n, starts: `00:00:00:${String(Math.max(0, n)).padStart(2, "0")}` }); return Promise.resolve(cur); }
    case "align": return Promise.resolve({ ok: true, shift_seconds: -0.3, strength: 0.93, z: 6, reliable: true, frames: -7, move_to_frame: -7, move_by_frames: -7 - cur.offset_frames, guide: "the picture's own sound", words: "Move it 7 frames earlier to line up with the picture's own sound.", fps_label: "24" });
    case "fit_make": return Promise.resolve({ shot: "S01-01", person: "Sarah", take: "voice/_generated/S01-01-dfabc.wav", tempo: a.data.allow_extreme ? 1.5 : 1.05, seconds: 3, cached: false, attached: false, natural: !a.data.allow_extreme, next: "" });
    case "adr_mark": cur = timing({ adr: { needs: a.data.needs === true, reason: String(a.data.reason ?? "") } }); return Promise.resolve(cur);
    case "adr_take": return Promise.resolve({ take: "voice/_generated/S01-01-adabc.wav", attached: false });
    default: return Promise.resolve({});
  }
};
const sent = (action: string) => invoke.mock.calls.filter(([, a]) => a.action === action).map(([, a]) => a.data);
const open = async (onChanged = () => {}) => { render(<TimingAdr dir="film" shotId="S01-01" who="Sarah" onChanged={onChanged} />); fireEvent.click(screen.getByRole("button", { name: "Open timing and ADR…" })); await screen.findByLabelText("Where the line sits"); };
afterEach(() => { cleanup(); invoke.mockReset(); openDialog.mockReset(); askFn.mockReset(); });

describe("timing and ADR", () => {
  it("says a move and a place in plain words", () => {
    expect(moveWords(0)).toBe("in place");
    expect(moveWords(1)).toBe("1 frame later");
    expect(moveWords(-12)).toBe("12 frames earlier");
    expect(placeWords(timing())).toBe("Recording 3.00 s, in place: starts 00:00:00:00, ends 00:00:03:00 (the shot ends 00:00:05:00, 24 frames a second).");
  });

  it("asks the engine for nothing until it is opened", () => {
    invoke.mockImplementation(backend);
    render(<TimingAdr dir="film" shotId="S01-01" who="Sarah" onChanged={() => {}} />);
    expect(invoke).not.toHaveBeenCalled();
  });

  it("says plainly when the person has no recording, instead of showing an error", async () => {
    invoke.mockImplementation(() => Promise.reject("That person has no recording in that shot. Attach one first."));
    render(<TimingAdr dir="film" shotId="S01-01" who="Sarah" onChanged={() => {}} />);
    fireEvent.click(screen.getByRole("button", { name: "Open timing and ADR…" }));
    expect(await screen.findByText(/Sarah has no recording in S01-01 yet/)).toBeInTheDocument();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("moves the line by whole frames, tells the parent, and puts it back", async () => {
    cur = timing();
    invoke.mockImplementation(backend);
    const changed = vi.fn();
    await open(changed);
    expect(screen.getByLabelText("Where the line sits")).toHaveTextContent("starts 00:00:00:00");
    fireEvent.click(screen.getByRole("button", { name: "Move 10 frames later" }));
    await waitFor(() => expect(sent("nudge")).toEqual([{ shot: "S01-01", speaker: "Sarah", frames: 10 }]));
    fireEvent.click(screen.getByRole("button", { name: "Move 1 frame earlier" }));
    await waitFor(() => expect(sent("nudge")[1]).toEqual({ shot: "S01-01", speaker: "Sarah", frames: -1 }));
    expect(changed).toHaveBeenCalled();
    fireEvent.click(await screen.findByRole("button", { name: "Put it back" }));
    await waitFor(() => expect(sent("nudge")[2]).toEqual({ shot: "S01-01", speaker: "Sarah", to_frame: 0 }));
  });

  it("warns when the line runs past its shot", async () => {
    cur = timing({ runs_past_shot: true });
    invoke.mockImplementation(backend);
    await open();
    expect(screen.getByRole("alert")).toHaveTextContent("runs past the end of the shot");
  });

  it("suggests a line-up without moving anything, says how confident it is, and applies it only when asked", async () => {
    cur = timing();
    invoke.mockImplementation(backend);
    await open();
    fireEvent.click(screen.getByRole("button", { name: "Line up with the picture's sound" }));
    const box = await screen.findByLabelText("Line-up suggestion");
    expect(within(box).getByText(/^Move it 7 frames earlier to line up/)).toBeInTheDocument();
    expect(within(box).getByText(/not words\. Match 93%/)).toBeInTheDocument();
    expect(sent("nudge")).toEqual([]);
    fireEvent.click(within(box).getByRole("button", { name: "Move it 7 frames earlier" }));
    await waitFor(() => expect(sent("nudge")).toEqual([{ shot: "S01-01", speaker: "Sarah", to_frame: -7 }]));
  });

  it("offers a fitted take only when a natural or audible change would fit, and makes it as a take", async () => {
    cur = timing({ fit: { fits: false, tempo: 1.05, target: 2.9, recording: 3, class: "natural", words: "Speeding it up 5.0% would fit it, which should sound natural." } });
    invoke.mockImplementation(backend);
    const changed = vi.fn();
    await open(changed);
    expect(screen.getByLabelText("Fit")).toHaveTextContent("5.0%");
    fireEvent.click(screen.getByRole("button", { name: "Make a fitted take" }));
    await waitFor(() => expect(sent("fit_make")).toEqual([{ shot: "S01-01", speaker: "Sarah" }]));
    expect(await screen.findByRole("status")).toHaveTextContent("A fitted take was added to the takes");
    expect(changed).toHaveBeenCalled();
  });

  it("refuses a change that is too big unless the person insists after a warning", async () => {
    cur = timing({ fit: { fits: false, tempo: 1.9, target: 1.5, recording: 3, class: "too_much", words: "It would need 90% faster, too much to sound right." } });
    invoke.mockImplementation(backend);
    askFn.mockResolvedValueOnce(false).mockResolvedValueOnce(true);
    await open();
    expect(screen.queryByRole("button", { name: "Make a fitted take" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Make one anyway…" }));
    await waitFor(() => expect(askFn).toHaveBeenCalledTimes(1));
    expect(sent("fit_make")).toEqual([]);
    fireEvent.click(screen.getByRole("button", { name: "Make one anyway…" }));
    await waitFor(() => expect(sent("fit_make")).toEqual([{ shot: "S01-01", speaker: "Sarah", allow_extreme: true }]));
    expect(await screen.findByRole("status")).toHaveTextContent("a big change");
  });

  it("shows no fit button when the line already fits", async () => {
    cur = timing();
    invoke.mockImplementation(backend);
    await open();
    expect(screen.queryByRole("button", { name: "Make a fitted take" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Make one anyway…" })).toBeNull();
  });

  it("marks a line for ADR with a reason, and adds an ADR recording as a new take", async () => {
    cur = timing();
    invoke.mockImplementation(backend);
    openDialog.mockResolvedValue("C:\\booth\\take.wav");
    const changed = vi.fn();
    await open(changed);
    fireEvent.change(screen.getByLabelText("Why it needs ADR"), { target: { value: "a dog barks" } });
    fireEvent.click(screen.getByLabelText("This line needs ADR"));
    await waitFor(() => expect(sent("adr_mark")).toEqual([{ shot: "S01-01", speaker: "Sarah", needs: true, reason: "a dog barks" }]));
    fireEvent.click(screen.getByRole("button", { name: "Add an ADR recording…" }));
    await waitFor(() => expect(sent("adr_take")).toEqual([{ shot: "S01-01", speaker: "Sarah", recording: "C:\\booth\\take.wav" }]));
    expect(await screen.findByRole("status")).toHaveTextContent("Your original is kept");
    expect(changed).toHaveBeenCalled();
  });

  it("does nothing when the file chooser is cancelled, and shows the engine's own words on failure", async () => {
    cur = timing();
    openDialog.mockResolvedValue(null);
    invoke.mockImplementation((c: string, a: { action: string; data: Record<string, unknown> }) => (a.action === "align" ? Promise.reject("This shot has no picture sound to line up with. Choose a guide recording instead.") : backend(c, a)));
    await open();
    fireEvent.click(screen.getByRole("button", { name: "Add an ADR recording…" }));
    await waitFor(() => expect(openDialog).toHaveBeenCalled());
    expect(sent("adr_take")).toEqual([]);
    fireEvent.click(screen.getByRole("button", { name: "Line up with the picture's sound" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("no picture sound");
  });
});
