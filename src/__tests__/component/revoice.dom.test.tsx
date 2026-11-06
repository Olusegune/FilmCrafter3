// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";

const invoke = vi.fn();
vi.mock("@tauri-apps/api/core", () => ({ invoke: (cmd: string, args: unknown) => invoke(cmd, args), convertFileSrc: (p: string) => p }));
const open = vi.fn();
vi.mock("@tauri-apps/plugin-dialog", () => ({ open: (o: unknown) => open(o), save: vi.fn() }));
const askFn = vi.fn();
vi.mock("../../ask", () => ({ ask: (...a: unknown[]) => askFn(...a) }));

import { installWords, referenceWords, Revoice } from "../../Revoice";
import type { CastTake, RevoicePerson, RevoiceStatus } from "../../api";

const model = { id: "chatterbox-vc", name: "Chatterbox voice conversion", licence: "MIT", by: "Resemble AI", packages: [], size_note: "Several gigabytes in total.", needs: "About 8 GB of memory.", status: "experimental" };
const person = (over: Partial<RevoicePerson> = {}): RevoicePerson => ({ key: "chloe", person: "Chloe", file: "voice/_reference/chloe/ab.wav", seconds: 8, source: "permission", holder: "Ada", scope: "this film only", consent: { given: true, basis: "x" }, revoked: false, at: 1, ...over });
const status = (installed: boolean, people: RevoicePerson[] = []): RevoiceStatus => ({ runtime: { model, installed, since: installed ? 1 : null, versions: null, device: "cpu", folder: "f", how: "" }, people, conversions: 0 });
const spokenTake: CastTake = { file: "voice/_generated/S01-01-abc.mp3", text: "I know.", model: "eleven_v4", voice_name: "V", at: 1, current: false, kind: "speech" };

let state: RevoiceStatus;
const backend = (cmd: string, a: { action: string; data: Record<string, unknown> }) => {
  if (cmd === "film_revoice") {
    switch (a.action) {
      case "status": return Promise.resolve(state);
      case "install": state = status(true, state.people); return Promise.resolve(state);
      case "reference": state = status(true, [person({ holder: String(a.data.holder ?? ""), scope: String(a.data.scope ?? ""), source: a.data.consent ? "permission" : "film_take" })]); return Promise.resolve({});
      case "convert": return Promise.resolve({ shot: "S01-01", person: "Chloe", take: "voice/_generated/S01-01-rvfeed.wav", performance: "voice/_performances/aa.wav", seconds: 4, cached: false, attached: false, next: "" });
      default: return Promise.resolve({});
    }
  }
  return Promise.resolve({});
};
const sent = (cmd: string, action: string) => invoke.mock.calls.filter(([c, a]) => c === cmd && a.action === action).map(([, a]) => a.data);
const show = (takes: CastTake[] = [], onChanged = () => {}) => render(<Revoice dir="film" shotId="S01-01" who="Chloe" takes={takes} onChanged={onChanged} />);
afterEach(() => { cleanup(); invoke.mockReset(); open.mockReset(); askFn.mockReset(); });

describe("perform it yourself", () => {
  it("says what it is before anything is downloaded: size, licence, hardware and that it is experimental", () => {
    const t = installWords(model);
    expect(t).toContain("MIT");
    expect(t).toContain("Several gigabytes");
    expect(t).toContain("About 8 GB");
    expect(t).toContain("experimental");
    expect(t).toContain("Nothing is uploaded");
  });

  it("describes a reference voice in plain words, including a revoked one", () => {
    expect(referenceWords(person())).toBe("Ada's voice, for: this film only.");
    expect(referenceWords(person({ source: "film_take", holder: "", scope: "" }))).toContain("no real person's voice is copied");
    expect(referenceWords(person({ revoked: true }))).toContain("taken back");
  });

  it("downloads nothing until the person agrees, then installs with an explicit confirmation", async () => {
    state = status(false);
    invoke.mockImplementation(backend);
    askFn.mockResolvedValueOnce(false).mockResolvedValueOnce(true);
    show();
    const btn = await screen.findByRole("button", { name: "Install…" });
    fireEvent.click(btn);
    await waitFor(() => expect(askFn).toHaveBeenCalledTimes(1));
    expect(sent("film_revoice", "install")).toEqual([]);
    expect(screen.queryByRole("button", { name: /Record your performance/ })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Install…" }));
    await waitFor(() => expect(sent("film_revoice", "install")).toEqual([{ confirmed: true }]));
    expect(await screen.findByRole("button", { name: /Record your performance/ })).toBeDisabled();           // installed, but no reference voice yet
  });

  it("needs the owner's agreement, whose voice it is and what for, before a real voice is used", async () => {
    state = status(true);
    invoke.mockImplementation(backend);
    open.mockResolvedValue("C:\\voices\\ada.wav");
    show();
    fireEvent.click(await screen.findByRole("button", { name: "Choose…" }));
    const choose = screen.getByRole("button", { name: "Choose the recording…" });
    expect(choose).toBeDisabled();
    fireEvent.change(screen.getByLabelText(/Whose voice/), { target: { value: "Ada" } });
    fireEvent.change(screen.getByLabelText(/What it may be used for/), { target: { value: "this film only" } });
    expect(choose).toBeDisabled();
    fireEvent.click(screen.getByLabelText(/owner of this voice agrees/));
    expect(choose).toBeEnabled();
    fireEvent.click(choose);
    await waitFor(() => expect(sent("film_revoice", "reference")).toEqual([{ person: "Chloe", file: "C:\\voices\\ada.wav", consent: true, holder: "Ada", scope: "this film only" }]));
  });

  it("uses a take in the character's own cast voice with no permission step", async () => {
    state = status(true);
    invoke.mockImplementation(backend);
    show([spokenTake]);
    fireEvent.click(await screen.findByRole("button", { name: "Choose…" }));
    fireEvent.click(screen.getByRole("button", { name: "I know." }));
    await waitFor(() => expect(sent("film_revoice", "reference")[0]).toMatchObject({ file: spokenTake.file, consent: false }));
  });

  it("converts a chosen performance, lets you hear it next to the original, and only then attaches it", async () => {
    state = status(true, [person()]);
    invoke.mockImplementation(backend);
    open.mockResolvedValue("C:\\me\\line.wav");
    const changed = vi.fn();
    show([], changed);
    const go = await screen.findByRole("button", { name: /Change it into Chloe's voice/ });
    expect(go).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: /Choose a recording/ }));
    await screen.findByText(/Ready: line.wav/);
    fireEvent.click(go);
    await waitFor(() => expect(sent("film_revoice", "convert")).toEqual([{ shot: "S01-01", speaker: "Chloe", recording: "C:\\me\\line.wav" }]));
    const cmp = await screen.findByLabelText("Compare");
    expect(within(cmp).getByLabelText("Your performance")).toHaveAttribute("src", "film/voice/_performances/aa.wav");
    expect(within(cmp).getByLabelText("In Chloe's voice")).toHaveAttribute("src", "film/voice/_generated/S01-01-rvfeed.wav");
    expect(sent("film_cast_voice", "use_take")).toEqual([]);                                  // converting attaches nothing
    fireEvent.click(within(cmp).getByRole("button", { name: "Use this take for S01-01" }));
    await waitFor(() => expect(sent("film_cast_voice", "use_take")).toEqual([{ shot: "S01-01", speaker: "Chloe", file: "voice/_generated/S01-01-rvfeed.wav" }]));
    expect(await within(cmp).findByText("in the film")).toBeInTheDocument();
    expect(changed).toHaveBeenCalled();
    expect(within(cmp).getByText(/synthetic audio/)).toBeInTheDocument();
  });

  it("will not convert with a reference whose permission was taken back, and offers to take it back only with a yes", async () => {
    state = status(true, [person({ revoked: true })]);
    invoke.mockImplementation(backend);
    show();
    expect(await screen.findByText(/taken back/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Record your performance/ })).toBeDisabled();
    expect(screen.getByRole("button", { name: /Choose a recording/ })).toBeDisabled();
  });

  it("asks before permission is taken back, and does nothing if the answer is no", async () => {
    state = status(true, [person()]);
    invoke.mockImplementation(backend);
    askFn.mockResolvedValue(false);
    show();
    fireEvent.click(await screen.findByRole("button", { name: "Take permission back" }));
    await waitFor(() => expect(askFn).toHaveBeenCalled());
    expect(sent("film_revoice", "revoke")).toEqual([]);
  });

  it("shows the engine's own words when something fails", async () => {
    state = status(true, [person()]);
    invoke.mockImplementation((cmd: string, a: { action: string }) => (a.action === "convert" ? Promise.reject("The voice could not be changed: nope. Your performance is kept.") : backend(cmd, a as never)));
    open.mockResolvedValue("C:\\me\\line.wav");
    show();
    fireEvent.click(await screen.findByRole("button", { name: /Choose a recording/ }));
    await screen.findByText(/Ready:/);
    fireEvent.click(screen.getByRole("button", { name: /Change it into/ }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Your performance is kept");
  });
});
