import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { audioFacts, commaList, MUSIC_FIELDS, PROFILE_FIELDS, SOUND_FIELDS, voiceKey } from "../soundWords";

describe("the words of the Sound & Music tab", () => {
  it("turns a name into the engine's person key", () => {
    expect(voiceKey("Friend #1")).toBe("friend-1");
    expect(voiceKey("CHLOE DAD")).toBe("chloe-dad");
    expect(voiceKey("  Lila ")).toBe("lila");
  });
  it("reads a comma list without blanks", () => {
    expect(commaList("rain, night ,, soft")).toEqual(["rain", "night", "soft"]);
    expect(commaList("")).toEqual([]);
    expect(commaList("Yard\nKitchen")).toEqual(["Yard", "Kitchen"]);
  });
  it("describes an asset's length and the person's decision in plain words", () => {
    expect(audioFacts({ seconds: 1.4, approval: "pending" })).toBe("1.4 s");
    expect(audioFacts({ seconds: 42.5, approval: "approved" })).toBe("43 s · approved");
    expect(audioFacts({ seconds: 96, approval: "rejected" })).toBe("1:36 · rejected");
    expect(audioFacts({ seconds: 3600, approval: "pending" })).toBe("60:00");
  });
  it("offers the style and profile fields the engine keeps, and no others", () => {
    const py = readFileSync("analysis/filmcrafter_engine/bible.py", "utf8");
    const list = (name: string) => [...(new RegExp(`${name} = \\(([^)]*)\\)`).exec(py)![1].matchAll(/"(\w+)"/g))].map((m) => m[1]);
    expect(PROFILE_FIELDS.map((f) => f[0])).toEqual(list("VOICE_PROFILE_FIELDS"));
    const ss = /SOUND_STYLE_FIELDS = \{"sound": \(([^)]*)\),\s*"music": \(([^)]*)\)\}/.exec(py)!;
    expect(SOUND_FIELDS.map((f) => f[0])).toEqual([...ss[1].matchAll(/"(\w+)"/g)].map((m) => m[1]));
    expect(MUSIC_FIELDS.map((f) => f[0])).toEqual([...ss[2].matchAll(/"(\w+)"/g)].map((m) => m[1]));
  });
});

describe("the tab is wired in and promises only what it does (wiring guard)", () => {
  const cast = readFileSync("src/CastWorld.tsx", "utf8");
  const sm = readFileSync("src/SoundMusic.tsx", "utf8");
  it("is a fifth tab of Cast & World after Props, with no count and no second database", () => {
    expect(cast).toMatch(/\{ id: "prop", label: "Props" \}, \{ id: "sound", label: "Sound & Music" \}/);
    expect(cast).toContain("<SoundMusic dir={dir} b={b} run={run} />");
    expect(cast).toContain('t.id !== "sound"');
  });
  it("has the four areas the brief asks for", () => {
    for (const w of ["Voices", "Sound effects", "Music", "Sound style"]) expect(sm).toContain(`label: "${w}"`);
  });
  it("says it costs nothing and never calls a paid or generating action", () => {
    expect(sm).toContain("Nothing on this page costs anything");
    expect(sm).not.toMatch(/castVoice\("(design|design_save|clone|speak|preview)"/);          // choosing a voice goes through the existing VoiceMaker, which asks first
    expect(sm).not.toContain("confirmed: true");
    expect(sm).toContain("VoiceMaker } from \"./CastVoices\"");
  });
  it("approval is the person's act, asked for, and removing says the file is kept", () => {
    expect(sm).toMatch(/await ask\(`Approve /);
    expect(sm).toContain("not deleted");
    expect(sm).toContain("Bring it back");
  });
  it("the shell allows exactly the audio actions the engine has", () => {
    const rust = readFileSync("src-tauri/src/lib.rs", "utf8");
    expect(rust).toMatch(/ACTIONS: \[&str; 6\] = \["list", "import", "update", "approve", "remove", "restore"\]/);
    expect(rust).toContain('"update_sound_style", "set_voice_profile"');
    expect(readFileSync("src/api.ts", "utf8")).toContain('invoke<T>("film_audio"');
  });
});

import { aiAskWords, aiPriceWords, suggestedCap } from "../soundWords";

describe("Stage B words and wiring", () => {
  it("shows the price of a suggestion honestly and says it only suggests", () => {
    expect(aiPriceWords({ usd: 0, local: true })).toMatch(/free/);
    expect(aiPriceWords({ usd: 0.0042, local: false })).toBe("about $0.0042");
    expect(aiPriceWords({ usd: 0.031, local: false })).toBe("about $0.031");
    const t = aiAskWords("Suggest more natural ways?", "this line", { usd: 0.01, local: false });
    expect(t).toContain("Cost: about $0.010");
    expect(t).toContain("Voice slot: none is taken");
    expect(t).toContain("Nothing is saved or changed until you choose");
  });
  it("suggests a cap just above the price, rounded up to ten, never below it", () => {
    expect(suggestedCap(0)).toBe(0);
    expect(suggestedCap(16)).toBe(20);
    expect(suggestedCap(100)).toBe(120);
    for (const c of [1, 7, 29, 333, 1234]) expect(suggestedCap(c)).toBeGreaterThanOrEqual(c);
  });
  const rd = (f: string) => readFileSync(f, "utf8");
  it("the scene sheet asks with the price and the cap before it sends, and needs a cap that covers the price", () => {
    const v = rd("src/VoiceScene.tsx");
    expect(v.indexOf("await ask(confirmWords(")).toBeLessThan(v.indexOf('"scene_voice"'));
    expect(v).toContain("confirmed: true, cap_credits: capN");
    expect(v).toContain("capN < plan.estimate.credits");
    expect(v).toContain("Pause between lines");
    expect(v).toContain("if a charge is unclear nothing more is sent");
  });
  it("another take and the natural-delivery suggestions ask first, and the spoken version is kept apart from the written line", () => {
    const s = rd("src/LineStudio.tsx");
    expect(s.indexOf("await ask(confirmWords({ action: `Make another take")).toBeLessThan(s.indexOf("new_take: true, confirmed: true"));
    expect(s.indexOf("await ask(aiAskWords(")).toBeLessThan(s.indexOf('"natural_suggest"'));
    expect(s).toContain("Save as the spoken version");
    expect(s).toContain("Go back to the written line");
    expect(s).toContain("the film's written dialogue is never changed");
    expect(s).toContain("The written line has changed since");
  });
  it("suggesting voices is price-first, never saves by itself and never replaces an approved voice without asking", () => {
    const m = rd("src/SoundMusic.tsx");
    expect(m.indexOf("await ask(aiAskWords(")).toBeLessThan(m.indexOf('"voices_suggest"'));
    expect(m).toContain("Put these into the notes above");
    expect(m).toContain("(you still press Save)");
    expect(m).toContain("replace_approved: true");
    expect(m).toMatch(/voice is approved/);
  });
  it("the shell allows exactly the engine's direction actions", () => {
    const rust = rd("src-tauri/src/lib.rs");
    expect(rust).toMatch(/ACTIONS: \[&str; 11\] = \["performance", "performance_set", "performance_clear", "natural_estimate", "natural_suggest", "voices_estimate", "voices_suggest", "voices_match", "scene_plan", "scene_voice", "table_read"\]/);
    expect(rd("src/api.ts")).toContain('invoke<T>("film_voice_direct"');
  });
});

describe("Stage C wiring (scene sound)", () => {
  const rd = (f: string) => readFileSync(f, "utf8");
  it("is a fifth area of Sound & Music, and says it only plans", () => {
    const m = rd("src/SoundMusic.tsx");
    expect(m).toContain('label: "Scene sound"');
    expect(m).toContain("<SceneSound dir={dir} />");
    const s = rd("src/SceneSound.tsx");
    expect(s).toContain("Plans only: nothing here makes sound or costs anything");
    expect(s).toContain("Adjusting a cue never changes the sound file");
    expect(s).toContain("never changed behind your back");
  });
  it("asks the price before the sound director sends anything and offers a free local alternative", () => {
    const s = rd("src/SceneSound.tsx");
    expect(s.indexOf("await ask(aiAskWords(")).toBeLessThan(s.indexOf('"director_suggest"'));
    expect(s).toContain("Quick ideas (free)");
    expect(s).toContain("Nothing in your library fits yet.");              // the library is looked in first, then a plan is offered
    expect(s).toContain("Plan it (needs a sound)");
  });
  it("flags out-of-date cues in words and lets the person confirm instead of changing them", () => {
    const s = rd("src/SceneSound.tsx");
    for (const w of ["sound replaced", "shot length changed", "shot gone", "sound taken out"]) expect(s).toContain(w);
    expect(s).toContain("It is fine");
    expect(s).toContain("Bring it back");
  });
  it("the shell allows exactly the engine's cue actions", () => {
    const rust = rd("src-tauri/src/lib.rs");
    expect(rust).toMatch(/ACTIONS: \[&str; 10\] = \["list", "add", "update", "approve", "remove", "restore", "refresh", "quick", "director_estimate", "director_suggest"\]/);
    expect(rd("src/api.ts")).toContain('invoke<T>("film_cues"');
  });
});

describe("Stage D wiring (making sound and music)", () => {
  const rd = (f: string) => readFileSync(f, "utf8");
  it("is opened from the libraries, shows the price and the rights first, and asks before it sends", () => {
    const m = rd("src/MakeSound.tsx");
    expect(rd("src/SoundMusic.tsx")).toContain("Make with AI…");
    expect(m.indexOf("await ask(confirmWords(")).toBeLessThan(m.indexOf('"generate"'));
    expect(m).toContain("rights_ack: free ? false : rights");
    expect(m).toContain("unknown_cost_accepted: unknown");
    expect(m).toContain("I accept that the price is unknown");
    expect(m).toContain("commercial use: not known");
    expect(m).toContain("Already in your library: free.");
    expect(m).toContain("Make a variation");
    expect(m).toContain("already paid for");
    expect(m).toContain("is never retried by itself");
  });
  it("the make button stays off until the price is known and what must be ticked is ticked", () => {
    const m = rd("src/MakeSound.tsx");
    expect(m).toMatch(/const ready = !!est && !!p\?\.has_key && \(free \|\| \(rights && \(!est\.needs_unknown_cost_accepted \|\| unknown\)\)\)/);
  });
  it("the plan warns about sounds whose rights are not confirmed", () => {
    expect(rd("src/SceneSound.tsx")).toContain("rights you have not confirmed");
  });
  it("the shell allows exactly the engine's generation actions", () => {
    expect(rd("src-tauri/src/lib.rs")).toMatch(/ACTIONS: \[&str; 6\] = \["providers", "estimate", "generate", "pending", "check", "rights"\]/);
    expect(rd("src/api.ts")).toContain('invoke<T>("film_audiogen"');
  });
  it("the usage line mentions Kie.ai credits only as reported", async () => {
    const { usageWords } = await import("../voiceUsage");
    const u = (o: object) => ({ operations: 0, estimated: 0, reported: 0, unreported_operations: 0, estimated_unreported: 0, ...o });
    expect(usageWords({ kie_credits: u({ operations: 1, unreported_operations: 1 }) })).toBe("Kie.ai music: 1 operation so far, credits not reported yet");
    expect(usageWords({ kie_credits: u({ operations: 2, reported: 12 }) })).toBe("Kie.ai music: 12 credits reported");
  });
});

import { cueLaneKinds, cueSeconds } from "../CueLanes";
describe("Stage E (lanes and mixing)", () => {
  const rd = (f: string) => readFileSync(f, "utf8");
  const cue = (o: object) => ({ id: "q-1", kind: "sfx", asset_id: "a", asset_name: "x", asset_file: "f", asset_seconds: 3, scene: 1, shot: "S01-01", start: 1, duration: null, gain_db: 0, fade_in: 0, fade_out: 0,
    loop: false, ducking: "auto", approval: "approved", note: "", source: "manual", fresh: [], needs_sound: false, created: 0, updated: 0, ...o }) as never;
  it("a cue is heard for what was set, else its whole sound, else (a loop) until its shot ends", () => {
    expect(cueSeconds(cue({ duration: 2 }), 10, 4)).toBe(2);
    expect(cueSeconds(cue({}), 10, 4)).toBe(3);
    expect(cueSeconds(cue({ loop: true }), 10, 4)).toBe(5);                              // 4 + 1 = 5; the shot ends at 10
    expect(cueSeconds(cue({ loop: true }), 4.5, 4)).toBeGreaterThanOrEqual(0.2);
  });
  it("only the lanes that have something in them are shown, and rejected cues do not count", () => {
    const list = { cues: [cue({ kind: "music" }), cue({ kind: "sfx", approval: "rejected" })] } as never;
    expect(cueLaneKinds(list)).toEqual(["music"]);
    expect(cueLaneKinds(null)).toEqual([]);
  });
  it("the timeline reserves room for the lanes only in Edit mode and the Film strip stays as it was", () => {
    const s = rd("src/Studio.tsx");
    expect(s).toContain("const cueKinds = !edit || compact || !voiceFilm ? [] : cueLaneKinds(cueData.list);");
    expect(s).toContain("<CueLanes dir={voiceFilm}");
    expect(s).toContain("+ cueH : 28 + 18");
  });
  it("a clip is moved or adjusted without touching the sound file, and a muted cue is only left out of the film", () => {
    const c = rd("src/CueLanes.tsx");
    expect(c).toContain("Nothing here changes the sound file.");
    expect(c).toContain("Leave it out of the film");
    expect(c).toContain("never before the start of its shot");
    expect(c).toContain('api.filmCues("update"');
    expect(c).not.toMatch(/filmAudio\("(remove|import)"/);
  });
  it("the mix controls are plain, say that previews do not change the film, and the shell allows exactly the mix actions", () => {
    const s = rd("src/SceneSound.tsx");
    expect(s).toContain("a preview: the film is not changed");
    expect(s).toContain("a limiter so nothing clips");
    expect(s).toContain("Online video (-16 LUFS)");
    expect(rd("src-tauri/src/lib.rs")).toMatch(/ACTIONS: \[&str; 9\] = \["settings", "set_settings", "preview", "automation_set", "group_set", "group_remove", "marker_add", "marker_remove", "crossfade"\]/);
    expect(rd("src/api.ts")).toContain('invoke<T>("film_mix"');
  });
});

describe("Stage F wiring (what may be out of date)", () => {
  const rd = (f: string) => readFileSync(f, "utf8");
  it("the panel says nothing was changed, offers the options with their price first, and shows nothing when all is current", () => {
    const p = rd("src/OutdatedPanel.tsx");
    expect(p).toContain("nothing was changed");
    expect(p).toContain("Lip-sync this take…");
    expect(p).toContain("show their price first");
    expect(p).toContain("an approved take is never replaced by itself");
    expect(p).toContain("if (!r || (r.clean && !models.length)) return null;");
    expect(rd("src/CastVoices.tsx")).toContain("<OutdatedPanel dir={dir} />");
    expect(rd("src/SceneSound.tsx")).toContain("<OutdatedPanel dir={dir} />");
  });
  it("the shell exposes the read-only report and the validation doc does not claim a result", () => {
    expect(rd("src-tauri/src/lib.rs")).toContain("filmcrafter_engine.outdated");
    expect(rd("src/api.ts")).toContain('invoke<OutdatedReport>("film_outdated"');
    const doc = rd("docs/LIPSYNC_VALIDATION.md");
    expect(doc).toContain("one real run was made");
    expect(doc).toContain("not by a person watching and listening");
  });
});

describe("Stage G wiring (model registry, updates)", () => {
  const rd = (f: string) => readFileSync(f, "utf8");
  it("Settings shows when each provider's model list was read and refreshes only on request, saying that nothing is changed when a list cannot be read", () => {
    const m = rd("src/ModelsRow.tsx");
    expect(rd("src/Settings.tsx")).toContain("<ModelsRow />");
    expect(m).toContain("Refresh the model lists");
    expect(m).toContain("not changed (");
    expect(m).toContain("kept apart from the app");
    expect(rd("src-tauri/src/lib.rs")).toMatch(/ACTIONS: \[&str; 4\] = \["status", "list", "refresh", "in_use"\]/);
  });
  it("models behind a film that went away are reported, never replaced", () => {
    const p = rd("src/OutdatedPanel.tsx");
    expect(p).toContain("Nothing was replaced, and nothing will be swapped for approved work");
    expect(p).toContain('api.registry<ModelWarnings>("in_use", dir)');
  });
  it("before the person is sent to a new version the films' records are snapshotted, and the update stays off until it can be verified", () => {
    const u = rd("src/Updates.tsx");
    expect(u).toContain("await api.prepareUpdate(u.latest)");
    expect(u).toContain("export const UPDATES_ENABLED = false;");
    expect(rd("src-tauri/src/lib.rs")).toContain("filmcrafter_engine.preupdate");
    expect(rd("docs/UPDATES.md")).toContain("updates are NOT switched on");
  });
});

describe("shared class names stay unique (a regression that broke every small button)", () => {
  it("no stylesheet gives the bare class .sm a rule: it is the small-button size (.btn.sm) and a wrapper once used it for a flex column", () => {
    for (const f of ["styles", "polish", "motion", "film", "corners", "focus", "lanes", "acting", "sound", "studio-shared", "palette", "ui-system"]) {
      const css = readFileSync(`src/${f}.css`, "utf8");
      expect(css, f).not.toMatch(/(^|\n)\.sm\s*[{,]/);
    }
    expect(readFileSync("src/SoundMusic.tsx", "utf8")).toContain('<div className="snd">');
  });
});
