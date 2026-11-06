// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";

const invoke = vi.fn();
vi.mock("@tauri-apps/api/core", () => ({ invoke: (cmd: string, args: unknown) => invoke(cmd, args), convertFileSrc: (p: string) => p }));
const askFn = vi.fn();
vi.mock("../../ask", () => ({ ask: (...a: unknown[]) => askFn(...a) }));

import { auditionWords, lockWords, VoiceIdentity } from "../../VoiceIdentity";
import type { BibleCharacter, CastLibraryEntry, VoiceIdPerson } from "../../api";

const char = (over: Partial<BibleCharacter> = {}): BibleCharacter => ({ id: "c1", name: "Chloe", role: "", age: "", physical: "", relationships: "", arc: "", voice: "", notes: "", wardrobe: [], states: [], media: [], scenes: [], source: "",
  voice_profile: { description: "", age_range: "", accent: "yorkshire", timbre: "", pace: "", emotional_range: "", delivery: "", notes: "", approved: false }, ...over });
const voice = { voice_id: "AbCdEfGh1234", voice_name: "Warm", model: "eleven_v4", made: "library" };
const person = (over: Partial<VoiceIdPerson> = {}): VoiceIdPerson => ({ id: "c1", name: "Chloe", key: "chloe", role: "", approved: false, voice, lock: null,
  consistency: { state: "unlocked", problems: [], words: "Not locked." }, accent: { status: "untested", words: "Not listened to and rated yet." }, natural: null, ratings: 0, history: [], ...over });
const row = (id: string, name: string, over = {}) => ({ voice: { voice_id: id, name, category: "premade", description: "", labels: {}, preview_url: "" }, score: 4, why: ["yorkshire accent"], current: false,
  available: { where: "ElevenLabs (online; needs your key)", local: false }, audition_credits: 70, audition_basis: "x", licence: "One of ElevenLabs' own voices; use is covered by your plan's terms.",
  rated: { count: 0, natural: null, accent: { status: "untested", words: "" } }, ...over });
const entry = (over: Partial<CastLibraryEntry> = {}): CastLibraryEntry => ({ id: "e1", name: "Lila", voice: { ...voice, made: "design" }, profile: {}, film: "Old Film", saved: 1, note: "", rights: "Designed in FilmCrafter.", ...over });

let me: VoiceIdPerson;
const backend = (cmd: string, a: { action: string; data: Record<string, unknown> }) => {
  if (cmd === "film_voiceid") {
    switch (a.action) {
      case "overview": return Promise.resolve({ people: [me], flagged: 0 });
      case "compare": return Promise.resolve({ person: "Chloe", rows: [row("BBBBBBBBBBBB", "Bright"), row("AbCdEfGh1234", "Warm", { current: true })], searched: 2, model: "eleven_v4", note: "Fit comes from labels." });
      case "cast_library": return Promise.resolve({ entries: [entry(), entry({ id: "e2", name: "Mama", voice: { ...voice, made: "clone" }, rights: "This voice was cloned from a recording." })] });
      default: return Promise.resolve({});
    }
  }
  if (cmd === "film_cast_voice" && a.action === "library") return Promise.resolve({ voices: [{ voice_id: "BBBBBBBBBBBB", name: "Bright", category: "premade", description: "", labels: {}, preview_url: "" }], next: null });
  return Promise.resolve({});
};
const sent = (cmd: string, action: string) => invoke.mock.calls.filter(([c, a]) => c === cmd && a.action === action).map(([, a]) => a.data);
const show = (c = char(), run = vi.fn(async () => null)) => render(<VoiceIdentity dir="film" c={c} hasKey run={run} onChanged={() => {}} />);
afterEach(() => { cleanup(); invoke.mockReset(); askFn.mockReset(); });

describe("voice identity", () => {
  it("says the lock state in plain words", () => {
    expect(lockWords(person({ voice: null }))).toContain("nothing to lock");
    expect(lockWords(person({ approved: true }))).toContain("Approved, but not locked");
    expect(lockWords(person({ consistency: { state: "ok", problems: [], words: "Same voice." } }))).toBe("Locked. Same voice.");
    expect(lockWords(person({ consistency: { state: "changed", problems: ["x"], words: "The voice changed from Warm to Bright." } }))).toBe("The voice changed from Warm to Bright.");
    expect(auditionWords(1234)).toContain("1,234 credits");
    expect(auditionWords(5)).toContain("an estimate");
  });

  it("saves the identity fields with the Bible profile call, and only when something changed", async () => {
    me = person();
    invoke.mockImplementation(backend);
    const run = vi.fn(async (f: () => Promise<unknown>) => { await f(); return null; });
    show(char(), run as never);
    const save = await screen.findByRole("button", { name: "Save identity" });
    expect(save).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Vocal habits"), { target: { value: "hums" } });
    expect(save).toBeEnabled();
    fireEvent.click(save);
    await waitFor(() => expect(sent("film_bible", "set_voice_profile")[0]).toMatchObject({ id: "c1", mannerisms: "hums" }));
  });

  it("locks the voice they have, and warns plainly when it has changed", async () => {
    me = person();
    invoke.mockImplementation(backend);
    show();
    fireEvent.click(await screen.findByRole("button", { name: "Lock this voice" }));
    await waitFor(() => expect(sent("film_voiceid", "lock")).toEqual([{ person: "Chloe" }]));
    cleanup();
    me = person({ lock: { voice_id: "ZyXwVu987654", voice_name: "Bright", model: "eleven_v4", made: "library", reference_sha256: null, at: 1 }, consistency: { state: "changed", problems: ["x"], words: "The voice changed from Bright to Warm." } });
    show();
    expect(await screen.findByRole("alert")).toHaveTextContent("The voice changed from Bright to Warm.");
  });

  it("only unlocks after a yes", async () => {
    me = person({ lock: { voice_id: "AbCdEfGh1234", voice_name: "Warm", model: "eleven_v4", made: "library", reference_sha256: null, at: 1 }, consistency: { state: "ok", problems: [], words: "Same." } });
    invoke.mockImplementation(backend);
    askFn.mockResolvedValueOnce(false).mockResolvedValueOnce(true);
    show();
    fireEvent.click(await screen.findByRole("button", { name: "Unlock" }));
    await waitFor(() => expect(askFn).toHaveBeenCalledTimes(1));
    expect(sent("film_voiceid", "unlock")).toEqual([]);
    fireEvent.click(screen.getByRole("button", { name: "Unlock" }));
    await waitFor(() => expect(sent("film_voiceid", "unlock")).toEqual([{ person: "Chloe" }]));
  });

  it("saves a rating of the voice they have, never without a score, and says it is the listener's judgement", async () => {
    me = person();
    invoke.mockImplementation(backend);
    show();
    const save = await screen.findByRole("button", { name: "Save my rating" });
    expect(save).toBeDisabled();
    fireEvent.change(screen.getByLabelText("How convincing"), { target: { value: "4" } });
    fireEvent.change(screen.getByLabelText("Accent you listened for"), { target: { value: "Yorkshire" } });
    fireEvent.click(save);
    await waitFor(() => expect(sent("film_voiceid", "rate")).toEqual([{ person: "Chloe", voice_id: "AbCdEfGh1234", accent: "Yorkshire", accent_score: 4, natural_score: null, note: "" }]));
    expect(screen.getByText(/cannot tell whether an accent is authentic/)).toBeInTheDocument();
  });

  it("compares voices from the library with cost, licence and where they run, and does not pick one for you", async () => {
    me = person();
    invoke.mockImplementation(backend);
    show();
    fireEvent.click(await screen.findByRole("button", { name: "Compare voices from my library" }));
    const list = await screen.findByRole("list");
    const bright = within(list).getByText("Bright").closest("li")!;
    expect(within(bright).getByText(/about 70 credits/)).toBeInTheDocument();
    expect(within(bright).getByText(/own voices/)).toBeInTheDocument();
    expect(within(bright).getByText(/ElevenLabs \(online/)).toBeInTheDocument();
    expect(sent("film_cast_voice", "library")).toEqual([{ query: "yorkshire" }]);
    expect(sent("film_cast_voice", "set")).toEqual([]);
    expect(within(list).getByText("their voice now")).toBeInTheDocument();
    fireEvent.click(within(bright).getByRole("button", { name: "Give Chloe this voice" }));
    await waitFor(() => expect(sent("film_cast_voice", "set")[0]).toMatchObject({ person: "Chloe", voice: { voice_id: "BBBBBBBBBBBB" } }));
  });

  it("asks before replacing an approved voice, and does nothing on no", async () => {
    me = person({ approved: true });
    invoke.mockImplementation(backend);
    askFn.mockResolvedValue(false);
    show(char({ voice_profile: { ...char().voice_profile!, approved: true } }));
    fireEvent.click(await screen.findByRole("button", { name: "Compare voices from my library" }));
    fireEvent.click(await screen.findByRole("button", { name: "Give Chloe this voice" }));
    await waitFor(() => expect(askFn).toHaveBeenCalled());
    expect(sent("film_cast_voice", "set")).toEqual([]);
  });

  it("keeps a character for other films and uses one, confirming the rights of a cloned voice", async () => {
    me = person();
    invoke.mockImplementation(backend);
    askFn.mockResolvedValue(true);
    show();
    fireEvent.click(await screen.findByRole("button", { name: "Keep Chloe for other films" }));
    await waitFor(() => expect(sent("film_voiceid", "library_save")).toEqual([{ person: "Chloe" }]));
    const list = await screen.findByRole("list");
    fireEvent.click(within(within(list).getByText("Mama").closest("li")!).getByRole("button", { name: "Use for Chloe" }));
    await waitFor(() => expect(sent("film_voiceid", "library_use")).toEqual([{ person: "Chloe", id: "e2", replace_approved: false, rights_confirmed: true }]));
    expect(askFn.mock.calls[0][0]).toContain("cloned from a recording");
    fireEvent.click(within(within(list).getByText("Lila").closest("li")!).getByRole("button", { name: "Use for Chloe" }));
    await waitFor(() => expect(sent("film_voiceid", "library_use")[1]).toMatchObject({ id: "e1", rights_confirmed: false }));
  });

  it("shows the engine's own words when something fails", async () => {
    me = person();
    invoke.mockImplementation((cmd: string, a: { action: string }) => (a.action === "lock" ? Promise.reject("This character has no voice to lock yet.") : backend(cmd, a as never)));
    show();
    fireEvent.click(await screen.findByRole("button", { name: "Lock this voice" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("no voice to lock");
  });
});
