/** "Your first film": the order a film is made in, worked out from what the film already has. No screen code, nothing here spends or changes anything. */
import type { FilmProgress } from "./api";

export type StudioSheet = "presets" | "smart" | "color" | "motion" | "polish" | import("./FilmRail").ToolId;           // "polish" is the three finishing sheets one after another
export type StepId = "story" | "materials" | "cast" | "look" | "voices" | "cut" | "grade" | "titles" | "shots" | "pictures" | "video" | "sound" | "export";
export type StepStatus = "done" | "next" | "later";
export type Step = {
  id: StepId; title: string; what: string; cost: "free" | "asks" | "your_recordings";
  costWords: string;                           // what it costs, in words: always honest, always says the price is shown first when there is one
  status: StepStatus; optional: boolean;
  go: `studio:${StudioSheet}` | "story" | "cast" | "shots" | "make" | "export" | "voice" | "sound" | "materials";          // where the "Take me there" button goes
  detail: string;                              // how far along it is, in words ("2 of 3 lines have a voice")
};

export type Facts = {
  progress: FilmProgress | null;
  voices: { people: number; recorded: number } | null;          // the Voiceover status; null until read
  sound: { cues: number; assets: number } | null;                // the planned sound; null until read
  pro: boolean;                                                  // Simple mode does the breakdown for you
  exported: boolean;                                             // an export file exists
};

const plural = (n: number, w: string) => `${n} ${w}${n === 1 ? "" : "s"}`;

/** All steps, with each one's state. The first step that is not done and not optional is "next"; the ones after it are "later"; optional steps never block. */
export function buildSteps(f: Facts): Step[] {
  const p = f.progress, v = f.voices, s = f.sound;
  const castDone = !!p && p.cast.characters > 0 && p.cast.style;
  const voicesDone = !!v && (v.people === 0 || v.recorded >= v.people);
  const shotsDone = !!p && p.shots.count > 0;
  const picsDone = !!p && p.make.shots > 0 && p.make.keyframe > 0;
  const videoDone = !!p && p.make.shots > 0 && p.make.video > 0;
  const raw: Omit<Step, "status">[] = [
    { id: "story", title: "Your story, locked", what: "Bring a screenplay or an idea. When it is final, lock it: everything else is made from that exact version.", cost: "free", costWords: "Free", optional: false, go: "story",
      detail: !p ? "" : p.story.locked ? "Locked." : p.story.as_is ? "Using it as it is: lock it when you are ready." : "Not locked yet." },
    { id: "materials", title: "Your own materials (optional)", what: "Bring a storyboard, character and place sheets, a shot list or notes you already have. They guide the shots and the pictures: nothing is added until you have seen where each piece goes.", cost: "free",
      costWords: "Free. Nothing is bought or sent", optional: true, go: "materials", detail: !p ? "" : p.cast.pictures ? "Some of your own pictures are already in." : "Skip it if you only have a script." },
    { id: "cast", title: "Cast & World", what: "The people, the places and one visual style, so every shot looks like the same film. The writing helper can suggest details (its price is shown first).", cost: "free", costWords: "Free",
      optional: false, go: "cast", detail: !p ? "" : `${plural(p.cast.characters, "character")}, ${plural(p.cast.places, "place")}${p.cast.style ? ", a style chosen" : ", no style yet"}.` },
    { id: "look", title: "Start from a preset (optional)", what: "A preset sets the look, the acting, the colour, the editing style and the frame shape in one go, from a ready-made list (a vertical social version, a micro-drama, a storybook). You see every change first and can undo it.", cost: "free",
      costWords: "Free. Nothing is made or bought, and it can be undone", optional: true, go: "studio:presets", detail: "Skip it to choose each thing yourself." },
    { id: "voices", title: "Voices", what: "Give each speaking character a voice: record your own lines (free), or choose a voice from your ElevenLabs library (free to choose; speaking a line shows its price first). Voice a whole scene with one price and a cap.",
      cost: "your_recordings", costWords: "Free with your own recordings. Speaking lines: price shown first", optional: false, go: "voice",
      detail: !v ? "" : v.people === 0 ? "Nobody speaks yet." : `${v.recorded} of ${plural(v.people, "line")} have a voice.` },
    ...(f.pro ? [{ id: "shots" as const, title: "Shots", what: "The story is broken into shots you can change: framing, length, who is in them.", cost: "free" as const, costWords: "Free", optional: false, go: "shots" as const,
      detail: !p ? "" : p.shots.count ? `${plural(p.shots.count, "shot")}.` : "Not broken into shots yet." }] : []),
    { id: "pictures", title: "Pictures: test one shot first", what: "Make the picture for one shot, look at it, then do the rest. A picture is a few cents; the price is shown and confirmed first.", cost: "asks",
      costWords: "Asks first: the price is shown before anything is made", optional: false, go: "make", detail: !p ? "" : p.make.shots ? `${p.make.keyframe} of ${plural(p.make.shots, "shot")} have a picture.` : "No shots to make yet." },
    { id: "video", title: "Video: test one shot first", what: "Bring one picture to life, check that the face, the mouth and the voice are right, then make the others. This is the main cost.", cost: "asks",
      costWords: "Asks first: the price is shown before anything is made", optional: false, go: "make", detail: !p ? "" : p.make.shots ? `${p.make.video} of ${plural(p.make.shots, "shot")} have video.` : "No shots to make yet." },
    { id: "sound", title: "Sound and music (optional)", what: "Plan each scene's sound: free quick ideas, or the sound director (price first). Your own sounds and music are free to import. Making new sound with AI shows its price first.", cost: "free",
      costWords: "Free to plan. AI-made sound asks first", optional: true, go: "sound", detail: !s ? "" : s.cues ? `${plural(s.cues, "planned sound")}.` : s.assets ? `${plural(s.assets, "sound")} in the library, none planned yet.` : "Nothing yet. You can skip this." },
    { id: "cut", title: "Tighten the cut (optional)", what: "The Smart Editor reads your cut and suggests where a pause could be trimmed or a reaction left to breathe. Each suggestion says why, and shows before and after; nothing changes until you accept it.", cost: "free",
      costWords: "Free. Nothing is made or bought, and it can be undone", optional: true, go: "studio:smart", detail: "After the video." },
    { id: "grade", title: "Colour (optional)", what: "Give the whole film, a scene or one shot a grade: exposure, contrast, tint, or a look file (.cube). See before and after, and undo it.", cost: "free",
      costWords: "Free. Nothing is made or bought, and it can be undone", optional: true, go: "studio:color", detail: "After the video." },
    { id: "titles", title: "Titles and lower thirds (optional)", what: "Add a title card, a name under someone who has just appeared, a place and time, a quote or an end card. Type the words and see how it looks first.", cost: "free",
      costWords: "Free. They are drawn by FilmCrafter, nothing is generated", optional: true, go: "studio:motion", detail: "After the video." },
    { id: "export", title: "Export the film", what: "Put the pictures, video, voices and sound together into one file, or hand it to an editor.", cost: "free", costWords: "Free", optional: false, go: "export",
      detail: f.exported ? "Exported." : videoDone ? "Ready." : "After the video." },
  ];
  const doneOf: Record<StepId, boolean> = { look: false, cut: false, grade: false, titles: false, story: !!p && p.story.locked, materials: false, cast: castDone, voices: voicesDone, shots: shotsDone, pictures: picsDone, video: videoDone, sound: !!s && s.cues > 0, export: f.exported };
  let found = false;
  return raw.map((r) => {
    const done = doneOf[r.id];
    let status: StepStatus = done ? "done" : "later";
    if (!done && !r.optional && !found) { status = "next"; found = true; }
    return { ...r, status };
  });
}

export const nextStep = (steps: Step[]): Step | null => steps.find((s) => s.status === "next") ?? null;
export const doneCount = (steps: Step[]) => steps.filter((s) => s.status === "done" && !s.optional).length;
export const requiredCount = (steps: Step[]) => steps.filter((s) => !s.optional).length;

const KEY = (dir: string) => `pf-first-film:${dir}`;
/** Whether the guide has been shown (or dismissed) for this film. Per film, in this browser only; everything works without it. */
export const guideSeen = (dir: string): boolean => { try { return localStorage.getItem(KEY(dir)) === "1"; } catch { return true; } };
export const markGuideSeen = (dir: string) => { try { localStorage.setItem(KEY(dir), "1"); } catch { /* optional */ } };
