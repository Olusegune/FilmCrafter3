/**
 * The screenshot harness: renders one real screen of the app with made-up data, so the guide's pictures (docs/img) can be regenerated and so a layout can be looked at without the desktop shell.
 *
 *   npm run dev                                  (the preview on http://localhost:1420)
 *   node scripts/docshots-edge.mjs               (every scene)   or   node scripts/docshots-edge.mjs review kt   (just those)
 *   http://localhost:1420/docshots.html?scene=review   (look at one in a browser)
 *
 * Nothing here ships in the app: only index.html is built. The pictures are placeholders made by make_samples.py; the direction and look texts are the app's own.
 * A scene can be told what to do once it is up: &click=<button text> presses a button, &drag=x0,y0,x1,y1 drags a box on the Fix a hand picture (fractions of the picture).
 */
import { SoundPlan } from "../SoundPlan";
import { SetBuilder } from "../SetBuilder";
import set3d from "./set3d.json";
import { DirectorCam } from "../DirectorCam";
import { CutoutStudio } from "../CutoutStudio";
import vpGet from "../__tests__/fixtures/engine/vp_get.json";
import dcPlans from "../__tests__/fixtures/engine/directorcam_plans.json";
import dcPlan from "../__tests__/fixtures/engine/directorcam_plan_get.json";
import dcPreview from "../__tests__/fixtures/engine/directorcam_preview.json";
import dcWlGet from "../__tests__/fixtures/engine/directorcam_worldlock_get.json";
import dcWlList from "../__tests__/fixtures/engine/directorcam_worldlock_list.json";
import { ReadinessSheet } from "../ReadinessSheet";
import { PacingSheet } from "../PacingSheet";
import { GivenToModel } from "../GivenToModel";
import { createRoot } from "react-dom/client";
import { mockIPC, mockWindows } from "@tauri-apps/api/mocks";
import { useState, type ReactNode } from "react";
import { RenderQueueSheet } from "../RenderQueue";
import { ReviewSheet } from "../Review";
import { KeyframeTools } from "../KeyframeTools";
import { HandFix } from "../HandFix";
import { RoutingSheet } from "../Routing";
import { SelectReview } from "../SelectReview";
import { DirectionLibrarySheet } from "../DirectionLibrary";
import { LookPicker } from "../Looks";
import { LightingSheet } from "../Lighting";
import { CleanupSheet } from "../Cleanup";
import { ModelPicker } from "../ModelPicker";
import { ModelChoice } from "../ModelChoice";
import { ComposeTab } from "../Compose";
import { TakeCompare } from "../Compare";
import { LayersPanel } from "../Layers";
import { LayerLanes } from "../LayerLanes";
import { ColourMatchSheet } from "../ColourMatch";
import { SupervisorSheet } from "../Supervisor";
import { PerformanceSheet, ShotPerformance } from "../Performance";
import { ColorStudioSheet } from "../ColorStudio";
import { SmartEditorSheet } from "../SmartEditor";
import { PresetsSheet } from "../PresetLibrary";
import { MotionGraphicsSheet } from "../MotionGraphics";
import { FirstFilm } from "../FirstFilm";
import { ExportSheet } from "../Export";
import { FidelitySheet } from "../FidelitySheet";
import presetsBuiltin from "../../analysis/filmcrafter_engine/presets_builtin.json";
import { LibrarySheet } from "../Board";
import { Home } from "../Home";
import { Settings } from "../Settings";
import { NewFilm } from "../NewFilm";
import { FilmView } from "../FilmView";
import { CastWorld } from "../CastWorld";
import { ShotLab } from "../ShotLab";
import { MakeFilm } from "../MakeFilm";
import { FilmContinuity } from "../FilmContinuity";
import { AssistSheet } from "../AssistSheet";
import { ShotSuggestionSheet } from "../ShotSuggestionSheet";
import { Studio, ShotInspector } from "../Studio";
import { AgentStudio } from "../AgentStudio";
import { DirectorStyleSheet } from "../DirectorStyle";
import { ShotLook, saveShotLook } from "../ShotLook";
import { shotLookToSave } from "../styleStale";
import renderFixture from "./render-fixture.json";
import type { Job, LoadedProject, Shot, StyleBibleRead } from "../api";
import directions from "./directions.json";
import styles from "../../analysis/filmcrafter_engine/styles.json";
import "../styles.css";
import "../studio-shared.css";
import "../motion.css";
import "../acting.css";
import "../sound.css";
import "../focus.css";
import "../polish.css";
import "../film.css";
import "../corners.css";
import "../ui-system.css";            // after everything: one set of controls, one focus ring

const DIR = "/src/docshots/img";
(window as unknown as { __PF_MOCK__: boolean }).__PF_MOCK__ = true;
const q = new URLSearchParams(location.search);
// ?n=300 makes the sample film that long, to see how the screens hold up (the engine's own numbers for a 300-shot film are in docs/QA.md)
const N = Math.max(0, Number(q.get("n")) || 0);
const bigId = (i: number) => `S${String(Math.floor(i / 8) + 1).padStart(2, "0")}-${String((i % 8) + 1).padStart(2, "0")}`;
const grow = <T extends { id: string; scene?: number }>(list: T[]): T[] => (N > list.length ? Array.from({ length: N }, (_, i) => ({ ...list[i % list.length], id: bigId(i), scene: Math.floor(i / 8) + 1 })) : list);
const scene = q.get("scene") ?? "review";
const now = Math.floor(Date.now() / 1000);

// ---------------------------------------------------------------- made-up data
const ids = N > 8 ? Array.from({ length: N }, (_, i) => bigId(i)) : ["S01-01", "S01-02", "S01-03", "S01-04", "S01-05", "S01-06", "S02-01", "S02-02"];
const shots: Shot[] = ids.map((id, i) => ({ id, scene: Number(id.slice(1, 3)), number: i + 1, start: i * 6.5, end: i * 6.5 + 6, beats: ["Sege looks at the sea."], source_shots: [], performers: ["Sege"], framing: ["Close-up", "Wide", "Medium", "Over the shoulder"][i % 4], state: "ready", renderer: "x" }));
const still = (n: number) => `s${(n % 6) + 1}.png`;
const issue = (kind: string, severity: "minor" | "major", detail: string) => ({ kind, severity, detail, fix: "" });
const mk = (id: string, shot: string, created: number, over: Record<string, unknown> = {}): Job => ({ id, shot_id: shot, plan: "production", provider: "kie", model: "bytedance/seedance-2", state: "ready", kind: "video", output: `v${(created % 3) + 1}.mp4`, created, updated: created, overrides: {}, cost: 50, cost_unit: "credits", ...over } as unknown as Job);
const reviewJobs: Job[] = [
  mk("a1", "S01-03", 100, { review: { reviewed: true, status: "good", summary: "Looks good.", issues: [] } }),
  mk("a2", "S01-03", 200, { review: { reviewed: true, status: "needs_attention", summary: "The mood is strong, but the shot is framed as a full facial close-up instead of the specified ear-cheek-jaw detail.", issues: [issue("framing", "major", "The frames show Sege's full face and eyes, with a lot of bedroom background, rather than a tight close-up on his ear, cheek, beard, and jaw."), issue("wardrobe", "minor", "Sege's green outer shirt collar is prominent, while the shot calls for the white undershirt collar visible against his neck."), issue("anatomy", "major", "The held hands are fused into one mass; the fingers can't be told apart.")] } }),
  mk("b1", "S02-02", 100, { review: { reviewed: true, status: "good", summary: "Looks good.", issues: [] } }),
  mk("b2", "S02-02", 200, { review: { reviewed: true, status: "needs_attention", summary: "The emotional beat is present, but the shot is too wide and the scar is not clearly revealed.", issues: [issue("framing", "major", "This is a medium view of Sege from the waist up, not the requested static close-up on his hand, open shirt edge, and scar."), issue("wardrobe", "minor", "The white undershirt covers most of Sege's chest, so the open linen shirt does not clearly reveal the faint scar.")] } }),
  mk("c1", "S01-01", 100, { review: { reviewed: true, status: "needs_attention", summary: "Sege's hands look wrong in this take.", issues: [issue("anatomy", "major", "Fingers on the left hand are fused.")] } }),
  mk("d1", "S01-02", 100, { review: { reviewed: true, status: "minor", summary: "Slightly dark but usable.", issues: [issue("look", "minor", "The light is a little darker than the look asks for.")] } }),
  mk("e1", "S01-04", 100, { review: { reviewed: true, status: "good", summary: "Looks good.", issues: [] } }),
  mk("f1", "S02-01", 100, { review: { reviewed: true, status: "minor", summary: "Good, with a small continuity slip.", issues: [issue("wardrobe", "minor", "The jacket is slightly lighter than in the previous shot.")] } }),
];
const queueJobs: Job[] = [
  mk("q1", "S01-01", 1, { created: now - 200, updated: now - 5, state: "submitted", output: null, submitted: now - 90, progress: 0.4 }), mk("q2", "S01-02", 2, { created: now - 150, updated: now - 150, state: "queued", output: null }),
  mk("q3", "S01-03", 3, { created: now - 400, updated: now - 120, state: "failed", output: null, error: "The provider had an internal error. Nothing was sent or charged. Provider said: 500 Internal Server Error", error_kind: "service", estimate_usd: 0.9 }),
  mk("q4", "S02-01", 4, { created: now - 500, updated: now - 60 }),
];
const lightShots = ids.flatMap((id, i) => {
  const rows = [["Calm", "Golden hour", 5600, 1], ["Calm", "Golden hour", 5600, 1], ["Tension", "Single hard key", 5600, 2], ["Tension", "Single hard key", 5600, 2], ["Tension", "Single hard key", 5600, 2], ["Hope", "Golden hour", 4500, 1], ["Joy", "Golden hour", 4800, 1], ["Nostalgia", "Golden hour", 3400, 2]] as const;
  const [label, name, kelvin, level] = rows[i % rows.length];
  return [{ shot: id, scene: Number(id.slice(1, 3)), start: i * 2.2, end: i * 2.2 + 2, section: "verse", mood: label.toLowerCase(), label, valence: 0, arousal: 0, intensity: 0.4, user_set: false, held: i === 1,
    why: `${label} (read from the feeling and words of the shot; the song is quiet here) → ${name.toLowerCase()}, neutral, gentle contrast.`,
    design: { label: name, kelvin, level, wording: `${name.toLowerCase()} sunlight, warm low rays and long shadows; neutral colour (about ${kelvin} K); key large and soft from a window; gentle contrast; colour accents: pale neutral` } }];
});
const lightingPlan = { count: lightShots.length, user_set: 0, shots: lightShots, scenes: [{ scene: 1, heading: "INT. SEGE'S BEDROOM - BEFORE DAWN", from: "Calm", to: "Hope", arc: "Calm → Tension → Hope", terms: [] }, { scene: 2, heading: "INT. SEGE'S KITCHEN / CHILDHOOD HOME - MORNING", from: "Joy", to: "Nostalgia", arc: "Joy → Calm → Nostalgia", terms: [] }] };
const cleanupItems = Array.from({ length: 12 }, (_, i) => ({ path: `v${(i % 3) + 1}.mp4`, name: `take-${i}.mp4`, kind: "video" as const, size: (3 + (i % 5)) * 1.2e6, shot: ids[i % ids.length], model: ["image-to-video", "seedance-2-mini", "video-to-video-lipsync", "3-0-video"][i % 4], created: now - 5000, cost: null, cost_unit: null, what: "older take" }));
const cleanupScan = { items: cleanupItems, bytes: 4.2e7, kept: 31, rendering: 0, trash: { batches: 1, files: 4, bytes: 9e6 } };
const row = (label: string, provider: string, model: string, price: number | null, verified: boolean, extra: Record<string, unknown> = {}) => ({ label, provider, model, price_usd: price, verified, strength: "Keeps people looking like themselves from your reference pictures, at a low price.", consider: "For a whole project on a budget, and when the same characters appear in many shots.", watch: "Check hands and faces on important shots.", ...extra });
const project: LoadedProject = { dir: DIR, project: { title: "Exit Plan", state: "ready", song: "song.wav" }, song_path: null, song_map: null, production: null, directed: null, jobs: [],
  concepts: { concepts: [
    { title: "The Long Way Home", premise: "A son walks the streets of his childhood at dawn, remembering the people who raised him, until the song's last chorus brings him to his mother's door.", mood: "Tender, nostalgic", performance_approach: "Performance woven into memory: he sings to no one, then to everyone.", cinematic_style: "Handheld, warm, shallow focus; long takes that drift with him.", palette: ["faded amber", "dusty blue", "cream", "deep green"], environment: "Lagos streets at dawn, a market, a kitchen with the radio on.", wardrobe: "A worn linen shirt, white undershirt, a bracelet.", movement: "Slow walking, small gestures, a held hand.", narrative_level: "narrative", hero_frame: "Sege in the doorway, morning light on his face, a woman's hand reaching for his.", suggested_look: "painterly" },
    { title: "One Room, One Night", premise: "The whole song in a single bedroom lit by the city outside: a man who cannot sleep, a partner who can, and the distance between them.", mood: "Intimate, restless", performance_approach: "Close, quiet, mostly on his face.", cinematic_style: "Static frames, hard single-source light, slow push-ins.", palette: ["night blue", "tungsten amber", "charcoal"], environment: "A bedroom above a city, rain on the window.", wardrobe: "A white tee, bare feet.", movement: "Barely any: breathing, turning, a hand on a sheet.", narrative_level: "hybrid", hero_frame: "His eye, open in the dark, the skyline reflected in it.", suggested_look: "cinematic" },
    { title: "Carnival of Small Things", premise: "The song as a parade: everyday objects and neighbours dancing through the neighbourhood, with Sege leading it, part conductor and part passenger.", mood: "Joyful, bright", performance_approach: "Big, rhythmic, ensemble.", cinematic_style: "Wide, symmetrical, saturated, whip pans on the beat.", palette: ["marigold", "hot pink", "turquoise", "primary accents"], environment: "A neighbourhood in festival, rooftops, a street market.", wardrobe: "Bright layered clothes, fabric prints.", movement: "Dancing, walking in step, throwing colour.", narrative_level: "performance", hero_frame: "Sege on a rooftop, the whole street below in colour, arms wide.", suggested_look: "vivid" },
  ] } };

const layer = (id: string, kind: string, text: string, start: number | null, end: number | null, over: Record<string, unknown> = {}) => ({ id, kind, text, source: "own", start, end, x: 0.5, y: 0.5, size: 0.08, width: 0.6, color: "#ffffff", fade: 0.3, enabled: true, placed: start !== null, reason: "", explicit: true, explicit_end: true, ...over });
const layerList = [layer("l1", "text", "Exit Plan", 2, 7), layer("l2", "icon", "Heart", 4, 9, { icon: "heart" }), layer("l3", "fill", "Warm tint", 0, 30, { color: "#e8b45c", opacity: 0.18 }), layer("l4", "text", "Lagos, 2019", 12, 16)];
// A picture layer whose mix, mask and cut-out colour can be changed: updates are kept (and cleaned the way the engine cleans them) so the panel can be clicked through
const MIXDIR = "/mixfilm";
const mixStore = { list: [layer("l5", "image", "Green screen", 1, 6, { file: "assets/x.png" })] as Record<string, unknown>[] };
const clipStore = { list: [layer("l6", "clip", "interview.mp4", 1, 9, { file: "assets/overlays/ov_clip.mp4", src_w: 1920, src_h: 1080, src_dur: 12.4, in_s: 0, width: 0.4 })] as Record<string, unknown>[] };
const MIXCLIPDIR = "/clipfilm";
const mixOverlays = (x: { action?: string; data?: Record<string, unknown> }, store = mixStore): unknown => {
  if (x.action === "key_suggest") return { found: true, kind: "green", color: "#1fae4b", sure: 0.93 };
  if (x.action === "update") {
    const { id, ...rest } = (x.data ?? {}) as { id?: string } & Record<string, unknown>;
    store.list = store.list.map((l) => {
      if (l.id !== id) return l;
      const n: Record<string, unknown> = { ...l, ...rest };
      if (n.blend === "normal") delete n.blend;
      if (n.mask === "none") { for (const k of ["mask", "mask_size", "mask_feather", "mask_invert"]) delete n[k]; }
      else if (n.mask && n.mask_size === undefined) n.mask_size = 0.8;
      if (n.key_color === "") { for (const k of ["key_color", "key_tol", "key_soft", "key_spill"]) delete n[k]; }
      if (n.loop === false) delete n.loop;
      return n;
    });
  }
  return store.list;
};
const colourState = { enabled: true, strength: 0.7, reference: null, analysed: 12, adjusted: 2, cast: true, cast_strength: 0.85, cast_seen: { u: -14, v: 6, size: 15.2, label: "yellow", noticeable: true }, cast_fix: { u: 12, v: -5 }, denoise: false, grain: false, picture_care: true, rows: ids.map((id, i) => ({ shot: id, distance: i === 2 ? 0.34 : i === 5 ? 0.22 : 0.05 + (i % 3) * 0.02, bright: i === 2 ? 0.3 : -0.2, adjusted: i === 2 || i === 5, is_reference: false })) };

const filmText = ["INT. KITCHEN - MORNING", "", "Sarah pours tea. Her hands are not steady.", "", "SARAH", "(quietly)", "He said he would call.", "", "JOHN (O.S.)", "Did you say something?", "", "EXT. PLATFORM - NIGHT", "", "Rain on the roof. A train waits.", "", "SARAH", "I am going.", "", "JOHN", "Then go.", "", "INT. TRAIN - NIGHT", "", "Sarah sits. She looks at her phone. Nothing."].join(String.fromCharCode(10));
const filmScene = (number: number, heading: string, line: number, location: string, time: string, characters: string[], d: number, a: number, int_ext = "INT") => ({ number, heading, int_ext, location, time, characters, dialogue_lines: d, action_lines: a, words: 20, seconds: 48 + number * 6, line });
const filmStatus = { title: "Last Train", aspect_ratio: "16:9", mode: "simple", stage: "story", created: now,
  story: { kind: "screenplay", current: 2, locked: null, lock_history: [], as_is: null, original: "last-train.fountain" }, version: 2, text: filmText, kind: "screenplay", note: "Sharper ending", locked_here: false,
  found: { kind: "screenplay", words: 61, pages: 2.4, rung: "screenplay", seconds: 144, has_headings: true,
    scenes: [filmScene(1, "INT. KITCHEN - MORNING", 0, "KITCHEN", "MORNING", ["SARAH", "JOHN"], 2, 1), filmScene(2, "EXT. PLATFORM - NIGHT", 11, "PLATFORM", "NIGHT", ["SARAH", "JOHN"], 2, 1, "EXT"), filmScene(3, "INT. TRAIN - NIGHT", 21, "TRAIN", "NIGHT", [], 0, 1)],
    characters: [{ name: "SARAH", scenes: [1, 2], scene_count: 2, first_scene: 1 }, { name: "JOHN", scenes: [1, 2], scene_count: 2, first_scene: 1 }], locations: [{ name: "KITCHEN", scenes: [1] }, { name: "PLATFORM", scenes: [2] }, { name: "TRAIN", scenes: [3] }] },
  advice: [
    { id: "thin-3", topic: "structure", text: "Scene 3 (INT. TRAIN - NIGHT) has almost nothing in it. Is it a transition, or is something missing?", scene: 3, status: "open" },
    { id: "talky-1", topic: "visual storytelling", text: "Scene 1 is almost all dialogue. A look, a gesture or an object could carry some of it.", scene: 1, status: "open" },
    { id: "length", topic: "production", text: "About 2.4 minutes of script. The first pass works best on one scene or a short of 1 to 3 minutes; you can start with one scene.", scene: null, status: "dismissed" }],
  versions: [{ version: 1, kind: "screenplay", note: "As supplied", parent: null, origin: "imported", created: now - 3600, fingerprint: "a1", locked: false, words: 58 }, { version: 2, kind: "screenplay", note: "Sharper ending", parent: 1, origin: "written", created: now, fingerprint: "b2", locked: false, words: 61 }] };

const spatialEmpty = { entrances: "", exits: "", doors: "One door, left of the stove", windows: "Large window over the sink, morning light", landmarks: "A radio on the shelf", furniture: "Round table, four chairs", blocking: "", camera_zones: "", lighting: "", day_night: "" };
const bibleView = { sound_style: { sound: { philosophy: "Quiet and close, like being in the room.", realism: "", ambience: "Rain, always, low.", dialogue: "Voices stay clear above everything.", silence: "After the letter." }, music: { genre: "Chamber", instrumentation: "Solo piano, a music box", mood: "Tender", tempo: "", influences: "", palette: "", motifs: "A music box for Lila", intensity: "", silence: "" } }, rev: 4, updated: now, rules: { world: "A coastal town where it rains most evenings.", tone: "Quiet, restrained, a little sad.", rules: "Sarah never takes off her ring.", avoid: "Slapstick, bright neon." },
  philosophy: { visual: "Muted, lived-in.", cinematography: "Mostly locked-off, slow pushes.", lighting: "Motivated, low key, practical lamps.", acting: "Restraint: the feeling shows in the eyes.", colour: "Teal shadows, amber practicals.", continuity: "Sarah's coat is torn after scene 2." },
  style: { lane: "painterly animation", notes: "", traits: "Oil paint texture, soft edges, visible brush marks.", references: ["Quiet domestic painting", "Overcast seaside light"] },
  characters: [
    { id: "c_sarah", name: "Sarah", role: "Lead", age: "28", physical: "Tall, grey eyes, dark hair tied back", relationships: "John's partner", arc: "From waiting to leaving", voice: "Low, careful", notes: "", wardrobe: [{ id: "w1", name: "Red coat", notes: "Wool, torn pocket" }],
      states: [{ id: "s1", label: "Default", notes: "" }, { id: "s2", label: "Age 8", notes: "Hair in plaits", age: "8", wardrobe: "" }], media: [{ path: "s1.png", kind: "master", label: "Master" }, { path: "s2.png", kind: "front", label: "Front view" }], scenes: [1, 2], source: "story" },
    { id: "c_john", name: "John", role: "", age: "", physical: "", relationships: "", arc: "", voice: "", notes: "", wardrobe: [], states: [{ id: "s1", label: "Default", notes: "" }], media: [{ path: "s3.png", kind: "master", label: "Master" }], scenes: [1, 2], source: "story" }],
  environments: [{ id: "e_kitchen", name: "Kitchen", description: "A narrow family kitchen", notes: "", spatial: spatialEmpty, states: [{ id: "s1", label: "Morning", notes: "" }, { id: "s2", label: "Night", notes: "" }], media: [{ path: "s4.png", kind: "master", label: "Master" }], scenes: [1], source: "story" },
    { id: "e_platform", name: "Platform", description: "", notes: "", spatial: { ...spatialEmpty, doors: "", windows: "", landmarks: "", furniture: "" }, states: [{ id: "s1", label: "Night", notes: "" }], media: [], scenes: [2], source: "story" }],
  props: [{ id: "p_the-letter", name: "The letter", notes: "Cream envelope", states: [{ id: "s1", label: "Default", notes: "" }], media: [], scenes: [], source: "manual" }],
  lanes: ["photoreal cinematic", "photoreal CGI", "feature 3D", "stylized 3D", "graphic 3D", "low-poly 3D", "hand-drawn 2D", "2D animation", "painterly animation", "anime-inspired", "graphic comic-inspired animation", "stop motion", "clay", "miniature", "mixed media", "experimental animation"],
  families: [{ id: "photoreal", name: "Photorealistic", blurb: "Looks like it was filmed: real light, real skin, real places.", lanes: ["photoreal cinematic", "photoreal CGI"] },
    { id: "3d", name: "3D animation", blurb: "Computer-made characters and worlds, from storybook to cel-shaded.", lanes: ["feature 3D", "stylized 3D", "graphic 3D", "low-poly 3D"] },
    { id: "2d", name: "2D animation", blurb: "Drawn and painted: classic hand-drawn, anime, comic and watercolour.", lanes: ["hand-drawn 2D", "2D animation", "painterly animation", "anime-inspired", "graphic comic-inspired animation"] },
    { id: "hybrid", name: "Hybrid 2D/3D", blurb: "Mixed worlds: 3D with drawn accents, collage, paper theatre, parallax.", lanes: [] },
    { id: "craft", name: "Hands-on crafts", blurb: "Made by hand and shot frame by frame: stop motion, clay, paper, miniatures.", lanes: ["stop motion", "clay", "miniature", "mixed media", "experimental animation"] },
    { id: "art", name: "Art movements & experimental", blurb: "Painting movements, print and folk art, and experimental graphic looks.", lanes: [] }].map((f) => ({ ...f, looks: (styles as { styles: { id: string; name: string; description: string; family: string }[] }).styles.filter((s) => s.family === f.id).map(({ id, name, description }) => ({ id, name, description })) })),
  genres: (styles as { styles: { id: string; name: string; description: string; family: string }[] }).styles.filter((s) => s.family === "genre").map(({ id, name, description }) => ({ id, name, description })),
  family: "craft", look: "stop-motion", genre: "g-biblical-epic", principles_custom: false,
  principles_on: ["squash-stretch", "anticipation", "staging", "follow-through", "slow-in-out", "arcs", "secondary-action", "timing", "exaggeration", "solid-drawing", "appeal"],
  principles: [["squash-stretch", "Squash and stretch", "Soft things flatten on impact and lengthen in fast motion, keeping their volume."], ["anticipation", "Anticipation", "A small opposite move prepares the big one: a crouch before a jump."],
    ["staging", "Staging", "One idea reads at once: a clear silhouette, nothing competing."], ["pose-to-pose", "Pose to pose", "Strong key poses first, then the in-betweens."],
    ["follow-through", "Follow-through and overlapping action", "Loose parts keep going a beat longer and settle at different times."], ["slow-in-out", "Slow in and slow out", "Movements ease in and out; nothing moves at one constant speed."],
    ["arcs", "Arcs", "Natural movement travels along curves, not straight lines."], ["secondary-action", "Secondary action", "A blink, a breath, a fidget supports the main action."],
    ["timing", "Timing", "How long a moment lasts says what it means."], ["exaggeration", "Exaggeration", "Push poses and faces a little past real life so the feeling reads."],
    ["solid-drawing", "Solid drawing", "Bodies keep weight and volume from every angle."], ["appeal", "Appeal", "Characters are easy to read and good to look at."]].map(([id, name, plain]) => ({ id, name, plain, fits: true, default: id !== "pose-to-pose" })),
  media_kinds: ["master", "front", "reference"], need: [], counts: { characters: 2, environments: 2, props: 1, characters_with_pictures: 2 } };

const blockingPlanMock = { people: [{ name: "Sarah", x: 30, y: 36, facing: 20 }, { name: "John", x: 72, y: 34, facing: 190 }], props: [{ name: "Tea", x: 24, y: 24 }], camera: { x: 12, y: 46, aim: 342, fov: 42 } };
const voiceStatus = {
  people: 5, recorded: 2, missing: 3, problems: 1,
  shots: [
    { id: "S01-02", scene: 1, title: "Lila speaks.", seconds: 3, others: ["Chloe"], notes: ["Lila: 3.4 s recording, 3.0 s shot: the shot is lengthened to hold it"],
      people: [{ name: "Lila", key: "lila", lines: ["She eats the weirdest stuff."], recording: { file: "voice/S01-02/lila.wav", name: "LILA_S01-02.wav", seconds: 3.4, rms_db: -21.2, peak_db: -4.1 } }] },
    { id: "S01-03", scene: 1, title: "Friend #1 speaks to Lila.", seconds: 2, others: [],
      people: [{ name: "Friend #1", key: "friend-1", lines: ["Like what?"], recording: { file: "voice/S01-03/friend-1.wav", name: "friend1_S01-03_take2.wav", seconds: 1.6, rms_db: -23.0, peak_db: -6.0 } },
               { name: "Lila", key: "lila", lines: ["Yesterday? It looked like... spiced beans?"], recording: null }] },
    { id: "S01-05", scene: 2, title: "Ethan speaks.", seconds: 5.4, others: ["Chloe"],
      people: [{ name: "Ethan", key: "ethan", lines: ["Hey. You coming to the thing on Friday?"], recording: null }] },
    { id: "S02-01", scene: 2, title: "Chloe speaks to Ethan.", seconds: 3.4, others: [], people: [{ name: "Chloe", key: "chloe", lines: ["I might."], recording: null }] },
  ],
};

const pickerCatalog = [
  { model: "kling/3-0", title: "Kling · Kling 3.0", rec: 1, fresh: true, sees: true },
  { model: "kling/v3-turbo-image-to-video", title: "Kling · V3 Turbo Image to Video", sees: true },
  { model: "kling/3-0-omni-image-to-video", title: "Kling · Kling 3.0 Omni Image To Video", sees: true },
  { model: "bytedance/seedance-2", title: "Bytedance · seedance-2", rec: 2, sees: true },
  { model: "bytedance/seedance-2-5", title: "Bytedance · Bytedance Seedance 2.5", rec: 3, fresh: true, sees: true },
  { model: "minimax/h3-image-to-video", title: "MiniMax · MiniMax H3 Image-to-Video", sees: true },
  { model: "wan/3-0-video", title: "Wan · Wan 3.0 - Video", sees: true },
  { model: "happyhorse/image-to-video", title: "HappyHorse · HappyHorse-1-1 image-to-video", sees: true },
  { model: "google/veo3-1", title: "Google · Veo 3.1", rec: 4, sees: true },
  { model: "runway/gen4", title: "Runway · Gen-4 Turbo", sees: true },
] as never[];
const blockingMock = { id: "S01-02", scene: 1, framing: "over the shoulder", plan: blockingPlanMock, suggested: null, has_previous: true, people: ["Sarah", "John"], room: { w: 100, h: 70 },
  text: "Blocking as the camera sees it: John screen-right, facing screen-left. Camera over Sarah's shoulder.",
  scene_shots: [{ id: "S01-01", framing: "wide", plan: { ...blockingPlanMock, camera: { x: 50, y: 66, aim: 270, fov: 65 } } }, { id: "S01-02", framing: "over the shoulder", plan: blockingPlanMock }, { id: "S01-03", framing: "over the shoulder", plan: { ...blockingPlanMock, camera: { x: 90, y: 20, aim: 190, fov: 40 } } }],
  crossings: [] as { shot: string; previous: string; message: string; fix: string }[] };
const continuityMock = { open: 3, shots: 6, findings: [
  { id: "f1", kind: "character", shot: "S02-03", other: "", severity: "likely", status: "open", text: "Sarah may have changed outfit: red coat in S02-02, grey cardigan in S02-03.", suggestion: "If the change is meant, ignore this. If not, set them to the same outfit." },
  { id: "f2", kind: "direction", shot: "S01-03", other: "", severity: "look", status: "open", text: "The camera is on the other side of the line between Sarah and John than in S01-02, so they may swap sides on screen.", suggestion: "Move the camera back to the other side of the dashed line, or cut away to an insert or a wide shot first." },
  { id: "f3", kind: "state", shot: "S01-04", other: "", severity: "note", status: "open", text: "S01-04 doesn't say how it begins. S01-03 ends: \"She puts the cup down.\".", suggestion: "Use that as how this shot begins.", apply: { opening_state: "She puts the cup down." } },
  { id: "f4", kind: "prop", shot: "S01-04", other: "", severity: "note", status: "noted", text: "The letter is in S01-03 but not listed in S01-04.", suggestion: "Add it to the next shot's props." }] } as never;
const shotCard = (id: string, scene: number, index: number, title: string, framing: string, duration: number, chars: string[], over: Record<string, unknown> = {}) => ({ id, scene, index, title, status: "draft", edited: false, story_purpose: title,
  camera: { framing, angle: "eye level", position: "", lens: "", movement: "locked off", focus: "", why: "" }, locks: { storyboard: false, keyframe: false }, duration, characters: chars, has_dialogue: chars.length > 0, environment: "Kitchen", ...over });
const shotsView = { title: "Last Train", story_version: 2, seconds: 21.5, scenes: [{ number: 1, shots: 4, seconds: 14.5 }, { number: 2, shots: 2, seconds: 7 }],
  shots: [shotCard("S01-01", 1, 1, "Show where we are: Kitchen (INT, Morning).", "wide", 4, []), shotCard("S01-02", 1, 2, "Sarah speaks to John.", "over the shoulder", 4.5, ["SARAH", "JOHN"], { locks: { storyboard: true, keyframe: false } }),
    shotCard("S01-03", 1, 3, "John speaks to Sarah.", "over the shoulder", 3, ["JOHN", "SARAH"]), shotCard("S01-04", 1, 4, "A detail that matters: letter.", "insert", 3, []),
    shotCard("S02-01", 2, 1, "Show where we are: Platform (EXT, Night).", "establishing", 4, []), shotCard("S02-02", 2, 2, "Sarah speaks.", "close-up", 3, ["SARAH"])],
  enums: { framing: ["establishing", "wide", "medium", "close-up", "extreme close-up", "over the shoulder", "point of view", "insert"], angle: ["eye level", "low", "high", "dutch", "overhead"], lens: ["wide (24mm)", "normal (35mm)", "portrait (50mm)", "telephoto (85mm+)", "macro"],
    movement: ["locked off", "push in", "pull out", "pan", "tilt", "dolly", "tracking", "orbit", "crane", "handheld", "rack focus", "subject tracking"], focus: ["deep", "shallow", "rack", "follow"] , dof: ["very shallow", "shallow", "medium", "deep"] }, cut_max: 2 };
const shotContract = { id: "S01-02", scene: 1, index: 2, story_version: 2, title: "Sarah speaks to John", status: "draft", edited: true, story_purpose: "Sarah lets slip that she is waiting for a call, and John does not notice.", action: "",
  dialogue: [{ speaker: "SARAH", line: "He said he would call.", paren: "quietly" }], characters: [{ name: "SARAH", character_id: "c_sarah", state_id: "s1", wardrobe_id: null }, { name: "JOHN", character_id: "c_john", state_id: "s1", wardrobe_id: null }],
  environment: { id: "e_kitchen", name: "Kitchen", state_id: "s1" }, props: [], blocking: "Sarah at the sink, John at the table behind her, looking at his phone.",
  performance: { emotional_intention: "Held-back dread", beats: [{ character: "Sarah", what: "Holds the cup too tightly", want: "He calls", need: "To accept he will not", fear: "Being alone", hiding: "That she has packed", subtext: "Stay", start: "Hopeful", turn: "Doubt", end: "Resolve" }], micro_animation: "A slow breath, a swallow before she speaks." },
  camera: { framing: "over the shoulder", angle: "eye level", position: "Behind John's left shoulder, on Sarah", lens: "portrait (50mm)", movement: "locked off", focus: "shallow", why: "Her face is where the story is." }, lighting: { description: "Low morning light through the window over the sink", time: "Morning", why: "Soft light makes the dread quieter." },
  opening_state: "Sarah holds the cup with both hands.", closing_state: "She puts the cup down.", continuity: "Ring on her left hand. Letter by the sink.", reference_assets: [], sound: "Kettle ticking as it cools.", generation: { duration: 4.5, aspect: "", notes: "" }, locks: { storyboard: true, keyframe: false } };
const shotSuggestion = { camera: { framing: "over the shoulder", angle: "low", position: "", lens: "portrait (50mm)", movement: "handheld", focus: "shallow", why: "Tension is felt up close: a tight frame, a slightly low angle and a small unsteadiness keep the audience uneasy." }, lighting: { description: "Hard, low-key light from one side; deep shadow on the rest of the face.", why: "Contrast and shadow say something is being held back." }, from: "the feeling of the shot" };

const opt = (job: string, image: string, state = "ready", model = "Nano Banana") => ({ job, image, state, model, provider: "kie", created: 1, ok: state === "ready" });
const mkShot = (id: string, scene: number, title: string, framing: string, d: number, sb: string | null, kf: string | null, lockedSb = false, lockedKf = false, takes: unknown[] = []) => ({ id, scene, title, duration: d, framing,
  storyboard: { options: sb ? [opt(id + "a", sb), opt(id + "b", "s2.png")] : [], chosen: sb, locked: lockedSb }, keyframe: { options: kf ? [opt(id + "k", kf)] : [], chosen: kf, locked: lockedKf }, video: { takes, approved: null } });
const makeStatus = { render_dir: DIR, active: 1, synced: true, soundtrack: { kind: "silence" }, counts: { shots: 6, storyboard: 4, keyframe: 2, video: 1 },
  shots: [mkShot("S01-01", 1, "Show where we are: Kitchen", "wide", 4, "s1.png", "s1.png", true, true, [{ job: "v1", video: null, state: "ready", model: "Seedance", provider: "kie", created: 1, approved: true, ok: false }]),
    mkShot("S01-02", 1, "Sarah speaks to John", "over the shoulder", 4.5, "s3.png", "s3.png", true), mkShot("S01-03", 1, "John speaks to Sarah", "over the shoulder", 3, "s4.png", null),
    mkShot("S01-04", 1, "A detail that matters: letter", "insert", 3, "s5.png", null), mkShot("S02-01", 2, "Show where we are: Platform", "establishing", 4, null, null), mkShot("S02-02", 2, "Sarah speaks", "close-up", 3, null, null)] };

// ---------------------------------------------------------------- the made-up backend
mockWindows("main");
mockIPC((cmd, a) => {
  const x = (a ?? {}) as { action?: string; data?: Record<string, unknown> };
  switch (cmd) {
    case "film_worldlock":
      switch (x.action) {
        case "list": if (scene === "directorcam") return dcWlList; return { sets: [{ id: set3d.set.id, name: set3d.set.name, version: set3d.set.version, locked: false, assets: 0, cameras: set3d.set.cameras.length, updated: now }], limits: { sets: 40, assets: 200, cameras: 30, events: 200 } };
        case "get": if (scene === "directorcam") return x.data && "set" in x.data ? dcWlGet : { shots: [] }; return x.data && "set" in x.data ? set3d.set : { shots: [] };
        case "views3d": return set3d.views;
        case "collisions": return set3d.collisions;
        default: return set3d.set;
      }
    case "film_shots": return { shots: [] };
    case "film_vp": return vpGet;
    case "film_vpvideo": return { ffmpeg: true, formats: ["png", "prores", "webm"] };
    case "film_directorcam":
      switch (x.action) {
        case "plans": return dcPlans;
        case "plan_get": return dcPlan;
        case "preview": return dcPreview;
        default: return dcPlan;
      }
    case "film_blender": return { found: false, path: "", version: "", note: "Blender was not found. It is optional: FilmCrafter draws 3D sets without it." };
    case "agent_studio": return { version: 1, paused: false, current: "direction", updated: now,
      brief: { story: "A young man faces the memories he has avoided and chooses to come home.", style: "Cinematic storybook", duration: "3–4 minutes", aspect: "2.39:1", budget_limit: 30, checkin_mode: "balanced", checkpoints: ["story", "direction", "first_scene", "preview"] },
      stages: ["story", "direction", "storyboard", "first_scene", "scenes", "audio", "preview", "export"].map((id, i) => ({ id, label: ["Story & shot plan", "Cast & visual direction", "Storyboard & keyframes", "First scene preview", "Remaining scenes", "Voices & sound", "Preview cut", "Final review & export"][i], state: i === 0 ? "complete" : i === 1 ? "needs_approval" : "not_started" })),
      approvals: [{ id: "ap1", stage: "story", at: now - 60, asset_versions: ["plan-v1"] }], revisions: [], activity: [{ id: "a1", at: now, kind: "plan", text: "Cast and visual direction are ready to review." }, { id: "a2", at: now - 60, kind: "approval", text: "Story and shot plan approved." }],
      existing: { scenes: 2, shots: 8 }, spending: { actual: 3.33, committed: 0, limit: 30, pricing_known: true }, jobs: { ready: 3, working: 0, failed: 0 },
      inbox: [{ id: "in1", kind: "approval", stage: "direction", title: "Review before FilmCrafter continues", detail: "Cast and visual direction are ready to review.", priority: 1, action: "review" as const }],
      orchestration: { status: "waiting", next_action: "Review the cast and visual direction", blockers: [], active_jobs: 0, evidence: {}, safe_to_continue: true, message: "Waiting for your review. Nothing paid has been submitted." },
      first_scene_proof: { state: "blocked", scene: null, shots: [], requires_cost_review: false, can_start_local: false, blockers: [] } };
    case "director_style": return { current: "ryan-coogler", styles: [
      { id: "ryan-coogler", name: "Ryan Coogler", region: "North America", origin: "USA · grounded, kinetic, community-centred", known_for: "Warm community, intimate faces, mythic scale", palette: ["gold", "deep green"], traits: { camera: "Long moving takes through lived-in places; steady close-ups for feeling.", light: "Warm natural light on skin and golden-hour exteriors.", editing: "Cut for the emotional beat.", movement: "Grounded physical action.", design: "Culturally specific places and wardrobe." } },
      { id: "christopher-nolan", name: "Christopher Nolan", region: "North America", origin: "UK and USA · large-format practical spectacle", known_for: "Large-format scale and temporal precision", palette: ["steel blue", "amber"], traits: { camera: "Large-format wides, controlled dolly movement and deep staging.", light: "Hard directional daylight and strong practical sources.", editing: "Parallel action converges with exact timing.", movement: "Physical weight and purpose." } },
      { id: "kemi-adetiba", name: "Kemi Adetiba", region: "Africa", origin: "Nigeria · bold glamour and forceful drama", known_for: "Commanding portraits, glamour and dramatic power", palette: ["gold", "black"], traits: { camera: "Low heroic angles and polished close-ups.", light: "Warm skin, strong rim light and jewel-toned interiors." } }
    ] };
    case "stylebible": { if (x.action === "set_shot_options") { const d = x.data as { shot: string; keep_cast: boolean }; if (d.keep_cast) sbKeep[d.shot] = true; else delete sbKeep[d.shot]; }
      if (x.action === "set_shot") { const d = x.data as { shot: string; style: string | null }; if (d.style) sbShots[d.shot] = d.style; else delete sbShots[d.shot]; } return sbRead(); }
    case "film_choreography": return x.action === "types" ? { types: [{ id: "fight", label: "Fist fight", blurb: "Two people, no weapons.", needs_b: true, good_for: "Close, handheld shots." }, { id: "chase", label: "Foot chase", blurb: "One runs, one follows.", needs_b: true, good_for: "Tracking shots." }], outcomes: [{ id: "a_wins", label: "The first side wins" }, { id: "draw", label: "Neither wins" }], intensity: [{ id: "grounded", label: "Grounded" }, { id: "heightened", label: "Heightened" }], limits: { min_beats: 4, max_beats: 14 }, advice: [] }
      : x.action === "list" ? { plans: [] }
      : { id: "ch-demo0001", type: "fight", scene: 1, place: "Platform", weapon: "", sides: { a: ["Sarah"], b: ["John"] }, intensity: "grounded", outcome: "a_wins", geography: "Sarah enters screen-left and John screen-right and they stay that way. Cross the line only on a cutaway.", people: ["Sarah", "John"], seconds: 12.5, warnings: ["Contact is cut around on purpose: the blow and the landing are separate shots."], after: "S01-02", applied: [], status: "draft",
          beats: [{ n: 1, phase: "establish", kind: "establish", actor: null, momentum: "even", text: "Platform: Sarah and John, a few paces apart.", seconds: 4, framing: "establishing", movement: "locked off", angle: "eye level", lens: "wide (24mm)", sound: "wind, distance", title: "Fist fight 1/4", carrying: "" },
                  { n: 2, phase: "strike", kind: "action", actor: "Sarah", momentum: "A", text: "Sarah throws a heavy right hand at John's jaw", seconds: 3, framing: "medium", movement: "handheld", angle: "eye level", lens: "normal (35mm)", sound: "a dull thud", title: "Fist fight 2/4", carrying: "" },
                  { n: 3, phase: "land", kind: "reaction", actor: "John", momentum: "A", text: "John's head snaps to the side and he staggers a step (Carrying: John has a split lip.)", seconds: 2.5, framing: "close-up", movement: "handheld", angle: "eye level", lens: "portrait (50mm)", sound: "a grunt", title: "Fist fight 3/4", carrying: "John has a split lip" },
                  { n: 4, phase: "aftermath", kind: "aftermath", actor: "Sarah", momentum: "A", text: "Sarah stands over John, breathing hard; it is over", seconds: 3, framing: "wide", movement: "pull out", angle: "high", lens: "wide (24mm)", sound: "silence settling", title: "Fist fight 4/4", carrying: "" }] };
    case "film_placecare": return { places: [{ id: "e_playground", name: "Lincoln Middle School - Playground - Day", scenes: [1, 5], has_description: false, has_layout: false, has_picture: false, missing: true }, { id: "e_hall", name: "Hallway", scenes: [2], has_description: true, has_layout: false, has_picture: false, missing: false }], missing: ["e_playground"], filled: x.action === "draft" ? [{ id: "e_playground", name: "Lincoln Middle School - Playground - Day", description: "From the story: ..." }] : undefined, note: "" };
    case "film_readiness": { const r = { shots: 8, ready: false, unread: [], note: "This only reads the film. Anything that costs money shows its price first, in the place where it is made.", counts: { fix: 1, look: 3, note: 1 },
      items: [{ step: "fix", level: "fix", what: "S03-01 lasts 2.0 s but its dialogue needs about 4.5 s.", why: "People speak at about 2.5 words a second, with a breath either side; a shorter shot means the voice is cut off or hurried.", go: "shots", shot: "S03-01", fix: { kind: "shot_seconds", shot: "S03-01", seconds: 4.5, was: 2, label: "Lengthen S03-01 to 4.5 s" } },
        { step: "voices", level: "look", what: "2 lines still need a voice, in 1 shot.", why: "Record each line, or speak it with the person's voice; the price is shown before anything is spent.", go: "voice", shot: "S03-01", fix: null },
        { step: "keyframes", level: "look", what: "8 shots have no keyframe.", why: "A keyframe fixes the look of a shot before the video is made, so a poor one is cheap to replace.", go: "make", shot: "S01-01", fix: null },
        { step: "video", level: "look", what: "8 shots have no video yet.", why: "Making video is paid. Open Make: the price of the batch is shown first, and nothing is made until you confirm.", go: "make", shot: "S01-01", fix: null },
        { step: "voices", level: "note", what: "1 voice-over shot is not set to silent on screen.", why: "Nobody on screen speaks a voice-over, so the picture can be made without lip-sync. The Sound plan sets it in one click.", go: "soundplan", shot: "S01-02", fix: null }] }; return { ...r, next: r.items[0] }; }
    case "film_audioplan": return { video_cost: { usd: 9.6, usd_known: 9.6, unknown: 0, shots: 3, lipsync_shots: 1, model: "Seedance 2.0" }, tier: "draft", model: "Seedance 2.0", model_known: true, model_takes_recording: true, model_makes_sound: true, native_scene: false, counts: { voice_over: 2, needs_voice: 1, audio_in: 1, none: 4 }, lines_to_speak: 2, tts_credits: 140, tts_unpriced: 0, keep_rate: 0.6, tries: 1.67, note: "The route is what the film does today by its existing rules. Nothing here makes or buys anything; the only thing Apply changes is the shot's own on or off setting for who speaks on screen.",
      shots: [{ shot: "S03-01", scene: 3, title: "The hall", seconds: 6, route: "needs_voice", why: "Somebody on screen speaks and a line has no voice yet: record it, or speak it with the character's voice (the price is shown first).", warnings: [], setting: "auto", recommended_setting: "auto", differs: false, speakers: ["Sarah", "John"], timing: { lead: 0.5, tail: 0, end: 6.1, over: 0.6, segments: [{ speaker: "Sarah", start: -0.5, seconds: 2.4, estimated: false, file: null }, { speaker: "John", start: 2.15, seconds: 3.95, estimated: true, file: null }] }, lines: [{ speaker: "Sarah", line: "He said he would call.", voice_over: false, has_voice: false, source: "" }, { speaker: "John", line: "Did you say something?", voice_over: false, has_voice: false, source: "" }] },
        { shot: "S01-02", scene: 1, title: "Tea", seconds: 4, route: "voice_over", why: "A voice-over: nobody on screen is speaking. The picture is made silent with no lip-sync, and the voice is mixed in when the film is exported.", warnings: [], setting: "auto", recommended_setting: "off", differs: true, speakers: [], timing: { lead: 0, tail: 1, end: 3.1, over: 0, segments: [{ speaker: "Sarah", start: 0, seconds: 3.1, estimated: false, file: null }] }, lines: [{ speaker: "Sarah", line: "I remember that night.", voice_over: true, has_voice: true, source: "recorded" }] }] };
    case "film_pacing": return { film: { shots: 8, seconds: 31.5, asl: 3.9, shortest: 1.2, longest: 7 }, scenes: [{ number: 1, shots: 5, seconds: 21, asl: 4.2, shortest: 2, longest: 7, bars: [{ id: "S01-01", seconds: 4 }, { id: "S01-02", seconds: 7 }, { id: "S01-03", seconds: 3 }, { id: "S01-04", seconds: 5 }, { id: "S01-05", seconds: 2 }] }, { number: 2, shots: 3, seconds: 10.5, asl: 3.5, shortest: 1.2, longest: 6, bars: [{ id: "S02-01", seconds: 3.3 }, { id: "S02-02", seconds: 1.2 }, { id: "S02-03", seconds: 6 }] }],
      findings: [{ level: "fix", shot: "S01-03", scene: 1, what: "S01-03 lasts 3.0 s but its dialogue needs about 5.8 s.", why: "People speak at about 2.5 words a second, with a breath either side; a shorter shot means the voice is cut off or hurried.", tip: "Lengthen the shot to 5.8 s, or cut the line." }, { level: "note", shot: "S02-01", scene: 2, what: "Scene 2 does not open on a wide shot.", why: "A wide first shot tells the audience where they are.", tip: "Make the first shot wide or establishing." }], counts: { fix: 1, look: 0, note: 1 }, note: "Advice only." };
    case "film_composition": return x.action === "set" ? { in_prompt: true } : { size: "close", shot: "S01-02", in_prompt: true, horizon: null, grid: [0.333, 0.667], text: "", points: [{ name: "Sarah", x: 0.333, y: 0.333 }],
      lines: [{ text: "The eyes sit on the upper third line, with just enough headroom.", why: "A close-up is about the eyes." }, { text: "Leave look room on the right, in front of the face.", why: "Space in front of a face lets the thought go somewhere." }] };
    case "confirm_spend": return "docshot-token";
    case "plugin:dialog|open": return ["C:/boards/storyboard"];
    case "library": if (x.action === "library") return { items: [
        { id: "c1", kind: "character", name: "Sege", files: ["s1.png", "s2.png"], notes: "Mid-thirties, linen shirt, bracelet", sheet: true }, { id: "c2", kind: "character", name: "Amara", files: ["s3.png"], sheet: true },
        { id: "s1", kind: "set", name: "Kitchen, morning", files: ["s4.png"], notes: "Warm light, radio on" }, { id: "s2", kind: "set", name: "Night train platform", files: ["s5.png"] },
        { id: "p1", kind: "prop", name: "Red toy car", files: ["s6.png"] }, { id: "st1", kind: "style", name: "Painterly warm", files: ["s2.png"] }],
        assign: { project: ["c1", "st1"], scenes: { "2": { add: ["s1"] } }, shots: {} } };
      if (x.action === "bible") return { world: "", tone: "", rules: "", avoid: "" };
      if (x.action === "storyboard") return { plan: "p", shots: ids.map((id, i) => ({ id, scene: N > 8 ? Number(id.slice(1, 3)) : 1, start: i * 6, end: i * 6 + 5, beat: "", performers: [], status: "ready", locked: false, approved: null, thumb_src: `t${i}.png`, thumb_source: "keyframe", preview: null, keyframe: still(i), versions: [], references: [] })), library: { items: [], assign: { project: [], scenes: {}, shots: {} } } }; if (x.action === "thumbs") return Object.fromEntries(((x.data?.srcs as string[]) ?? []).map((s, i) => [s, still(i + s.length)])); return null;
    case "list_styles": return styles.styles;
    case "direction_library":
      if (x.action === "list") return { directions, current: "hayao-miyazaki" };
      if (x.action === "match") return { matches: ["hayao-miyazaki", "isao-takahata", "hirokazu-kore-eda", "pete-docter", "agnes-varda", "satyajit-ray"].map((id, i) => ({ id, score: 1, why: i < 3 ? ["genre: drama", "mood: tender", "low energy"] : [] })), story: { energy: "low", moods: ["tender", "family"], genres: ["drama", "coming-of-age"], words: 900 } };
      return null;
    case "supervisor": return { items: [
      { id: "i1", shot: "S01-02", source: "keyframe check", severity: "major", title: "Fused hands", detail: "The held hands are fused into one mass; the fingers can't be told apart.", fix: "Redraw with the hands apart and five fingers each.", kind: "image", render: null, actions: ["fix", "regenerate", "accept", "ignore"], status: "open" },
      { id: "i2", shot: "S02-02", source: "take review", severity: "minor", title: "Soft left hand", detail: "The left hand is soft and slightly out of focus.", fix: "", kind: "video", render: null, actions: ["regenerate", "accept", "ignore"], status: "open" },
      { id: "i4", shot: "S01-02", source: "keyframe check", severity: "minor", title: "Extra finger on the left hand", detail: "A sixth finger shows on the hand holding the cup.", fix: "", kind: "image", render: null, actions: ["regenerate", "accept", "ignore"], status: "open" },
      { id: "i5", shot: "S02-03", source: "continuity", severity: "minor", title: "Jump cut", detail: "The camera barely moves between this shot and the one before.", fix: "", kind: "video", render: null, actions: ["fix", "accept", "ignore"], status: "open" },
      { id: "i3", shot: "S01-04", source: "continuity", severity: "info", title: "Jacket colour changes", detail: "The jacket is blue here and green in the shot before.", fix: "", kind: "image", render: null, actions: ["accept", "ignore"], status: "open" }],
      groups: [{ id: "g1", scene: "2", title: "Continuity: jump cut", kind: "video", action: "fix", items: ["i5", "i2"], shots: ["S02-02", "S02-03"], render: null }], summary: { open: 5, major: 1, minor: 3, info: 1, decided: 2, ready: false } };
    case "director_audit": return x.action === "audit" ? { planned: 70, directed: 76, ok: false, drops: [], uncovered: [], merges: [
      { shot: "S01-02", scene: 1, start: 13, end: 15, duration: 2, check: true, risks: ["different people are the focus of each beat", "two separate lyric or dialogue lines fall in one shot (only one can be lip-synced)"], note: "All scripted beats are preserved in order; the final match cut also carries the aftermath so the scene lands without an extra cut.",
        sources: [{ id: "S01-02", cue: ["Survival instinct"], people: ["Amara", "Sege"], description: "Wide establishing shot of the warm kitchen with Amara preparing tea. Then: close-up of Amara smiling at Sege." }, { id: "S01-03", cue: [], people: ["Sege"], description: "Over Sege's shoulder as his imaginary duplicate packs behind him." }] },
      { shot: "S01-05", scene: 1, start: 27, end: 29, duration: 2, check: false, risks: ["each of the 2 actions gets under 2 seconds"], note: "", sources: [{ id: "S01-05", cue: [], people: [], description: "Rapid push into the dark childhood corridor." }, { id: "S01-06", cue: [], people: ["Young Sege"], description: "Low medium shot of Young Sege sitting with the red toy car." }] },
      { shot: "S02-01", scene: 2, start: 31, end: 33, duration: 2, check: false, risks: [], note: "", sources: [{ id: "S02-01", cue: [], people: ["Sege"], description: "Intimate profile of their kiss." }, { id: "S02-02", cue: [], people: ["Amara"], description: "Close-up of Amara laughing gently." }] }] } : null;
    case "review_backlog": return { unchecked: 0 };
    case "lipsync_check": return { shots: 0 };
    case "performance_director": return pdCall(x);
    case "grading": return gdCall(x);
    case "editing": return cutCall(x);
    case "smart_editor": return smartCall(x);
    case "presets": return presetCall(x);
    case "layer_kit": return layerKitCall(x);
    case "series": return seriesCall(x);
    case "proxies": return { rows: [], big: 2, ready: x.action === "build" ? 2 : 0, bytes: 0, ...(x.action === "build" ? { made: 2 } : {}), ...(x.action === "clear" ? { removed: 2 } : {}) };
    case "acting": if (x.action === "beats_get") return { beats: [{ t0: 0, t1: 2.5, what: "Sarah holds the cup with both hands", note: "" }, { t0: 2.5, t1: 4.2, what: "She sets it down without looking at him", note: "" }], seconds: 4.2, source: "written" }; return { arc: { sections: ["verse", "chorus", "bridge"], characters: ["Sege", "Amara"], arcs: { Sege: { points: [], source: null }, Amara: { points: [], source: null } } }, business: { Sege: [], Amara: [] } };
    case "performance": return { profiles: [{ id: "natural", label: "Natural", blurb: "Truthful, everyday acting. Small motivated gestures; the default." }, { id: "restrained", label: "Restrained", blurb: "Held back, internal. Emotion shows in the eyes and breath, not the face." }, { id: "expressive", label: "Expressive", blurb: "Open and readable. Clear faces and gestures, still grounded." }, { id: "dramatic", label: "Dramatic", blurb: "Heightened, cinematic. Big emotional beats, strong poses, held moments." }, { id: "energetic", label: "Energetic", blurb: "High energy for up-tempo songs: movement, rhythm, performance to camera." }], default: "dramatic", set: true, scenes: {}, characters: {}, shots: {} };
    case "list_projects":
      if (new URLSearchParams(location.search).get("many")) return Array.from({ length: 60 }, (_, i) => ({ dir: `m${i}`, title: `Film number ${i + 1}`, kind: "film", state: "Screenplay", aspect: i % 2 ? "9:16" : "16:9", modified: now - 3600 * i }));
      if (new URLSearchParams(location.search).get("none")) return [];
      return [
      { dir: "f1", title: "Last Train", kind: "film", state: "Story locked", aspect: "9:16", thumb: "/src/docshots/img/s3.png", modified: now },
      { dir: "f2", title: "The Lighthouse Keeper", kind: "film", state: "Story: idea", aspect: "16:9", modified: now - 86400 * 2 },
      { dir: "p1", title: "Exit Plan", state: "directed", modified: now - 86400 * 9, song: "song.wav" }];
    case "hidden_count": return 0;
    case "providers": return { providers: [{ provider: "kie", name: "Kie.ai", connected: true, families: ["seedream"], verified: [] }], comfyui: { url: "http://127.0.0.1:8188", connected: false, workflows: [] } };
    case "film_voice": return { people: 2, recorded: 2, lines: [], voices: [] };
    case "film_cues": return { cues: [{ id: "c1" }], approved: 0 };
    case "film_audio": return { assets: [] };
    case "video_finish": {
      const act = (a as { action?: string }).action;
      const rep = (level: string, score: number) => ({ frames: 240, level, confidence: "high", global: 0.6, local: 1.1, score, note: level === "Calm" ? "Brightness is steady from frame to frame." : "Brightness pulses a little between frames." });
      if (act === "videos") return { videos: [{ ref: "project:exports/Last Train - YouTube.mp4", name: "Last Train - YouTube.mp4", bytes: 48e6, at: 1 }] };
      if (act === "presets") return { looks: [{ id: "none", label: "No look", note: "Colour and grain stay as they are." }, { id: "clean", label: "Clean", note: "A touch of contrast and a gentle noise clean-up." }, { id: "film", label: "Film", note: "Warmer shadows and fine grain." }], profiles: [{ id: "web", label: "Web (H.264)", note: "Plays everywhere.", ext: "mp4" }, { id: "master", label: "Master (H.264, high quality)", note: "Large; for editing.", ext: "mp4" }], strengths: ["gentle", "balanced", "strong"] };
      if (act === "flicker") return { ref: "project:exports/Last Train - YouTube.mp4", report: rep("Some", 4.1), limits: "Measures brightness only; it does not judge colour shifts or how things move." };
      if (act === "restore") return { id: "r1", source: "project:exports/Last Train - YouTube.mp4", output: "project:restore/r1.mp4", output_path: "C:/Films/Last Train/restore/r1.mp4", strength: "balanced", before: rep("Some", 4.1), after: rep("Calm", 0.7), gain: 3.4, better: true, note: "Calmer. The original is untouched." };
      return { id: "f1", source: "project:exports/Last Train - YouTube.mp4", output: "project:finish/f1.mp4", output_path: "C:/Films/Last Train/finish/f1.mp4", look: "clean", profile: "web", bytes: 41e6, source_bytes: 48e6 };
    }
    case "fidelity": {
      const act = (a as { action?: string }).action;
      const rep = { width: 1536, height: 1024, aspect: "3:2", format: "PNG", analysed_at: "1536×1024", reduced: false, verdict: "optional", action: "Optional: Clean Enhance can tidy this up.", low_resolution: false, not_assessed: ["Faces and hands (needs an image model)", "Whether the picture suits the story"],
        rows: [{ id: "sharpness", label: "Sharpness", level: "Moderate", value: 0.24, confidence: "high", note: "The sharpest parts are only gently defined.", depth_of_field: false }, { id: "noise", label: "Noise", level: "Low", value: 0.8, confidence: "high", note: "Clean." }, { id: "blockiness", label: "Compression blocks", level: "Unknown", value: null, confidence: "low", note: "Too little detail to tell." }] };
      if (act === "upscale_status") return { available: false, help: "Real-ESRGAN is not installed. Install realesrgan-ncnn-vulkan and set FILMCRAFTER_REALESRGAN, or put it in engine/tools/realesrgan." };
      if (act === "masters") return { masters: {} };
      return { shot: "S01-04", ref: "project:keyframes/S01-04.png", report: rep };
    }
    case "export_project": { const v = (a as { preset?: string }).preset === "vertical"; const dr = (a as { dir?: string }).dir === "f-draft"; return { path: v ? "C:/Films/Last Train/exports/Last Train - TikTok - 2026-11-05 1010.mp4" : "C:/Films/Last Train/exports/Last Train - YouTube - 2026-11-05 1009.mp4", preset: v ? "TikTok / Reels 9:16" : "YouTube 16:9", width: v ? 1080 : 1920, height: v ? 1920 : 1080, fps: 24, duration: 144.5, shots: 6, rendered: 6, draft: dr, loudness: null, check: null, overlays: 0, captions: 0, subtitles: null }; }
    case "golden": return { video: ["S01-01", "S01-02"], still: [], none: [], stale: [] };
    case "key_status": return { openai: true, fal: true, kie: true, google: false, elevenlabs: false, midjourney: false, byteplus: false };
    case "engine_status": return { ready: true, gpu: false, dev: true, python: "" };
    case "film_bible": return bibleView;
    case "model_registry": return x.action === "in_use" ? { models: [], warnings: [] } : x.action === "refresh" ? { results: { elevenlabs: { ok: true, models: 6 }, kie: { ok: false, error: "no network" } }, kept: "Anything that could not be refreshed keeps what it had." }
      : { models: 32, providers: { elevenlabs: { refreshed: now - 86400, stale: false, last_error: null }, kie: { refreshed: null, stale: true, last_error: null }, openrouter: { refreshed: null, stale: true, last_error: null } }, note: "" };
    case "film_outdated": return { takes: [{ shot: "S01-03", take: "v1", kind: "voice_changed", why: "The voice was replaced after this take was made, so the mouth may not match it.", speakers: ["Lila"], kept: false, options: ["lipsync_pass", "new_take"], note: "" }], cues: [], film: null, unchecked_takes: 2, clean: false };
    case "film_mix": {
      if (x.action === "preview") return { file: "cache/audio-preview/scene1.wav", seconds: 14.5, cues: 1, skipped: [], ducked: true, solo: (x.data as { solo?: string } | undefined)?.solo ?? null, voices: true };
      return { schema: 1, ducking_db: -12, duck_attack: 0.15, duck_release: 0.6, target_lufs: null, peak_db: -1, mute_lanes: [], solo: null };
    }
    case "film_audiogen": {
      if (x.action === "providers") return { providers: [{ id: "elevenlabs_sfx", label: "ElevenLabs sound effects", kind: "sfx", cost_known: true, cost_words: "about 11 credits per second you ask for", duration: [0.5, 30], loop: true, instrumental: false, has_key: true, rights: "not_established", rights_note: "Commercial rights for sound made this way were not established.", checked: "2026-10-14" },
        { id: "elevenlabs_music", label: "ElevenLabs Music", kind: "music", cost_known: false, cost_words: "ElevenLabs does not publish what a piece of music uses of your plan", duration: [3, 600], loop: false, instrumental: true, has_key: true, rights: "not_established", rights_note: "Commercial rights for sound made this way were not established.", checked: "2026-10-14" }] };
      if (x.action === "estimate") return { provider: "elevenlabs_sfx", label: "ElevenLabs sound effects", kind: "sfx", key: "k", cached: null, unit: "elevenlabs_credits", amount: 22, basis: "about 11 credits per second x 2 s (an estimate)", cost_known: true, needs_unknown_cost_accepted: false, needs_rights_ack: true, rights_note: "Commercial rights for sound made this way were not established.", has_key: true };
      if (x.action === "pending") return { tasks: [] };
      return { assets: [], blocking: [], ok: true };
    }
    case "film_cues": {
      const base = { cues: [{ id: "q-1a2b3c4d", kind: "ambience", asset_id: "a-sfx-1a2b3c4d", asset_name: "Rain on the roof", asset_file: "audio/sfx/a-sfx-1a2b3c4d.wav", asset_seconds: 42.5, scene: 1, shot: null, start: 0, duration: null, gain_db: -14, fade_in: 1, fade_out: 2,
          loop: true, ducking: "auto", approval: "approved", note: "", source: "manual", fresh: [], needs_sound: false, created: now, updated: now },
        { id: "q-5e6f7a8b", kind: "sfx", asset_id: null, asset_name: null, asset_file: null, asset_seconds: null, plan: { description: "A kettle clicking off", search: "kettle" }, scene: 1, shot: "S01-02", start: 1.2, duration: null, gain_db: 0, fade_in: 0, fade_out: 0,
          loop: false, ducking: "auto", approval: "approved", note: "", source: "quick", fresh: [], needs_sound: true, created: now, updated: now }],
        dialogue: [{ id: "voice:S01-02:lila", kind: "dialogue", derived: true, scene: 1, shot: "S01-02", speaker: "Lila", file: "voice/lila.wav", duration: 3.4, start: 0, source: "recording", text: "It looked weird." }], removed: [],
        scenes: { "1": { seconds: 14.5, shots: [{ id: "S01-01", seconds: 4, sound: "" }, { id: "S01-02", seconds: 4.5, sound: "A kettle clicks off, quietly" }] }, "2": { seconds: 7, shots: [{ id: "S02-01", seconds: 4, sound: "" }] } }, counts: { cues: 2, needs_sound: 1, suggested: 0 } };
      if (x.action === "quick" || x.action === "director_suggest") return { scene: 1, source: x.action === "quick" ? "quick" : "director", ideas: [{ kind: "ambience", what: "Rain falling", why: "The scene mentions rain.", search: "rain", shot: null, loop: true, matches: [{ asset_id: "a-sfx-1a2b3c4d", name: "Rain on the roof", score: 5, why: ["rain"], approved: true, seconds: 42.5 }] },
        { kind: "sfx", what: "Pencil on paper", why: "She draws.", search: "pencil", shot: "S01-02", loop: false, matches: [] }] };
      if (x.action === "director_estimate") return { calls: 1, usd: 0.004, local: false, note: "", sends: "this scene's shots" };
      return base;
    }
    case "film_voice_direct": {
      if (x.action === "scene_plan") return { scene: 1, speakers: [{ name: "Lila", key: "lila", voice: "Warm Northern Woman", has_voice: true, approved: false, lines: 2 }, { name: "Chloe", key: "chloe", voice: null, has_voice: false, approved: false, lines: 1 }],
        lines: [{ shot: "S01-02", speaker: "Lila", key: "lila", text: "It looked weird.", written: "It looked weird.", spoken_version: false, state: "missing", seconds: null, characters: 16, credits: 16, cached: false },
          { shot: "S01-03", speaker: "Chloe", key: "chloe", text: "I know.", written: "I know.", spoken_version: false, state: "no_voice", seconds: null }], missing: 1, no_voice: ["Chloe"], estimate: { characters: 16, credits: 16, basis: "" } };
      if (x.action === "table_read") return { scene: 1, lines: [{ shot: "S01-02", speaker: "Lila", key: "lila", text: "It looked weird.", file: null, seconds: null, source: null }], seconds: 0, silent: 1 };
      if (x.action === "performance") return { lines: [] };
      return {};
    }
    case "film_audio": {
      const a = (id: string, kind: string, name: string, category: string, seconds: number, approval: string, extra: Record<string, unknown> = {}) => ({ id, kind, name, description: "", category, file: `audio/${kind}/${id}.wav`, original_name: `${name}.wav`, sha1: id, bytes: 1000, seconds, source: "imported",
        tags: [], places: [], props: [], characters: [], scenes: [], shots: [], genre: "", mood: "", tempo: "", generation: {}, licence: { source: "", note: "", commercial: "unknown" }, approval, added: now, updated: now, exists: true, ...extra });
      const all = [a("a-sfx-1a2b3c4d", "sfx", "Rain on the roof", "weather", 42.5, "approved", { places: ["Kitchen"], tags: ["rain", "night"] }), a("a-sfx-5e6f7a8b", "sfx", "Kettle click", "foley", 1.4, "pending", { props: ["Kettle"] }),
        a("a-music-9c0d1e2f", "music", "Lila's music box", "theme", 96, "pending", { genre: "Chamber", mood: "Tender", characters: ["Lila"] })];
      return { assets: all, removed: 0, removed_items: [], categories: { sfx: [{ id: "foley", name: "Foley" }, { id: "ambience", name: "Environmental ambience" }, { id: "weather", name: "Weather" }, { id: "custom", name: "Custom" }], music: [{ id: "score", name: "Background score" }, { id: "theme", name: "Character or recurring theme" }, { id: "custom", name: "Custom" }] }, counts: { sfx: 2, music: 1 } };
    }
    case "film_make": return x.action === "progress" ? { story: { kind: "screenplay", locked: true, as_is: true }, cast: { characters: 2, places: 2, pictures: 2, style: true }, shots: { count: 6, edited: 1 }, make: { shots: 6, storyboard: 4, keyframe: 2, video: 1 } } : N > 8 ? { ...makeStatus, shots: grow(makeStatus.shots as never[]), counts: { ...(makeStatus as { counts: object }).counts, shots: N } } : makeStatus;
    case "film_check": return continuityMock;
    case "film_spending": return { lines: [
      { step: "pictures", label: "Pictures", provider: "kie", unit: "kie_credits", unit_name: "Kie credits", operations: 6, reported: 24, reported_operations: 6, estimated: 0, estimated_operations: 0 },
      { step: "video", label: "Video", provider: "kie", unit: "kie_credits", unit_name: "Kie credits", operations: 2, reported: 328, reported_operations: 2, estimated: 0, estimated_operations: 0 },
      { step: "voices", label: "Voices", provider: "elevenlabs", unit: "elevenlabs_credits", unit_name: "ElevenLabs credits", operations: 4, reported: 9, reported_operations: 3, estimated: 3, estimated_operations: 1 },
      { step: "sound_effects", label: "Sound effects", provider: "elevenlabs", unit: "elevenlabs_credits", unit_name: "ElevenLabs credits", operations: 2, reported: 33, reported_operations: 2, estimated: 0, estimated_operations: 0 }],
      totals: [{ unit: "kie_credits", unit_name: "Kie credits", operations: 8, reported: 352, estimated: 0 }, { unit: "elevenlabs_credits", unit_name: "ElevenLabs credits", operations: 6, reported: 42, estimated: 3 }],
      uncertain: [], limits: { elevenlabs_credits: 150 }, problems: [], operations: 14, note: "Amounts marked reported came from the provider's own reply; estimates are our guess from the published price. Not tracked here: the writing helper (planning with a language model)." };
    case "film_materials": return x.action === "apply" ? { applied: [{ id: "a", type: "storyboard", title: "storyboard/S01-01.png", what: "Panel for S01-01 (also the framing reference for its hero picture)" }], failed: [], skipped: [], changed_since_scan: [], message: "1 added to the film. Nothing was bought or sent anywhere." } : { token: "0123456789ab", problems: ["board.pdf: page 004 has no picture inside it (it is drawn as lines or text). Export those pages as pictures (PNG or JPG) and bring them in as files."], counts: { storyboard: 2, asset: 1, shotrow: 1, note: 1 },
      shots: [{ id: "S01-01", scene: 1, title: "Kitchen" }, { id: "S01-02", scene: 1, title: "Tea" }, { id: "S02-01", scene: 2, title: "Yard" }],
      items: [
        { id: "f1", type: "storyboard", title: "storyboard/S01-01.png", rel: "boards/storyboard/S01-01.png", on: true, blocked: "", notes: [], shot: "S01-01", shot_label: "S01-01 · Kitchen", how: "the file name" },
        { id: "f2", type: "storyboard", title: "storyboard/panel 2.png", rel: "boards/storyboard/panel 2.png", on: false, blocked: "", notes: ["This shot already has a chosen panel. Tick to use this one instead; the old one stays in the film."], shot: "S01-02", shot_label: "S01-02 · Tea", how: "their order", replaces: true },
        { id: "f3", type: "asset", title: "characters/Sarah/front.png", rel: "boards/characters/Sarah/front.png", on: true, blocked: "", notes: [], kind: "character", name: "Sarah", entry: "sarah", entry_name: "Sarah", create: false, media_kind: "front" },
        { id: "f4r1", type: "shotrow", title: "S01-01 · Kitchen", rel: "shots.csv", on: true, blocked: "", notes: [], shot: "S01-01", changes: [{ label: "Framing", old: "wide", new: "close-up" }, { label: "Movement", old: "", new: "push in" }, { label: "Length (s)", old: 3, new: 4 }] },
        { id: "f5", type: "note", title: "tone.md", rel: "notes/tone.md", on: true, blocked: "", notes: [], target: "tone", excerpt: "Warm, patient, handheld. The kitchen is always lit from the window.", length: 64 },
        { id: "f6", type: "unsorted", title: "mystery.png", rel: "boards/mystery.png", on: false, blocked: "Say what this picture is: a storyboard panel, or a picture of a character, a place or a prop.", notes: [] }] };
    case "film_voice": return voiceStatus;
    case "film_voiceid": return x.action === "overview" ? { people: [], flagged: 0 } : x.action === "cast_library" ? { entries: [] } : {};
    case "film_revoice": return { runtime: { model: { id: "chatterbox-vc", name: "Chatterbox voice conversion", licence: "MIT", by: "Resemble AI", packages: [], size_note: "Several gigabytes in total.", needs: "About 8 GB of memory.", status: "experimental" }, installed: false, since: null, versions: null, device: null, folder: "", how: "" }, people: [], conversions: 0 };
    case "film_cast_voice":
      if (x.action === "library") return { voices: [{ voice_id: "AbCdEfGh1234", name: "Warm Northern Woman", category: "premade", description: "Gentle, unhurried", labels: { accent: "british", age: "old" }, preview_url: "" }, { voice_id: "ZyXwVu987654", name: "Bright Girl", category: "premade", description: "", labels: { age: "young" }, preview_url: "" }], next: null };
      if (x.action === "ledger") return { limits: { elevenlabs_credits: 500 }, count: 3, by_unit: { elevenlabs_credits: { operations: 2, estimated: 58, reported: 0, unreported_operations: 2, estimated_unreported: 58 }, voice_slot: { operations: 1, estimated: 1, reported: 0, unreported_operations: 1, estimated_unreported: 1 } },
        unresolved: [{ id: "u1", at: 1790000000, updated: 1790000000, action: "speak", person: "Lila", shot: "S01-03", status: "uncertain", estimate: { unit: "elevenlabs_credits", amount: 29, basis: "" }, actual: { unit: "elevenlabs_credits", amount: null, reported: false, source: null }, note: "" }],
        recent: [{ id: "u1", at: 1790000000, updated: 1790000000, action: "speak", person: "Lila", shot: "S01-03", status: "uncertain", estimate: { unit: "elevenlabs_credits", amount: 29, basis: "" }, actual: { unit: "elevenlabs_credits", amount: null, reported: false, source: null }, note: "" }] };
      if (x.action === "estimate") return { rows: [{ shot: "S01-03", speaker: "Lila", ok: true, characters: 52, credits: 52, cached: false, text: "[tired] Yesterday? It looked like... spiced beans?" }], characters: 52, credits: 52, basis: "" };
      if (x.action === "takes") return { person: "Lila", shot: "S01-03", takes: [
        { file: "voice/_generated/S01-03-b.mp3", text: "[tired] Yesterday? It looked like... spiced beans?", model: "eleven_v4", voice_name: "Warm Northern Woman", at: 1790000200, current: true },
        { file: "voice/_generated/S01-03-a.mp3", text: "Yesterday? It looked like... spiced beans?", model: "eleven_v4", voice_name: "Warm Northern Woman", at: 1790000100, current: false }] };
      return { key: true, models: [{ id: "eleven_v4", label: "Eleven v4 (most expressive: put [laughs], [whispers], [sad]... in the words)" }, { id: "eleven_v4_turbo", label: "Eleven v4 Turbo (expressive, half the credits)" }, { id: "eleven_v3", label: "Eleven v3 (expressive, less steady than v4)" }, { id: "eleven_multilingual_v2", label: "Multilingual v2 (steady, best for long lines; no tags)" }, { id: "eleven_flash_v2_5", label: "Flash v2.5 (fast, half the credits; no tags)" }],
        people: { lila: { name: "Lila", voice_id: "AbCdEfGh1234", voice_name: "Warm Northern Woman", model: "eleven_v4", stability: 0.5, similarity: 0.75, style: 0, speed: 1, made: "library" } },
        plan: { tier: "starter", used: 1200, limit: 30000, left: 28800, can_clone: true, slots_used: 3, slots: 10 }, plan_error: "" };
    case "film_shots": return x.action === "shot" ? { shot: { ...shotContract, plan: blockingPlanMock, ...(/click=Blocking/.test(location.search) ? { locks: { storyboard: false, keyframe: false } } : {}) } } : x.action === "suggest" ? shotSuggestion : x.action === "blocking" ? blockingMock : x.action === "principles" ? { look: "stop-motion", family: "craft", screen_craft: false, picture: [], video: [{ id: "anticipation", name: "Anticipation", plain: "A small opposite move prepares the big one." }, { id: "follow-through", name: "Follow-through and overlapping action", plain: "Loose parts keep going a beat longer." }, { id: "staging", name: "Staging", plain: "One idea reads at once." }, { id: "slow-in-out", name: "Slow in and slow out", plain: "Movements ease in and out." }] } : N > 8 ? { ...shotsView, shots: grow(shotsView.shots as never[]), scenes: Array.from({ length: Math.ceil(N / 8) }, (_, k) => ({ number: k + 1, shots: 8, seconds: 40 })), seconds: N * 5 } : shotsView;
    case "film":
      if (x.action === "read_file") return { name: "last-train.fountain", text: filmText, truncated: false };
      if (x.action === "preview") return { kind: "screenplay", words: 61, scenes: 3, characters: 2, locations: 3, seconds: 144, has_headings: true };
      return filmStatus;
    case "overlays": {
      if ((a as { dir?: string }).dir === MIXDIR) return mixOverlays(x);
      if ((a as { dir?: string }).dir === MIXCLIPDIR) return mixOverlays(x, clipStore);
      return x.action === "list" ? layerList : null;
    }
    case "colour_match": return colourState;
    case "lighting": return lightingPlan;
    case "cleanup": return cleanupScan;
    case "keyframe_set":
      if (x.action === "check_plan") return { flagged: [{ shot: "S01-02", image: "s2.png", state: "fail", locked: false, detail: "The held hands are fused into one mass; the fingers can't be told apart." }, { shot: "S02-02", image: "s3.png", state: "look", locked: false, detail: "The left hand is soft." }], shots: ["S01-01", "S01-04", "S02-02"], already: ["S01-02"], skipped: [], usd_est: 0.06, can_check: true, unavailable: "" };
      if (x.action === "remake_plan") return { shots: ["S01-02"], skipped: [], usd_est: 0.1 };
      if (x.action === "remodel_plan") return { target: { provider: "kie", model: "google/nano-banana-edit", label: "Nano Banana", price_usd: 0.03 }, shots: ["S01-02", "S01-05", "S02-01"], from: [], skipped: [{ shot: "S01-04", reason: "your own picture" }], used: [{ provider: "kie", model: "google/nano-banana-edit", count: 9 }, { provider: "kie", model: "gpt/gpt-image-2-5-flare-image-to-image", count: 3 }], usd_est: 0.75 };
      if (x.action === "swap_status") return { making: 1, ready: 2, failed: 0, shots_ready: [], reasons: {} };
      return null;
    case "frames":
      if (x.action === "get") return { "S01-01": { start: "s1.png", start_mode: "keyframe", end: "s2.png", end_mode: "own", end_state: "She turns to face him, the light behind her.", next: "S01-02", prev: null, next_has_start: false } };
      if (x.action === "support") return { title: "Seedance 2", shots: { "S01-01": { model: "bytedance/seedance-2", swapped: false, supports_end: true, proven: true, end: "project:s2.png" } } };
      if (x.action === "options") return { shots: {}, active: 0 };
      return null;
    case "hand_fix": return x.action === "plan" ? { model: { label: "Nano Banana", price_usd: 0.03 }, variants: 1, usd_est: 0.03 } : null;
    case "retry_cheaper": return { can: true, original_usd: 0.9, options: [
      { provider: "fal", model: "fal-ai/wan/v2.2-a14b/image-to-video/turbo", label: "Wan 2.2 Turbo", price_usd: 0.1, cheaper: true, saves_usd: 0.8, strength: "A cheap, quick Wan; proven to land on an end picture.", warning: "" },
      { provider: "kie", model: "wan/3-0-video", label: "Wan 3.0", price_usd: 0.45, cheaper: true, saves_usd: 0.45, strength: "Low price. FilmCrafter's Balanced video choice.", warning: "" }] };
    case "routing":
      if (x.action === "pick") return (x.data as { kind?: string } | undefined)?.kind === "video" ? { provider: "kie", model: "wan/3-0-video", label: "Wan 3.0", free: false, mode: "balanced", verified: true, price_usd: 0.45 } : { provider: "kie", model: "google/nano-banana-edit", label: "Nano Banana", free: false, mode: "balanced", verified: true, price_usd: 0.03 };
      if (x.action === "models") return { video: [row("Seedance 2", "kie", "bytedance/seedance-2", 0.9, true, { strength: "Takes a start and an end picture, can also use reference pictures, video and sound, and can speak lines.", consider: "For shots that must land on an end frame and shots with sung or spoken lines.", watch: "Costs more per shot." }), row("Wan 3.0", "kie", "wan/3-0-video", 0.45, true, { strength: "Low price. FilmCrafter's Balanced video choice.", consider: "For a whole video on a budget.", watch: "" }), row("Kling", "kie", "kling-2.6/image-to-video", 0.7, true), row("Hailuo 2.3", "fal", "fal-ai/minimax/hailuo-2.3/standard/image-to-video", 0.5, false)],
        image: [row("Nano Banana", "kie", "google/nano-banana-edit", 0.03, true, { sees_references: true }), row("GPT Image 2.5 Flare", "kie", "gpt/gpt-image-2-5-flare-image-to-image", 0.25, true, { sees_references: true, strength: "Follows detailed instructions closely and draws clean, readable text. Sees your character sheets.", consider: "For hero shots and anything with writing in it.", watch: "Costs the most of the picture models." }), row("Seedream 4.5", "kie", "seedream/4-5-edit", 0.06, true, { sees_references: true })], advice: "Use one picture model for the whole project. Two models draw people, light and colour differently, so mixing them across keyframes can make a character look different from shot to shot." };
      return { mode: "balanced", chosen: true, budget_usd: 25, spent_usd: 7.4, remaining_usd: 17.6, online: true, auto_retry: false, pins: {},
        modes: [{ id: "local", label: "Local First", blurb: "Only this computer: ComfyUI, a local AI model, moving stills. Free and works offline." }, { id: "cheapest", label: "Cheapest", blurb: "The lowest real price per shot among proven models." }, { id: "balanced", label: "Balanced", blurb: "The cheapest proven cloud models." }, { id: "premium", label: "Premium", blurb: "The best proven models." }],
        video: { provider: "kie", model: "wan/3-0-video", label: "Wan 3.0", free: false, mode: "balanced", verified: true, price_usd: 0.45 }, image: { provider: "kie", model: "google/nano-banana-edit", label: "Nano Banana", free: false, mode: "balanced", verified: true, price_usd: 0.03 },
        brain: { provider: "openai", local: false }, works_offline: ["Moving stills and your own media", "Export"],
        consistency: { image_models: [{ provider: "kie", model: "google/nano-banana-edit", label: "Nano Banana", count: 9 }, { provider: "kie", model: "gpt/gpt-image-2-5-flare-image-to-image", label: "GPT Image 2.5 Flare", count: 3 }], mixed: true, pinned: false, advice: "" } };
    case "compose": {
      if (x.action === "library_list") return [
        { id: "a1b2c3d4e5", name: "Slow walk", seconds: 8.2, width: 1080, height: 1920, added: now, thumb: null, tags: ["walk", "slow"], path: `${DIR}/v1.mp4` },
        { id: "b2c3d4e5f6", name: "Salsa step", seconds: 12.4, width: 1080, height: 1920, added: now, thumb: null, tags: ["dance"], path: `${DIR}/v2.mp4` },
        { id: "c3d4e5f6a7", name: "Runway turn", seconds: 6, width: 1080, height: 1920, added: now, thumb: null, tags: ["walk", "fashion"], path: `${DIR}/v3.mp4` }];
      if (x.action === "models") return { start_end: [], references: [], motion: [] };
      if (x.action === "state") return { shot: "S01-01", shot_seconds: 6, video: null, video_seconds: null, image: "s1.png", image_is_start: true, orientation: "video", quality: "std", background: "video", note: "", notes: [], ready: false, missing: ["a motion video"], prompt: { mode: "auto", text: "", only: false } };
      return null;
    }
    default: return null;
  }
});

// ---------------------------------------------------------------- the scenes
const noop = () => {};

// a look for one shot: the made-up looks and the one shot that has its own (set in memory, so the select can be tried)
const sbShots: Record<string, string> = scene === "shotlook-own" ? { "S01-04": "anime" } : {};
const sbKeep: Record<string, boolean> = {};

// the Performance Director's made-up film: one scene with two people and a line that may mean more than it says; every edit is kept in memory so the screens can be tried
type PdField = { value: string; source: "auto" | "you"; from: string };
const pdf = (value: string, from = "", source: "auto" | "you" = "auto"): PdField => ({ value, source, from: value ? from : "" });
const pdScenes = [
  { number: 1, heading: "INT. KITCHEN - MORNING", shots: ["S01-01", "S01-02"],
    fields: { purpose: pdf("She cannot ask him to stay.", "the shots' story purposes"), start: pdf("Brittle calm", "shot S01-01"), end: pdf("", ""), tension: pdf("Sarah and John: she wants him to stay and will not say so.", "the cast notes") },
    people: [{ name: "Sarah", wants: pdf("To keep him from leaving", "the story beats of S01-01"), obstacle: pdf("Pride", "the story beats of S01-01"), outward: pdf("", ""), inner: pdf("Afraid he is already gone", "the story beats of S01-01"), hiding: pdf("", "") },
      { name: "John", wants: pdf("", ""), obstacle: pdf("", ""), outward: pdf("", ""), inner: pdf("", ""), hiding: pdf("", "") }],
    subtext: [{ id: "S01-02:0", shot: "S01-02", person: "Sarah", says: "I'm fine.", means: pdf("Sarah may be hiding how they really feel", "the words of shot S01-01"), confidence: "medium" as const,
      why: "The line (\"I'm fine\") is a deflection, and shot S01-01 mentions \"shaking\". This is a reading, not a fact: say what it means." }],
    turning_points: [], nonverbal: [{ shot: "S01-01", what: "Sarah pours tea. Her hands are shaking and she will not look at him." }], reactions: [{ shot: "S01-03", person: "John", what: "listens to Sarah" }] },
  { number: 2, heading: "EXT. PLATFORM - NIGHT", shots: ["S02-01"], fields: { purpose: pdf("Show where we are: Platform.", "the shots' story purposes"), start: pdf(""), end: pdf(""), tension: pdf("") },
    people: [{ name: "John", wants: pdf(""), obstacle: pdf(""), outward: pdf(""), inner: pdf(""), hiding: pdf("") }], subtext: [], turning_points: [], nonverbal: [{ shot: "S02-01", what: "Rain on the roof. John waits alone." }], reactions: [] },
];
const pdProfiles: Record<string, Record<string, string>> = { Sarah: {}, John: {} };
const pdNudges: Record<string, number> = {};
const pdDismissed = new Set<string>();

// Colour Studio's made-up film: grades, LUTs and looks are kept in memory so the sheet can be tried; the preview pictures are two sample stills (the real pictures come from the engine's own filter text)
type GradeMock = Record<string, unknown>;
const gdGrades: { film: GradeMock; scenes: Record<string, GradeMock>; shots: Record<string, GradeMock> } = { film: {}, scenes: {}, shots: {} };
const gdLuts: { id: string; name: string; kind: string; space_in: string; space_out: string; dims: number; size: number; favorite: boolean }[] = [
  { id: "a1b2c3d4e5f60718", name: "Warm afternoon", kind: "creative", space_in: "rec709", space_out: "rec709", dims: 3, size: 33, favorite: true },
  { id: "0f1e2d3c4b5a6978", name: "Log to Rec.709", kind: "technical", space_in: "log", space_out: "rec709", dims: 3, size: 33, favorite: false }];
const gdPresets: { name: string; grade: GradeMock }[] = [];
const gdHistory: { rev: number; at: number; what: string }[] = [];
const gdState = () => ({ revision: gdHistory.length, grades: gdGrades, luts: gdLuts, presets: gdPresets, history: gdHistory, spaces: ["rec709", "srgb", "log", "hdr_pq", "hdr_hlg", "dci_p3", "other"], picture_space: "rec709",
  ranges: { exposure: [-3, 3, 0], brightness: [-1, 1, 0], contrast: [-1, 1, 0], highlights: [-1, 1, 0], shadows: [-1, 1, 0], whites: [-1, 1, 0], blacks: [-1, 1, 0], saturation: [-1, 1, 0], vibrance: [-1, 1, 0], hue: [-180, 180, 0],
    temperature: [-1, 1, 0], tint: [-1, 1, 0], gamma: [-1, 1, 0], lift: [-1, 1, 0], gain: [-1, 1, 0] },
  swing: Object.fromEntries([["film", gdGrades.film], ...Object.entries(gdGrades.scenes).map(([k, g]) => [`scene:${k}`, g]), ...Object.entries(gdGrades.shots).map(([k, g]) => [`shot:${k}`, g])]
    .filter(([, g]) => Object.keys(g as object).length).map(([k, g]) => [k, { clipped_whites: Number((g as GradeMock).exposure ?? 0) > 1.5, crushed_blacks: false }])),
  shots: [{ id: "S01-01", scene: 1, heading: "INT. KITCHEN - MORNING" }, { id: "S01-02", scene: 1, heading: "INT. KITCHEN - MORNING" }, { id: "S02-01", scene: 2, heading: "EXT. PLATFORM - NIGHT" }] });
// The cut's made-up backend: a small stand-in for the engine's editing (whole frames at 24 a second), kept in memory so the timeline's controls can be tried. The real checks are in the engine's own tests.
type CutClipMock = { id: string; shot: string; start: number; source_in: number; duration: number };
type CutMock = { clips: CutClipMock[]; markers: { id: string; at: number; name: string }[]; length: number; locked: boolean };
const FRAME_TICKS = 254_016_000_000 / 24;
const cutStart = (): CutMock => ({ clips: (renderFixture as unknown as { production: { scenes: { shots: { id: string; start: number; end: number }[] }[] } }).production.scenes.flatMap((sc) => sc.shots)
  .map((s, i) => ({ id: `c${i + 1}`, shot: s.id, start: Math.round(s.start * 24), source_in: 0, duration: Math.round(s.end * 24) - Math.round(s.start * 24) })), markers: [], length: Math.round((renderFixture as unknown as { song_map: { duration: number } }).song_map.duration * 24), locked: false });
let cutNow: CutMock = cutStart();
let cutStored = false;
let cutPast: CutMock[] = [];
let cutFuture: CutMock[] = [];
let cutSeq = 100;
const cutView = () => ({
  stored: cutStored, unplaced: [] as string[], orphans: [] as string[], can_undo: cutPast.length > 0, can_redo: cutFuture.length > 0, history: [],
  sequence: { fps: [24, 1], frame_ticks: FRAME_TICKS, ticks_per_second: 254_016_000_000, length: cutNow.length * FRAME_TICKS, length_s: cutNow.length / 24,
    tracks: [{ id: "V1", kind: "video", locked: cutNow.locked, hidden: false, muted: false, clips: cutNow.clips.map((c) => ({ ...c, take: null, start_s: c.start / 24, duration_s: c.duration / 24, source_in_s: c.source_in / 24, start_frame: c.start, frames: c.duration,
      start_t: 0, source_in_t: 0, duration_t: 0 })).map(({ start_t: _a, source_in_t: _b, duration_t: _c, ...c }) => ({ ...c, start: c.start * FRAME_TICKS, source_in: c.source_in * FRAME_TICKS, duration: c.duration * FRAME_TICKS })) }],
    markers: cutNow.markers.map((m) => ({ id: m.id, at: m.at * FRAME_TICKS, at_s: m.at / 24, name: m.name })), ranges: [] } });
const cutCall = (a: { action?: string; data?: Record<string, unknown> }): unknown => {
  const d = (a.data ?? {}) as { op?: string; at?: number; to?: number; clip?: string; edge?: string; ripple?: boolean; marker?: string; name?: string; locked?: boolean };
  if (a.action === "sequence_get") return cutView();
  if (a.action === "undo") { const p = cutPast.pop(); if (!p) throw new Error("There is nothing to undo."); cutFuture.push(cutNow); cutNow = p; return cutView(); }
  if (a.action === "redo") { const n = cutFuture.pop(); if (!n) throw new Error("There is nothing to do again."); cutPast.push(cutNow); cutNow = n; return cutView(); }
  if (a.action !== "edit") throw new Error("Unknown action.");
  const next: CutMock = JSON.parse(JSON.stringify(cutNow));
  const f = (v: unknown) => Math.round(Number(v) * 24);
  const find = () => { const c = next.clips.find((x) => x.id === d.clip); if (!c) throw new Error("That clip is not in the film."); return c; };
  if (next.locked && d.op !== "track_set") throw new Error("The track V1 is locked. Unlock it to edit.");
  const end = (c: CutClipMock) => c.start + c.duration;
  switch (d.op) {
    case "split": { const at = f(d.at); const c = next.clips.find((x) => x.start < at && at < end(x)); if (!c) throw new Error("There is no clip to cut there (a cut has to fall inside a clip, not on its edge)."); const first = at - c.start;
      next.clips.push({ id: `c${cutSeq++}`, shot: c.shot, start: at, source_in: c.source_in + first, duration: c.duration - first }); c.duration = first; break; }
    case "trim": { const c = find(); const to = f(d.to); const after = next.clips.filter((x) => x.start > c.start);
      if (d.edge === "in") { const delta = to - c.start; if (c.duration - delta <= 0) throw new Error("A clip cannot be trimmed to nothing. Delete it instead."); if (delta < 0 && c.source_in < -delta) throw new Error("There is no more of this clip before its start to bring back.");
        c.source_in += delta; c.duration -= delta; if (d.ripple) { after.forEach((x) => { x.start -= delta; }); next.length -= delta; } else c.start = to; }
      else { const nd = to - c.start; if (nd <= 0) throw new Error("A clip cannot be trimmed to nothing. Delete it instead."); const delta = nd - c.duration; c.duration = nd; if (d.ripple) { after.forEach((x) => { x.start += delta; }); next.length += delta; } }
      break; }
    case "delete": { const c = find(); next.clips = next.clips.filter((x) => x.id !== c.id); if (d.ripple) { next.clips.filter((x) => x.start > c.start).forEach((x) => { x.start -= c.duration; }); next.length -= c.duration; } break; }
    case "move": { const c = find(); c.start = Math.max(0, f(d.to)); if (next.clips.some((x) => x.id !== c.id && c.start < end(x) && x.start < end(c))) throw new Error("There is no room for the clip there: it would overlap another. Move it into a gap, or use a ripple move to make room."); break; }
    case "marker_set": next.markers.push({ id: `m${cutSeq++}`, at: f(d.at), name: d.name ?? "" }); break;
    case "marker_remove": next.markers = next.markers.filter((m) => m.id !== d.marker); break;
    case "track_set": next.locked = !!d.locked; break;
    default: throw new Error("That edit is not in the screenshot harness.");
  }
  next.clips.sort((x, y) => x.start - y.start);
  cutPast.push(cutNow); cutFuture = []; cutNow = next; cutStored = true;
  return cutView();
};
// The Smart Editor's made-up backend: two fixed suggestions that accept, reject and preview in memory (the real rules and previews are in the engine's own tests)
type SmartMock = { id: string; kind: "tighten" | "react"; title: string; what: string; why: string; clips: string[]; shots: string[]; saves: number; window: number[]; ops: Record<string, unknown>[] };
let smartLeft: SmartMock[] = [
  { id: "a1b2c3d4e5", kind: "tighten", title: "Tighten the end of S01-01", clips: ["c1"], shots: ["S01-01"], saves: 1.0, window: [0, 6], ops: [],
    what: "End S01-01 1.0 s sooner (4.5 s to 3.5 s) and close the gap.",
    why: "S01-01 has 9 spoken words in 1 line, which take about 3.8 s to say. With a 1.4 s breath after the last word it needs about 5.2 s, and it runs 6.0 s: 0.8 s more. Cutting the dead time keeps the scene moving. It is only a reading: refuse it if the quiet is the point." },
  { id: "f6a7b8c9d0", kind: "react", title: "Give S01-02 a little more time", clips: ["c2"], shots: ["S01-02"], saves: -0.6, window: [4, 9], ops: [],
    what: "Hold S01-02 for 0.6 s longer, and move what follows later by the same amount.",
    why: "S01-02 shows John after S01-01, where words were spoken. A moment on the listener lets the audience take in what was said. The take has more picture for it. Refuse it if the pace is right." }];
const smartKept = [{ kind: "tighten", shot: "S02-01", clip: "c4", why: "Kept the pause at the end of S02-01: you asked to hold the reaction longer there." }];
const smartCall = (a: { action?: string; data?: Record<string, unknown> }): unknown => {
  const d = (a.data ?? {}) as { id?: string; text?: string };
  const recipe = { id: "restrained_drama", label: "Restrained character drama", for: "Quiet scenes where silence and reactions carry the feeling." };
  switch (a.action) {
    case "recipes": return { default: "restrained_drama", recipes: [{ id: "restrained_drama", label: "Restrained character drama", for: recipe.for, built: true }, { id: "intimate_conversation", label: "Intimate conversation", for: "Two people talking close.", built: true },
      { id: "rhythmic_montage", label: "Rhythmic montage", for: "Quick, cut-on-the-beat sequences.", built: true }, { id: "suspense", label: "Suspense and anticipation", for: "", built: false }] };
    case "suggest": return { recipe, proposals: smartLeft, kept: smartKept };
    case "ask": return d.text && /tighten|shorter/i.test(d.text) ? { understood: true, message: "Tightening: ending spoken clips a little after the last word. Across the film. Style: Restrained character drama.", recipe, proposals: smartLeft.filter((p) => p.kind === "tighten"), kept: smartKept }
      : { understood: false, message: "I did not understand that as something I can do yet. I can: tighten (end spoken clips a little after the last word); give a listener more time after someone speaks.", recipe, proposals: [], kept: [] };
    case "accept": case "reject": { const p = smartLeft.find((x) => x.id === d.id); if (!p) throw new Error("That suggestion no longer applies: the cut has changed since it was made. Ask again."); smartLeft = smartLeft.filter((x) => x.id !== d.id); return { accepted: p.title, rejected: p.title }; }
    case "reset_rejected": return { cleared: 0 };
    case "preview": return { before: "s1.png", after: "s2.png" };
    default: throw new Error("Unknown action.");
  }
};
// The presets' made-up backend: the real built-in catalog, with the stacking, the preview and the "yours is kept" rule worked out here the same way so the sheet can be tried (the engine's own tests prove the real rules)
type PMock = { id: string; type: string; group: string; name: string; description: string; use: string; version: number; thumbnail: string | null; includes: string[]; settings: Record<string, unknown>; complexity: number; series?: string };
const pBuiltin = (presetsBuiltin as unknown as { presets: PMock[] }).presets;
let pNow: Record<string, { value: unknown; set: boolean }> = { look: { value: "claymation", set: true }, acting: { value: "natural", set: false }, grade: { value: {}, set: false }, editing: { value: null, set: false }, delivery: { value: null, set: false },
  aspect: { value: "16:9", set: false }, duration_hint_s: { value: null, set: false } };
let pStack: string[] = [];
let pFav: string[] = [];
let pMine: (PMock & { mine: true })[] = [];
let pApplied: { before: Record<string, { value: unknown; set: boolean }>; keys: string[] }[] = [];
const pAll = () => [...pBuiltin, ...pMine];
const pExpand = (ids: string[]): string[] => { const out: string[] = []; const visit = (id: string) => { const p = pAll().find((x) => x.id === id); if (!p) throw new Error(`The preset "${id}" is not here.`); p.includes.forEach(visit); if (!out.includes(id)) out.push(id); }; ids.forEach(visit); return out; };
const pResolve = (ids: string[]) => { const out: Record<string, { value: unknown; by: string }> = {}; for (const id of pExpand(ids)) for (const [k, v] of Object.entries(pAll().find((x) => x.id === id)!.settings)) out[k] = { value: v, by: id }; return out; };
const pPlan = (stack: string[], replace: string[] = []) => {
  const want = pResolve(stack);
  const changes = ["look", "acting", "grade", "editing", "delivery", "aspect", "duration_hint_s"].filter((k) => k in want).map((k) => {
    const cur = pNow[k]; const same = JSON.stringify(cur.value) === JSON.stringify(want[k].value);
    return { key: k, status: same ? "same" : !cur.set ? "new" : replace.includes(k) ? "replace" : "yours", now: cur.value, to: want[k].value, by: want[k].by, set: cur.set };
  });
  const notes = [...(changes.some((c) => c.key === "delivery" && (c.to as { export: string }).export === "vertical") ? ["Your film keeps its own shape. The vertical version is made as a separate export; the original is never changed."] : []),
    "Nothing is regenerated and no provider is called: only settings change, and every change can be undone."];
  return { stack, order: pExpand(stack), changes, notes };
};
const pCatalog = () => ({ presets: pAll().map((p) => ({ ...p, series: p.series, mine: "mine" in p, favorite: pFav.includes(p.id), recent: false, in_stack: pStack.includes(p.id) })), stack: pStack, types: ["production", "visual", "performance", "editing", "color", "delivery"], applied: pApplied.length, current: pNow, is_film: true });
let pReframe: Record<string, number> = {};
const presetCall = (a: { action?: string; data?: Record<string, unknown> }): unknown => {
  const d = (a.data ?? {}) as { stack?: string[]; replace?: string[]; id?: string; on?: boolean; name?: string; shot?: string; x?: number | null };
  switch (a.action) {
    case "catalog": return pCatalog();
    case "plan": return pPlan(d.stack ?? [], d.replace ?? []);
    case "apply": { const pl = pPlan(d.stack ?? [], d.replace ?? []); const todo = pl.changes.filter((c) => c.status === "new" || c.status === "replace"); pApplied.push({ before: JSON.parse(JSON.stringify(pNow)), keys: todo.map((c) => c.key) });
      todo.forEach((c) => { pNow[c.key] = { value: c.to, set: true }; }); pStack = d.stack ?? []; return { changed: todo.map((c) => c.key), kept: pl.changes.filter((c) => c.status === "yours").map((c) => c.key), same: [], plan: pl }; }
    case "undo": { const last = pApplied.pop(); if (!last) throw new Error("There is nothing to undo."); last.keys.forEach((k) => { pNow[k] = last.before[k]; }); return { restored: last.keys, kept_as_changed_since: [] }; }
    case "favorite": pFav = pFav.filter((f) => f !== d.id).concat(d.on ? [String(d.id)] : []); return pCatalog();
    case "save_mine": { const settings = Object.fromEntries(Object.entries(d.stack?.length ? pResolve(d.stack) : Object.fromEntries(Object.entries(pNow).filter(([, v]) => v.set).map(([k, v]) => [k, { value: v.value }]))).map(([k, v]) => [k, (v as { value: unknown }).value]));
      const id = `mine-${String(d.name).toLowerCase().replace(/[^a-z0-9]+/g, "-")}`; pMine.push({ id, type: "custom", group: "Mine", name: String(d.name), description: "Your own preset.", use: "", version: 1, thumbnail: null, includes: [], settings, complexity: 1, mine: true }); return { saved: id, catalog: pCatalog() }; }
    case "delete_mine": pMine = pMine.filter((p) => p.id !== d.id); return pCatalog();
    case "stack_get": return { stack: pStack, reframe: pReframe, editing: null, delivery: pNow.delivery.set ? pNow.delivery.value : null, duration_hint_s: null, applied: [] };
    case "reframe_set": { if (d.x == null || Math.abs(Number(d.x) - 0.5) < 0.0005) delete pReframe[String(d.shot)]; else pReframe[String(d.shot)] = Number(d.x); return { stack: pStack, reframe: pReframe, editing: null, delivery: null, duration_hint_s: null, applied: [] }; }
    default: throw new Error("That is not in the screenshot harness.");
  }
};
type SF = { value: string; source: "scaffold" | "you" };
let serPlan: { idea: string; preset: string; hero: string; cast: string[]; places: string[]; episodes: { n: number; title: string; seconds: number; role: string; hook: SF; escalation: SF; turning_point: SF; ending: SF; continuity: SF; cliffhanger: boolean; budget_usd: number | null }[];
  season: { logline: SF; genre: string; tone: SF; rules: SF; ending: SF; season_budget_usd: number | null } } | null = null;
const SER_NOTE = "This is a plan to edit, not a story written for you. The suggestions are marked until you write or keep them. Nothing is sent anywhere and nothing is charged; making the episodes is a separate step that shows its price first.";
const seriesCall = (a: { action?: string; data?: Record<string, unknown> }): unknown => {
  const d = (a.data ?? {}) as { idea?: string; episodes?: number; seconds?: number; n?: number; key?: string } & Record<string, unknown>;
  const sf = (v: string, s: "scaffold" | "you" = "scaffold"): SF => ({ value: v, source: s });
  const out = () => ({ plan: serPlan, exists: serPlan !== null, note: SER_NOTE });
  const ep = () => { const e = serPlan?.episodes.find((x) => x.n === d.n); if (!e) throw new Error("That episode is not in the plan."); return e; };
  switch (a.action) {
    case "get": return out();
    case "create": { const n = Number(d.episodes ?? 10); const hero = "Sarah";
      serPlan = { idea: String(d.idea), preset: "vertical_micro_drama", hero, cast: ["Sarah", "John"], places: ["Kitchen", "Platform"], season: { logline: sf(String(d.idea).split(/(?<=[.!?])\s+/)[0]), genre: "drama", tone: sf(""), rules: sf(""), ending: sf("How does the season end, and what does it say?"), season_budget_usd: null },
        episodes: Array.from({ length: n }, (_, i) => ({ n: i + 1, title: i === 0 ? "Episode 1: the hook" : `Episode ${i + 1}`, seconds: Number(d.seconds ?? 90), role: i === 0 ? "opening" : i === n - 1 ? "close" : i === Math.floor((n - 1) / 2) ? "turn" : i < n / 2 ? "building" : "pressure",
          hook: sf(`Open on the moment that makes someone stay: ${hero} wants something and cannot have it.`), escalation: sf(`Make it cost ${hero} something to keep going.`), turning_point: sf(`A discovery that changes what ${hero} thinks is true.`), ending: sf("End on a question the next episode answers."), continuity: sf(""), cliffhanger: i % 3 !== 2 && i !== n - 1, budget_usd: null })) };
      return out(); }
    case "set_episode": { const e = ep(); for (const k of ["hook", "escalation", "turning_point", "ending", "continuity"] as const) if (k in d) e[k] = sf(String(d[k]), "you"); if ("cliffhanger" in d) e.cliffhanger = !!d.cliffhanger; if ("seconds" in d) e.seconds = Number(d.seconds); if ("budget_usd" in d) e.budget_usd = d.budget_usd as number | null; return out(); }
    case "set_season": for (const k of ["logline", "tone", "rules", "ending"] as const) if (serPlan && k in d) serPlan.season[k] = sf(String(d[k]), "you"); return out();
    case "reset_field": { const e = ep(); (e as Record<string, unknown>)[String(d.key)] = sf("End on a question the next episode answers."); return out(); }
    case "resize": return out();
    case "report": return { episodes: serPlan?.episodes.length ?? 0, total_seconds: (serPlan?.episodes.length ?? 0) * 90, written: serPlan?.episodes.filter((e) => e.hook.source === "you").length ?? 0, cliffhangers: serPlan?.episodes.filter((e) => e.cliffhanger).length ?? 0, cast: {}, places: {}, budget_total_usd: null, season_budget_usd: null,
      notes: (serPlan?.episodes ?? []).slice(0, 3).map((e) => ({ level: "todo", episode: e.n, what: `Episode ${e.n}: write your own hook and ending (the suggestion is only a starting point).` })) };
    case "export_markdown": return { path: "series-plan.md" };
    case "make_films": { const n = serPlan?.episodes.length ?? 0; return { made: Array.from({ length: n }, (_, i) => ({ n: i + 1, title: `Episode ${i + 1}`, dir: `films/ep${i + 1}` })), kept: [], folder: "films" }; }
    default: throw new Error("That is not in the screenshot harness.");
  }
};
// The motion graphics' made-up backend: the eight built-in templates by name (the sheet draws previews from sample pictures here; the engine draws the real ones from your words)
const MG = [["lower_third", "Lower third", "A name and a role at the bottom of the picture, for whoever has just appeared.", 4.5, 4, [["name", "Name", "Sarah Okafor"], ["role", "Role or place", "Head nurse"]]],
  ["title_card", "Title card", "The film's title over a dark tint, with a line underneath.", 6, 3, [["title", "Title", "The Last Train"], ["line", "Line under it", "A short film"]]],
  ["chapter_title", "Chapter title", "A small label and a chapter name, typed in.", 5, 3, [["label", "Label", "CHAPTER ONE"], ["title", "Chapter name", "The Name on the Chart"]]],
  ["location_tag", "Place and time", "Where and when, small and typed, in the corner.", 4, 1, [["place", "Place and time", "ST. MARY'S HOSPITAL, 3:12 AM"]]],
  ["callout", "Callout", "Point at something: a label in a box with an arrow.", 4, 3, [["text", "Label", "Look here"]]],
  ["quote", "Quote", "A line someone said, with who said it.", 6, 3, [["quote", "The words", "I am fine."], ["who", "Said by", "Sarah"]]],
  ["big_number", "Big number", "One number that matters, with what it means.", 5, 2, [["number", "Number", "86%"], ["what", "What it is", "of patients never learn the name"]]],
  ["end_card", "End card", "The end, with a closing line.", 6, 3, [["end", "Words", "The End"], ["line", "Closing line", "Thank you for watching"]]]] as const;
let mgGroups = 0;
const layerKitCall = (a: { action?: string; data?: Record<string, unknown> }): unknown => {
  const d = (a.data ?? {}) as { id?: string; group?: string };
  switch (a.action) {
    case "builtin_list": return { templates: MG.map(([id, name, use, seconds, layers, slots]) => ({ id, name, use, seconds, layers, slots: slots.map(([sid, label, def]) => ({ id: sid, label, default: def })) })) };
    case "builtin_preview": { const i = MG.findIndex((m) => m[0] === d.id); if (i < 0) throw new Error("That motion graphic is not one of the built-in ones."); return { path: `s${(i % 6) + 1}.png`, id: d.id }; }
    case "builtin_apply": { const m = MG.find((x) => x[0] === d.id); if (!m) throw new Error("That motion graphic is not one of the built-in ones."); mgGroups += 1; return { made: m[4], group: `tpl:${String(d.id).replace(/_/g, "")}:${mgGroups}`, layers: [], seconds: m[3] }; }
    case "template_remove": return { removed: 4, layers: [] };
    case "templates": return { templates: [] };
    default: return { styles: [] };
  }
};
const gdCall = (a: { action?: string; data?: Record<string, unknown> }): unknown => {
  const d = (a.data ?? {}) as { scope?: string; key?: string | number; grade?: GradeMock; id?: string; on?: boolean; name?: string; path?: string };
  const table = () => (d.scope === "scene" ? gdGrades.scenes : gdGrades.shots) as Record<string, GradeMock>;
  const note = (what: string) => gdHistory.push({ rev: gdHistory.length + 1, at: 0, what });
  switch (a.action) {
    case "state": return gdState();
    case "set_grade": case "clear_grade": {
      const g = a.action === "clear_grade" ? {} : (d.grade ?? {});
      const lut = (g as { lut?: { id: string } }).lut;
      const meta = lut ? gdLuts.find((l) => l.id === lut.id) : undefined;
      if (meta && meta.space_in !== "rec709") throw new Error(`This LUT expects ${meta.space_in} footage, and FilmCrafter's pictures are Rec.709. It is not applied: using it would change the colours in a way it was not made for.`);
      if (d.scope === "film") gdGrades.film = g; else if (Object.keys(g).length) table()[String(d.key)] = g; else delete table()[String(d.key)];
      note(`set the ${d.scope} grade`); return gdState();
    }
    case "lut_favorite": { const l = gdLuts.find((x) => x.id === d.id); if (l) l.favorite = !!d.on; return gdState(); }
    case "lut_remove": { const i = gdLuts.findIndex((x) => x.id === d.id); if (i >= 0) gdLuts.splice(i, 1); return gdState(); }
    case "lut_import": { gdLuts.push({ id: Math.random().toString(16).slice(2, 18).padEnd(16, "0"), name: "Imported look", kind: "creative", space_in: "rec709", space_out: "rec709", dims: 3, size: 17, favorite: false }); return gdState(); }
    case "preset_save": { const g = d.scope === "film" ? gdGrades.film : table()[String(d.key)]; if (!g || !Object.keys(g).length) throw new Error("There is nothing set there to save."); gdPresets.push({ name: String(d.name), grade: g }); return gdState(); }
    case "preset_apply": { const p = gdPresets.find((x) => x.name === d.name); if (p) { if (d.scope === "film") gdGrades.film = p.grade; else table()[String(d.key)] = p.grade; } return gdState(); }
    case "preset_delete": { const i = gdPresets.findIndex((x) => x.name === d.name); if (i >= 0) gdPresets.splice(i, 1); return gdState(); }
    case "undo": gdHistory.pop(); return gdState();
    case "preview": return { before: "s1.png", after: "s3.png" };
    default: throw new Error("Unknown action.");
  }
};
const NUDGE_DEFS: [string, string, number][] = [["restrained", "More restrained", 2], ["grounded", "Less exaggerated", 1], ["vulnerable", "More vulnerable", 1], ["hesitant", "More hesitant", 1], ["playful", "More playful", 1],
  ["tense", "More tension", 1], ["still_body", "Reduce body movement", 1], ["eyes", "Let the eyes tell the story", 1], ["hold", "Hold the reaction longer", 1]];
const pdCall = (a: { action?: string; data?: Record<string, unknown> }): unknown => {
  const d = (a.data ?? {}) as { scene?: number; path?: string; value?: string; person?: string; fields?: Record<string, string>; nudge?: string; level?: number };
  const sc = pdScenes.find((s) => s.number === Number(d.scene));
  const slot = (path: string): PdField | null => {
    if (!sc) return null;
    const p = path.split(".");
    if (p.length === 1) return (sc.fields as Record<string, PdField>)[p[0]] ?? null;
    if (p[0] === "people") return ((sc.people.find((x) => x.name === p[1]) as unknown as Record<string, PdField>) ?? {})[p[2]] ?? null;
    if (p[0] === "subtext") return sc.subtext.find((x) => x.id === p[1])?.means ?? null;
    return null;
  };
  switch (a.action) {
    case "breakdown_get": return { has_contracts: true, scenes: pdScenes };
    case "breakdown_set": case "breakdown_accept": { const s = slot(String(d.path)); if (!s) throw new Error("That is not a part of this scene's breakdown.");
      s.value = a.action === "breakdown_set" ? String(d.value ?? "") : s.value; s.source = "you"; s.from = "your edit"; return sc; }
    case "breakdown_reset": { const s = slot(String(d.path)); if (!s) throw new Error("That is not a part of this scene's breakdown."); s.source = "auto"; s.from = "the draft"; return sc; }
    case "kind_options": return { kinds: [["human", "A person"], ["stylised", "A stylised person (cartoon, puppet)"], ["animal", "An animal"], ["robot", "A robot or machine"], ["creature", "A creature or monster"]].map(([id, label]) => ({ id, label })) };
    case "continuity_get": case "continuity_dismiss": {
      if (a.action === "continuity_dismiss") { const f = String((d as { flag?: string }).flag); if ((d as { undo?: boolean }).undo) pdDismissed.delete(f); else pdDismissed.add(f); }
      const all = [{ id: "Sarah|abrupt|Scene 1>Scene 2", kind: "abrupt", scenes: ["Scene 1", "Scene 2"], message: "Sarah goes from calm (2/10) to furious (8/10) between Scene 1 and Scene 2. If nothing in the story causes that change, it may feel sudden." }];
      return { sections: ["Scene 1", "Scene 2"], dismissed: [...pdDismissed], people: [{ name: "Sarah", source: "you", dismissed: all.filter((x) => pdDismissed.has(x.id)).length,
        track: [{ section: "Scene 1", emotion: "calm", intensity: 2 }, { section: "Scene 2", emotion: "furious", intensity: 8 }], flags: all.filter((x) => !pdDismissed.has(x.id)) }] };
    }
    case "characters_get": return { fields: ["personality", "desire", "fears", "triggers", "contradictions", "defenses", "speech_rhythm", "carriage", "stress", "state_now"],
      people: Object.keys(pdProfiles).map((n) => ({ name: n, profile: { personality: "", desire: "", fears: "", triggers: "", contradictions: "", defenses: "", speech_rhythm: "", carriage: "", stress: "", state_now: "", ...pdProfiles[n] },
        known: n === "Sarah" ? { role: "Lead", relationships: "Wants John to stay" } : {}, style: n === "Sarah" ? "restrained" : "", gestures: n === "Sarah" ? [{ when: "flustered", do: "touches the front of her collar" }] : [] })) };
    case "character_set": { const n = String(d.person); pdProfiles[n] = { ...pdProfiles[n], ...Object.fromEntries(Object.entries(d.fields ?? {}).filter(([, v]) => v)) }; return pdCall({ action: "characters_get" }); }
    case "character_clear": { pdProfiles[String(d.person)] = {}; return pdCall({ action: "characters_get" }); }
    case "beats_suggest": return { shot: "S01-02", seconds: 4.2, basis: "A rule-based starting point from the feeling (brittle calm), Sarah's acting style (restrained). Edit it freely; nothing is saved until you save.",
      beats: [{ t0: 0, t1: 1.47, what: "Sarah registers what is happening before reacting", eyes: "toward John", change: "the moment arrives", source: "auto", confidence: "low" },
        { t0: 1.47, t1: 2.94, what: "Sarah reacts: brittle calm, in a small readable way", face: "lips press into a tight smile", change: "brittle calm begins to show", source: "auto", confidence: "low" },
        { t0: 2.94, t1: 4.2, what: "Sarah holds the moment still; the feeling stays in the eyes and the breath", change: "the feeling settles", source: "auto", confidence: "low" }] };
    case "nudges_get": return { shot: "S01-02", nudges: NUDGE_DEFS.map(([id, label, levels]) => ({ id, label, level: pdNudges[id] ?? 0, levels })) };
    case "nudge_set": { if (d.level) pdNudges[String(d.nudge)] = Number(d.level); else delete pdNudges[String(d.nudge)]; return { ...(pdCall({ action: "nudges_get" }) as object), beats: { shot: "S01-02", beats: [] } }; }
    default: throw new Error("Unknown action.");
  }
};
const sbRead = (): StyleBibleRead => ({ style: { id: "claymation", name: "Claymation", prompt: "" }, scenes: [], shots: { ...sbShots }, keep_cast: { ...sbKeep }, precedence: [],
  styles: [{ id: "claymation", name: "Claymation", group: "", description: "" }, { id: "anime", name: "Shonen action anime", group: "", description: "" }, { id: "noir", name: "Film noir", group: "", description: "" }] });
const ShotLookDemo = () => {
  const [own, setOwn] = useState<StyleBibleRead>(sbRead());
  const [picking, setPicking] = useState(false);
  const mine = own.shots["S01-04"];
  const pick = (style: string) => { setPicking(false); saveShotLook(DIR, "S01-04", shotLookToSave(style, "claymation")).then(setOwn); };
  const shotFx: Shot = { id: "S01-04", scene: 1, number: 4, start: 12, end: 16.5, beats: ["Sege opens the suitcase and finds the letter."], source_shots: ["S01-04"], performers: ["Sege"], framing: "Close-up", state: "planned", renderer: "auto", emotion: "dread" };
  return (
    <>
    <aside className="inspector" style={{ width: 360, height: 700, display: "flex", flexDirection: "column" }} aria-label="Inspector">
      <ShotInspector shot={shotFx} director={false} onClose={noop} project={project}
        tabs={{ styleChanged: scene !== "shotlook-own" || !!mine, look: { name: mine ? (own.styles.find((x) => x.id === mine)?.name ?? mine) : "Claymation", own: !!mine, onOpen: () => setPicking(true) },
          badges: { keyframe: "", frames: "", video: "", media: "" }, media: null, keyframe: () => null, frames: () => null, video: () => null,
          shot: <ShotLook dir={DIR} shotId="S01-04" own={own} filmLook="claymation" sceneLook="claymation" onChanged={setOwn} /> }} />
    </aside>
    {picking && <LookPicker value={{ style: mine || "claymation" }} director={false} onCancel={() => setPicking(false)} onSave={(l) => pick(l.style)}
                            shot={{ id: "S01-04", own: !!mine, sameAs: "Same as its film (Claymation)", onClear: () => pick("") }} />}
    </>
  );
};
const keys = { openai: true, fal: true, kie: true, google: false, elevenlabs: false } as never;
const take = (id: string, _shot: string, n: number, over: Record<string, unknown> = {}) => ({ id, n, state: "ready", provider: "kie", model: "bytedance/seedance-2", output: `v${n}.mp4`, kind: "video", created: n, cost: n === 1 ? 50 : 38, cost_unit: "credits", approved: n === 1, ...over });
const card = (children: ReactNode, width = 480) => <div className="sheet glass" style={{ width }}>{children}</div>;
const scenes: Record<string, () => ReactNode> = {
  agentstudio: () => <AgentStudio project={{ dir: DIR, ...(renderFixture as object), directed: null, jobs: reviewJobs.slice(0, 3), keyframes: {}, concepts: null, treatment: null, song_path: DIR + "/soundtrack.wav", doc: null } as never} onHome={noop} onManual={noop} />,
  directorstyle: () => <DirectorStyleSheet dir={DIR} onClose={noop} />,
  fidelity: () => <FidelitySheet dir="f1" shot="S01-04" onClose={noop} onChanged={noop} />,
  exportsheet: () => <ExportSheet dir="f1" projectAspect="16:9" shots={6} rendered={6} onClose={noop} />,
  exportdraft: () => <ExportSheet dir="f-draft" projectAspect="16:9" shots={6} rendered={3} onClose={noop} />,
  guide: () => <FirstFilm dir={DIR} pro={true} onGo={noop} onClose={noop} progress={{ story: { kind: "screenplay", locked: true, as_is: true }, cast: { characters: 2, places: 2, pictures: 2, style: true }, shots: { count: 6, edited: 1 }, make: { shots: 6, storyboard: 6, keyframe: 6, video: 6 } }} />,
  layerclip: () => <div style={{ width: 380, padding: 16 }} className="glass"><LayersPanel dir={MIXCLIPDIR} selected="l6" onSelect={noop} onClose={noop} time={3} docked /></div>,
  layermix: () => <div style={{ width: 380, padding: 16 }} className="glass"><LayersPanel dir={MIXDIR} selected="l5" onSelect={noop} onClose={noop} time={3} docked /></div>,
  layers: () => <div style={{ width: 380, padding: 16 }} className="glass"><LayersPanel dir={DIR} selected="l1" onSelect={noop} onClose={noop} time={3} docked /></div>,
  layerlanes: () => <div style={{ width: 900, height: 120, position: "relative", background: "#10131a", overflow: "hidden" }}><LayerLanes dir={DIR} pps={40} duration={30} selected="l1" onSelect={noop} snap={[]} top={0} time={3} onSeek={noop} /></div>,
  settings: () => <Settings onClose={noop} onHelp={noop} />,
  home: () => <Home onNewFilm={noop} onOpen={noop} onChooseProject={noop} onSettings={noop} onHelp={noop} />,
  homeflow: () => <Home onNewFilm={(o) => { ((window as unknown as { __home?: unknown[] }).__home ??= []).push({ new: o ?? {} }); }} onOpen={(d) => { ((window as unknown as { __home?: unknown[] }).__home ??= []).push({ open: d }); }} onChooseProject={() => { ((window as unknown as { __home?: unknown[] }).__home ??= []).push({ choose: true }); }} onSettings={noop} onHelp={noop} />,
  newfilm: () => <NewFilm onClose={noop} onCreated={noop} />,
  newfilmpreset: () => <NewFilm kind="idea" preset="vertical_micro_drama" onClose={noop} onCreated={noop} />,
  newfilmwrite: () => <NewFilm file="last-train.fountain" onClose={noop} onCreated={noop} />,
  studio: () => <Studio project={{ dir: DIR, ...(renderFixture as object), directed: null, jobs: [], keyframes: {}, concepts: null, treatment: null, song_path: DIR + "/soundtrack.wav", doc: null } as never} onHome={noop} onSettings={noop} onReload={noop} />,
  studiovoice: () => <Studio project={{ dir: DIR + "/render", ...(renderFixture as object), directed: null, jobs: [], keyframes: {}, concepts: null, treatment: null, song_path: DIR + "/soundtrack.wav", doc: null } as never} onHome={noop} onSettings={noop} onReload={noop} />,
  cutedit: () => { try { localStorage.setItem(`pf-tl:${DIR}/render`, JSON.stringify({ edit: true })); } catch { /* storage can be blocked */ } return <Studio project={{ dir: DIR + "/render", ...(renderFixture as object), directed: null, jobs: [], keyframes: {}, concepts: null, treatment: null, song_path: DIR + "/soundtrack.wav", doc: null } as never} onHome={noop} onSettings={noop} onReload={noop} />; },
  make: () => <div style={{ width: "min(1240px, 100vw)", height: 760, display: "flex", background: "#090b0f" }}><MakeFilm dir="f1" tab="keyframe" onTab={noop} /></div>,
  export: () => <div style={{ width: "min(1240px, 100vw)", height: 760, display: "flex", background: "#090b0f" }}><MakeFilm dir="f1" tab="deliver" onTab={noop} /></div>,
  continuity: () => <div style={{ width: 1100, height: 640, display: "flex", background: "#090b0f" }}><FilmContinuity dir="f1" onGo={noop} onChanged={noop} /></div>,
  assist: () => <AssistSheet dir="f1" kind="character" id="c_sarah" name="Sarah" bible={bibleView as never} onClose={noop} onApplied={noop}
    proposal={{ role: "Lead: the one who waits", age: "28", physical: "Tall, grey eyes, dark hair tied back, a ring she never takes off", relationships: "John's partner; her mother's only daughter", arc: "From waiting for a call to deciding to leave", voice: "Low, careful, says less than she means", notes: "Keeps her hands busy when she is hiding something" }} />,
  shotsuggest: () => <ShotSuggestionSheet shot="S01-02" current={shotContract as never} onClose={noop} onUse={noop}
    proposal={{ emotional_intention: "A held-back dread that neither of them names", beats: [{ character: "Sarah", what: "Holds the cup with both hands", want: "To be asked", hiding: "That she has packed", start: "calm", turn: "he does not look up", end: "still" }], micro_animation: "Steam rises; she blinks slowly",
      camera: { framing: "over the shoulder", angle: "low", lens: "portrait (50mm)", movement: "locked off", focus: "shallow", why: "Low and close keeps us with Sarah's silence." }, lighting: { description: "Low window light from the left", why: "Morning light is soft and slow." } }} />,
  shotvoice: () => <div style={{ width: "min(1240px, 100vw)", height: 780, display: "flex", background: "#090b0f" }}><ShotLab dir="f1" /></div>,
  shots: () => <div style={{ width: "min(1240px, 100vw)", height: 780, display: "flex", background: "#090b0f" }}><ShotLab dir="f1" /></div>,
  cast: () => <div style={{ width: "min(1200px, 100vw)", height: Number(q.get("h")) || 760, display: "flex", background: "#090b0f" }}><CastWorld dir="f1" /></div>,
  film: () => <FilmView dir="f1" onHome={noop} onSettings={noop} />,
  color: () => <ColorStudioSheet dir={DIR} onClose={noop} />,
  smarteditor: () => <SmartEditorSheet dir={DIR} onClose={noop} />,
  presets: () => <PresetsSheet dir={DIR} onClose={noop} />,
  motion: () => <MotionGraphicsSheet dir={DIR} time={12.34} onClose={noop} />,
  shotacting: () => <aside className="inspector" style={{ width: 380, padding: 14 }} aria-label="Inspector"><ShotPerformance dir={DIR} shotId="S01-02" onChanged={noop} /></aside>,
  library: () => <LibrarySheet dir={DIR} scenes={[{ number: 1, heading: "BEDROOM - BEFORE DAWN" }, { number: 2, heading: "KITCHEN - MORNING" }, { number: 3, heading: "MARKET - DAY" }]} onClose={noop} onChanged={noop} />,
  supervisor: () => <SupervisorSheet dir={DIR} onClose={noop} onReview={noop} onChanged={noop} />,
  acting: () => <PerformanceSheet dir={DIR} scenes={[{ number: 1, heading: "INT. SEGE'S BEDROOM - BEFORE DAWN" }, { number: 2, heading: "INT. SEGE'S KITCHEN - MORNING" }]} characters={["Sege", "Amara", "Young Sege"]} onClose={noop} onChanged={noop} />,
  colourmatch: () => <ColourMatchSheet dir={DIR} onClose={noop} />,
  review: () => <ReviewSheet dir={DIR} shots={shots} jobs={reviewJobs} inUse={{ "S01-03": "a1", "S02-02": "b1" }} keys={keys} onSelect={noop} onJobs={noop} onClose={noop} />,
  queue: () => <RenderQueueSheet dir={DIR} jobs={queueJobs} shots={shots} onJob={noop} onShow={noop} onReview={noop} onClose={noop} />,
  retry: () => <RenderQueueSheet dir={DIR} jobs={queueJobs} shots={shots} onJob={noop} onShow={noop} onReview={noop} onClose={noop} />,
  keyframetools: () => <KeyframeTools dir={DIR} onClose={noop} />,
  handfix: () => <HandFix dir={DIR} shot="S01-02" image="s2.png" onClose={noop} />,
  planbudget: () => <RoutingSheet dir={DIR} onClose={noop} />,
  selectreview: () => <SelectReview dir={DIR} shots={ids.map((id, i) => ({ id, scene: N > 8 ? Number(id.slice(1, 3)) : 1, start: i * 6, end: i * 6 + 5, framing: ["Close-up", "Wide", "Medium", "Over the shoulder"][i % 4], beat: "", performers: [], status: "ready", locked: false, approved: null, thumb_src: null, thumb_source: "keyframe", preview: null, keyframe: still(i), versions: [], references: [] })) as never} sections={[{ label: "verse", group: "Verse 1", start: 0, end: 24 }, { label: "chorus", group: "Chorus", start: 24, end: 48 }] as never} initial={ids.slice(0, 4)} onClose={noop} onQueued={noop} />,
  compare: () => <div className="sheet glass viewer-sheet" style={{ width: 920 }}><div className="vs-head"><h2 className="num">Shot S01-03</h2></div><CompareLazy /></div>,
  directionlibrary: () => <DirectionLibrarySheet dir={DIR} onClose={noop} onApplied={noop} />,
  looks: () => <LookPicker value={{ style: "auto" }} director={false} onCancel={noop} onSave={noop} />,
  shotlook: () => <ShotLookDemo />,
  "shotlook-own": () => <ShotLookDemo />,
  shotlookpicker: () => <LookPicker value={{ style: "claymation" }} director={false} onCancel={noop} onSave={noop} shot={{ id: "S01-04", own: true, sameAs: "Same as its film (Claymation)", onClear: noop }} />,
  lighting: () => <LightingSheet dir={DIR} onClose={noop} />,
  cleanup: () => <CleanupSheet dir={DIR} onClose={noop} onChanged={noop} />,
  modelpicker: () => card(<><h2>Choose your video model</h2><p className="sub">Recommended models first, everything else behind All models.</p><div style={{ width: 360 }}><ModelPicker catalog={pickerCatalog} value="bytedance/seedance-2" label="Model" onChange={noop} onRefresh={noop} /></div></>),
  modelchoice: () => card(<><h2>Choose your picture model</h2><p className="sub">Choosing one fixes it for the whole project, which keeps your characters looking the same in every picture.</p><ModelChoice dir={DIR} kind="image" /></>, 560),
  ready: () => <ReadinessSheet dir={DIR} onClose={noop} onGo={noop} />,
  pacing: () => <PacingSheet dir={DIR} onClose={noop} onGo={noop} />,
  givenmodel: () => card(<GivenToModel dir={DIR} inputs={[{ role: "first_frame", label: "Keyframe S01-02", path: "s1.png", sent: true }, { role: "reference", label: "Sarah, front view", path: "s2.png", sent: true }, { role: "reference", label: "Kitchen, master", path: "s4.png", sent: true }, { role: "audio", label: "Sarah's recording", path: null, sent: true }] as never} />, 520),
  soundplan: () => <SoundPlan dir={DIR} onClose={noop} onGo={noop} />,
  sets3d: () => <div style={{ width: "min(1240px, 100vw)", height: 900, display: "flex", background: "#090b0f" }}><SetBuilder dir={DIR} onClose={noop} /></div>,
  directorcam: () => <div style={{ width: "min(1240px, 100vw)", height: 900, display: "flex", background: "#090b0f" }}><DirectorCam dir={DIR} onClose={noop} /></div>,
  cutouts: () => <div style={{ width: "min(1240px, 100vw)", height: 900, display: "flex", background: "#090b0f" }}><CutoutStudio dir={DIR} onClose={noop} /></div>,
  compose: () => card(<ComposeTab dir={DIR} shot="S01-01" keys={keys} />, 460),
};
function CompareLazy() {
  const versions = [take("t1", "S01-03", 1), take("t2", "S01-03", 2, { model: "wan/3-0-video", cost: 22 })] as never[];
  return <TakeCompare left={versions[0]} right={versions[1]} src={(v: { output: string | null }) => (v.output ? `${DIR}/${v.output}` : null)} busy={false} locked={false} onUse={noop} onSwap={noop} />;
}

document.body.classList.add("docshot");
const root = createRoot(document.getElementById("root")!);
root.render(scenes[scene] ? scenes[scene]() : <p>Unknown scene: {scene}</p>);

// ---------------------------------------------------------------- scripted steps, then report the size of the page for the screenshot
const press = (text: string) => { const b = [...document.querySelectorAll("button, summary, [role=tab]")].find((e) => (e.textContent ?? "").trim().toLowerCase().startsWith(text.toLowerCase())); (b as HTMLElement | undefined)?.click(); };
setTimeout(() => {
  const pick = q.get("select");                                                                 // &select=<value> chooses that option in the screen's first drop-down (a set, say)
  const sel = document.querySelector("select");
  if (pick && sel) { Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, "value")!.set!.call(sel, pick); sel.dispatchEvent(new Event("change", { bubbles: true })); }
  q.getAll("click").forEach((t, i) => setTimeout(() => press(t), i * 350));                 // one after another, so the screen can update between them
  const css = q.get("clickcss");
  if (css) (document.querySelector(css) as HTMLElement | null)?.click();
  const drag = q.get("drag");
  if (drag) {
    const [x0, y0, x1, y1] = drag.split(",").map(Number);
    const stage = document.querySelector(".hf-stage") as HTMLElement | null;
    if (stage) {
      const r = stage.getBoundingClientRect();
      const ev = (type: string, x: number, y: number) => stage.dispatchEvent(new PointerEvent(type, { bubbles: true, clientX: r.left + x * r.width, clientY: r.top + y * r.height, pointerId: 1 }));
      ev("pointerdown", x0, y0);                                                     // spaced out, so the screen can update between them as it does for a real mouse
      setTimeout(() => ev("pointermove", x1, y1), 120);
      setTimeout(() => ev("pointerup", x1, y1), 260);
    }
  }
}, 900);
setTimeout(() => {
  const rootEl = document.getElementById("root")!;
  const sheet = document.querySelector(".sheet") as HTMLElement | null;
  const first = (sheet ?? rootEl.firstElementChild) as HTMLElement | null;
  const w = Math.ceil((first?.getBoundingClientRect().width ?? 1000) + 48);
  const outer = (document.querySelector(".overlay") ?? first) as HTMLElement | null;
  const h = Math.ceil(outer?.getBoundingClientRect().height ?? rootEl.getBoundingClientRect().height);
  const full = scene === "home" || scene === "film" || scene === "studio";                               // whole-window screens are photographed at a desktop window size
  document.title = full ? "1440,900" : `${w},${h}`;
}, 2600);
