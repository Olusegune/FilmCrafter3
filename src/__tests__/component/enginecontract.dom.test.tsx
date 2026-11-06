// @vitest-environment jsdom
// The screens fed the REAL engine's answers (src/__tests__/fixtures/engine/*.json, made by scripts/make_engine_fixtures.py), not answers written by hand. A field the engine does not send, or sends
// under another name, shows up here as "undefined" or "NaN" on the screen or as a crash.
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";

import voiceidOverview from "../fixtures/engine/voiceid_overview.json";
import voiceidCompare from "../fixtures/engine/voiceid_compare.json";
import voiceidLibrary from "../fixtures/engine/voiceid_cast_library.json";
import planGet from "../fixtures/engine/performplan_get.json";
import planUntagged from "../fixtures/engine/performplan_get_untagged_model.json";
import sdScene from "../fixtures/engine/sounddesign_scene.json";
import sdSuggest from "../fixtures/engine/sounddesign_suggest.json";
import sdToCues from "../fixtures/engine/sounddesign_to_cues.json";
import sdCandidates from "../fixtures/engine/sounddesign_candidates.json";
import muGet from "../fixtures/engine/music_get.json";
import muSuggest from "../fixtures/engine/music_suggest.json";
import muPrompt from "../fixtures/engine/music_prompt.json";
import muToCues from "../fixtures/engine/music_to_cues.json";
import qaFilm from "../fixtures/engine/audioqa_film.json";
import adGet from "../fixtures/engine/adrsync_get.json";
import adAlign from "../fixtures/engine/adrsync_align.json";
import adFitPlan from "../fixtures/engine/adrsync_fit_plan.json";
import adFitMake from "../fixtures/engine/adrsync_fit_make.json";
import paPlan from "../fixtures/engine/proaudio_plan.json";
import paExport from "../fixtures/engine/proaudio_export.json";
import revStatus from "../fixtures/engine/revoice_status.json";
import castTakes from "../fixtures/engine/cast_takes.json";

const invoke = vi.fn();
vi.mock("@tauri-apps/api/core", () => ({ invoke: (cmd: string, args: unknown) => invoke(cmd, args), convertFileSrc: (p: string) => p }));
const openDialog = vi.fn();
vi.mock("@tauri-apps/plugin-dialog", () => ({ open: (o: unknown) => openDialog(o), save: vi.fn() }));
vi.mock("@tauri-apps/plugin-opener", () => ({ revealItemInDir: () => Promise.resolve() }));
vi.mock("../../ask", () => ({ ask: () => Promise.resolve(true) }));

import { VoiceIdentity } from "../../VoiceIdentity";
import { PerformancePlanner } from "../../PerformancePlanner";
import { SoundDesign } from "../../SoundDesign";
import { MusicDirector } from "../../MusicDirector";
import { AudioCheck } from "../../AudioCheck";
import { TimingAdr } from "../../TimingAdr";
import { ProAudio } from "../../ProAudio";
import { Revoice } from "../../Revoice";
import type { AudioAsset, BibleCharacter, CastTake } from "../../api";

type Json = Record<string, unknown>;
const answers = (table: Record<string, unknown>) => (cmd: string, a: { action: string }) => {
  const k = `${cmd}:${a.action}`;
  if (!(k in table)) return Promise.reject(`No answer for ${k} in the contract test.`);
  return Promise.resolve(table[k]);
};
/** The text of everything on screen must not hold a placeholder a missing field would leave behind. */
const clean = (el: HTMLElement) => {
  const t = el.textContent ?? "";
  for (const bad of ["undefined", "NaN", "[object", "null"]) expect(t, `the screen shows "${bad}"`).not.toContain(bad);
};
afterEach(() => { cleanup(); invoke.mockReset(); openDialog.mockReset(); });

const overview = voiceidOverview as unknown as { people: { id: string; name: string }[] };
const mama = overview.people.find((p) => p.name === "Mama")!;
const char = { id: mama.id, name: "Mama", role: "", age: "", physical: "", relationships: "", arc: "", voice: "", notes: "", wardrobe: [], states: [], media: [], scenes: [], source: "",
  voice_profile: { description: "", age_range: "middle aged", accent: "nigerian", timbre: "", pace: "", emotional_range: "", delivery: "", notes: "", approved: true, language: "English" } } as unknown as BibleCharacter;

describe("the screens with the real engine's answers", () => {
  it("voice identity: the lock, the comparison and the cast library", async () => {
    invoke.mockImplementation(answers({ "film_voiceid:overview": voiceidOverview, "film_voiceid:compare": voiceidCompare, "film_voiceid:cast_library": voiceidLibrary,
      "film_cast_voice:library": { voices: (voiceidCompare as { rows: { voice: unknown }[] }).rows.map((r) => r.voice), next: null } }));
    const { container } = render(<VoiceIdentity dir="film" c={char} hasKey run={async () => null} onChanged={() => {}} />);
    expect(await screen.findByText(/Locked\. Same voice, model and reference/)).toBeInTheDocument();
    expect(screen.getByText(/You rated the accent 4\.0 of 5/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Compare voices from my library" }));
    const list = await screen.findByRole("list");
    expect(within(list).getByText("Joy")).toBeInTheDocument();
    expect(within(list).getAllByText(/ElevenLabs \(online/).length).toBeGreaterThan(0);
    expect(within(list).getByText(/cloned or community voice/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Show my cast library" }));
    expect(await screen.findByText(/Warm · from/)).toBeInTheDocument();
    clean(container);
  });

  it("the performance plan, for a model that takes tags and for one that does not", async () => {
    invoke.mockImplementation(answers({ "film_performplan:get": planGet }));
    const { container, unmount } = render(<PerformancePlanner dir="film" shotId="S01-02" who="Mama" onChanged={() => {}} />);
    fireEvent.click(screen.getByRole("button", { name: "Plan the performance…" }));
    const box = await screen.findByLabelText("What the model will read");
    expect(within(box).getByText("[sighs] I did not THINK... [gasps] you [sad] would come back.")).toBeInTheDocument();
    expect(within(box).getByText(/not checked/)).toBeInTheDocument();
    expect(screen.getByLabelText("Sound 1")).toBeInTheDocument();
    clean(container);
    unmount();
    invoke.mockImplementation(answers({ "film_performplan:get": planUntagged }));
    const second = render(<PerformancePlanner dir="film" shotId="S01-02" who="Mama" onChanged={() => {}} />);
    fireEvent.click(screen.getByRole("button", { name: "Plan the performance…" }));
    const nc = await screen.findByLabelText("Not carried");
    expect(within(nc).getAllByRole("listitem").length).toBeGreaterThan(0);
    clean(second.container);
  });

  it("sound design: the scene, the suggestions, putting it into the film and finding a sound", async () => {
    const assets = [{ id: (sdScene as unknown as { events: { asset_id: string }[] }).events[0].asset_id, name: "hit", kind: "sfx" }] as unknown as AudioAsset[];
    invoke.mockImplementation(answers({ "film_sounddesign:scene": sdScene, "film_sounddesign:suggest": sdSuggest, "film_sounddesign:to_cues": sdToCues, "film_sounddesign:candidates": sdCandidates }));
    const { container } = render(<SoundDesign dir="film" scene={1} assets={assets} onChanged={() => {}} />);
    fireEvent.click(screen.getByRole("button", { name: "Open sound design…" }));
    await screen.findByText(/How this place sounds/);
    expect((await screen.findByLabelText("Foley sounds")).textContent).toContain("impact: basket of oranges");
    expect(screen.getByLabelText("Layer 1 name")).toHaveValue("Rain on the roof");
    fireEvent.click(screen.getAllByRole("button", { name: /Suggest sounds for/ })[0]);
    expect(await screen.findByLabelText("Suggestions")).toHaveTextContent(/because/);
    fireEvent.click(screen.getByRole("button", { name: "Put into the film" }));
    expect(await screen.findByText(/made, \d+ brought up to date/)).toBeInTheDocument();
    fireEvent.click(screen.getAllByRole("button", { name: "Find in my library" })[0]);
    clean(container);
  });

  it("music director: the real plan, a suggestion, the words for the music and putting it into the film", async () => {
    const assets = [{ id: (muGet as unknown as { spots: { asset_id: string }[] }).spots[0].asset_id, name: "theme", kind: "music" }] as unknown as AudioAsset[];
    invoke.mockImplementation(answers({ "film_music:get": muGet, "film_music:suggest": muSuggest, "film_music:prompt": muPrompt, "film_music:to_cues": muToCues }));
    const { container } = render(<MusicDirector dir="film" scene={1} shots={[{ id: "S01-01", seconds: 3 }]} assets={assets} onChanged={() => {}} />);
    fireEvent.click(screen.getByRole("button", { name: "Open the music director…" }));
    await screen.findByLabelText("State of the music plan");
    expect(screen.getAllByText("Mama's theme").length).toBeGreaterThan(0);
    expect(screen.getByLabelText("Mood")).toHaveValue("tender");
    expect(screen.getByLabelText("Music for this spot")).toHaveValue(assets[0].id);
    expect(screen.getByText(/by Ada for scene 1/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Suggest from the scene (free)" }));
    await screen.findByLabelText("Suggestion");
    fireEvent.click(screen.getByRole("button", { name: "Words to ask for it" }));
    expect(await screen.findByText(/Instrumental film score cue, no vocals/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Put into the film" }));
    expect(await screen.findByRole("status")).toHaveTextContent(/made, \d+ updated/);
    clean(container);
  });

  it("the sound check: the real report, grouped", async () => {
    invoke.mockImplementation(answers({ "film_audioqa:film": qaFilm }));
    const { container } = render(<AudioCheck dir="film" />);
    fireEvent.click(screen.getByRole("button", { name: "Check the sound" }));
    const res = await screen.findByLabelText("Sound check result");
    expect(within(res).getByRole("status")).toHaveTextContent(/measurements, not a quality score/);
    expect(within(res).getByText(/sound files? checked/)).toBeInTheDocument();
    fireEvent.click(within(res).getByText("What this does not measure"));
    clean(container);
  });

  it("timing and ADR: the line's timing, the line-up suggestion and a fitted take", async () => {
    invoke.mockImplementation(answers({ "film_adrsync:get": adGet, "film_adrsync:align": adAlign, "film_adrsync:fit_plan": adFitPlan, "film_adrsync:fit_make": adFitMake, "film_adrsync:nudge": adGet }));
    const { container } = render(<TimingAdr dir="film" shotId="S01-02" who="Mama" onChanged={() => {}} />);
    fireEvent.click(screen.getByRole("button", { name: "Open timing and ADR…" }));
    const place = await screen.findByLabelText("Where the line sits");
    expect(place.textContent).toMatch(/Recording \d+\.\d\d s, 3 frames later: starts 00:00:00:03/);
    expect(screen.getByLabelText("Why it needs ADR")).toHaveValue("a dog barks");
    expect((screen.getByLabelText("This line needs ADR") as HTMLInputElement).checked).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "Line up with the picture's sound" }));
    expect(await screen.findByLabelText("Line-up suggestion")).toHaveTextContent(/frames? (earlier|later)|already lines up/);
    clean(container);
  });

  it("the audio export: the plan and the result", async () => {
    invoke.mockImplementation(answers({ "film_proaudio:plan": paPlan, "film_proaudio:export": paExport }));
    const { container } = render(<ProAudio dir="film" />);
    fireEvent.click(screen.getByRole("button", { name: "Open audio export…" }));
    fireEvent.click(screen.getByRole("button", { name: "What would be made" }));
    expect((await screen.findByLabelText("Plan")).textContent).toMatch(/\d+ files?, about \d+ MB/);
    fireEvent.click(screen.getByRole("button", { name: "Export the audio" }));
    const box = await screen.findByLabelText("Export result");
    expect(within(box).getByRole("status")).toHaveTextContent(/Done: \d+ files in exports\/audio\//);
    expect(within(box).getByText(/FINAL\.wav: -23 LUFS/)).toBeInTheDocument();
    clean(container);
  });

  it("perform it yourself: the installed state and the takes list", async () => {
    invoke.mockImplementation(answers({ "film_revoice:status": revStatus }));
    const takes = (castTakes as unknown as { takes: CastTake[] }).takes;
    const { container } = render(<Revoice dir="film" shotId="S01-02" who="Mama" takes={takes} onChanged={() => {}} />);
    expect(await screen.findByText(/Perform it yourself/)).toBeInTheDocument();
    const installed = (revStatus as unknown as { runtime: { installed: boolean } }).runtime.installed;       // this computer has the model installed (the real run); a computer without it shows the install card instead
    await waitFor(() => expect(container.textContent).toMatch(installed ? /Sound like/ : /Chatterbox voice conversion/));
    clean(container);
  });

  it("the real engine's answers carry every field the screens' types promise (a few that matter most)", () => {
    const o = (voiceidOverview as unknown as { people: Json[] }).people[0];
    for (const k of ["id", "name", "key", "approved", "voice", "lock", "consistency", "accent", "natural", "ratings", "history"]) expect(o, `voice identity person.${k}`).toHaveProperty(k);
    const p = planGet as unknown as { plan: Json; compiled: Json };
    for (const k of ["arc", "events", "pauses", "emphasis", "physical", "pace", "approved"]) expect(p.plan, `plan.${k}`).toHaveProperty(k);
    for (const k of ["text", "tags", "unverified", "not_carried", "speed", "words", "model", "tagged"]) expect(p.compiled, `compiled.${k}`).toHaveProperty(k);
    const t = adGet as unknown as Json;
    for (const k of ["fps", "fps_label", "shot_seconds", "recording", "offset_frames", "starts", "ends", "shot_ends", "runs_past_shot", "fit", "adr"]) expect(t, `timing.${k}`).toHaveProperty(k);
    const x = adAlign as unknown as Json;
    for (const k of ["shift_seconds", "strength", "reliable", "frames", "move_to_frame", "move_by_frames", "words"]) expect(x, `align.${k}`).toHaveProperty(k);
    const e = paExport as unknown as Json;
    for (const k of ["folder", "relative", "files", "problems", "ok", "mixes", "lanes_without_sound", "not_checked"]) expect(e, `export.${k}`).toHaveProperty(k);
  });
});
