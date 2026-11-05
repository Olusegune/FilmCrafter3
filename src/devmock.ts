// Browser-only UI preview (`?mock`): answers the app's backend calls with local sample data so the
// screens can be checked outside the desktop shell. Never active inside the Tauri app.
import { mockIPC, mockWindows } from "@tauri-apps/api/mocks";

export async function installMock() {
  // Sample data lives outside public/ so it never ships in the app bundle.
  const url = (f: string) => new URL(`../mock-data/${f}`, import.meta.url).href;
  const [song_map, production, preview, concepts] = await Promise.all(["songmap.json", "production.json", "preview.json", "concepts.json"].map((n) => fetch(url(n)).then((r) => r.json())));
  const noScript = new URLSearchParams(location.search).get("mock") === "noscript";
  const now = Date.now() / 1000;
  const jobs = [
    { id: "j1", shot_id: "S01-01", plan: "production", provider: "fal", model: preview.manifest.model, state: "submitted", overrides: {}, provider_job_id: "r1", output: null, error: null, cost: null, created: now - 130, updated: now - 5, submitted: now - 95, detail: "in progress", progress: 0.55, attempts: 1, shot_start: 0, shot_end: 2 },
    { id: "j5", shot_id: "S01-05", plan: "production", provider: "fal", model: preview.manifest.model, state: "submitted", overrides: {}, provider_job_id: "r5", output: null, error: null, cost: null, created: now - 125, updated: now - 5, submitted: now - 20, attempts: 1, shot_start: 8.5, shot_end: 11 },
    { id: "j6", shot_id: "S01-06", plan: "production", provider: "fal", model: preview.manifest.model, state: "queued", overrides: {}, provider_job_id: null, output: null, error: null, cost: null, created: now - 120, updated: now - 120, estimate_usd: 1.2, attempts: 0, shot_start: 11, shot_end: 13 },
    { id: "j2", shot_id: "S01-02", plan: "production", provider: "fal", model: preview.manifest.model, state: "failed", overrides: {}, provider_job_id: "r2", output: null, error: "422: Prompt was flagged by the provider's content filter.", cost: null, created: now, updated: now, attempts: 1, shot_start: 2, shot_end: 4.5 },
    { id: "j4", shot_id: "S01-04", plan: "production", provider: "fal", model: preview.manifest.model, state: "ready", overrides: {}, provider_job_id: "r4", output: "x.mp4", error: null, cost: null, created: now - 260, updated: now - 140, submitted: now - 200, attempts: 1, shot_start: 6.5, shot_end: 8.5,
      review: { reviewed: true, status: "needs_attention", summary: "Sege is missing his beard and the suitcase is in the wrong place.", visual: { model: "gpt-5" },
        issues: [{ kind: "character", severity: "major", detail: "Sege has no beard; the sheet shows a trimmed beard.", fix: "Sege has a neatly trimmed beard." },
                 { kind: "artifact", severity: "minor", detail: "Left hand has six fingers briefly.", fix: "Hands have five fingers." }],
        fixes: ["Sege has a neatly trimmed beard.", "Hands have five fingers."] } },
    { id: "j8", shot_id: "S01-04", plan: "production", provider: "fal", model: preview.manifest.model, state: "ready", overrides: {}, provider_job_id: "r8", output: "y.mp4", error: null, cost: null, created: now - 30, updated: now - 10, submitted: now - 90, attempts: 1, shot_start: 6.5, shot_end: 8.5, fix_notes: ["Sege has a neatly trimmed beard."],
      review: { reviewed: true, status: "good", summary: "Sege now has his trimmed beard and the suitcase is where the script puts it.", visual: { model: "gpt-5" }, issues: [], fixes: [] } },
    { id: "j9", shot_id: "S01-07", plan: "production", provider: "fal", model: preview.manifest.model, state: "ready", overrides: {}, provider_job_id: "r9", output: "x.mp4", error: null, cost: null, created: now - 300, updated: now - 240, submitted: now - 290, attempts: 1, shot_start: 14, shot_end: 16,
      review: { reviewed: true, status: "needs_attention", summary: "The room is too bright for the late-night mood.", visual: { model: "gpt-5" }, issues: [{ kind: "look", severity: "major", detail: "Lighting is daylight; the shot should be lit by one lamp.", fix: "One warm lamp, dark room." }], fixes: ["One warm lamp, dark room."] } },
    { id: "j10", shot_id: "S01-07", plan: "production", provider: "fal", model: preview.manifest.model, state: "ready", overrides: {}, provider_job_id: "r10", output: "y.mp4", error: null, cost: null, created: now - 20, updated: now - 8, submitted: now - 80, attempts: 1, shot_start: 14, shot_end: 16, fix_notes: ["One warm lamp, dark room."],
      review: { reviewed: true, status: "minor", summary: "Better, but the lamp flickers oddly at the end.", visual: { model: "gpt-5" }, issues: [{ kind: "artifact", severity: "minor", detail: "The lamp flickers unnaturally in the last second.", fix: "Steady lamp light." }], fixes: [] } },
    { id: "j3", shot_id: "S01-03", plan: "production", provider: "kie", model: "bytedance/seedance-2", state: "uncertain", overrides: {}, provider_job_id: null, output: null, error: "The app closed while this shot was being sent. It may already be rendering (and billed). Check your provider dashboard before retrying.", cost: null, created: now, updated: now, attempts: 1, shot_start: 4.5, shot_end: 6.5 },
  ];
  const project = { title: "Exit Plan", state: "analyzed", song: "song.wav", aspect_ratio: "2.39:1", artist: "Uncle Sege", look: { style: "feature-3d", notes: "Match the character sheet exactly." }, lyrics: "lyrics.txt", script: "script.pdf",
    references: { cast: { Sege: "assets/refs/character_sege.png", Amara: "assets/refs/character_amara.png" } } };
  const shots = (production.scenes as { number: number; shots: { id: string; start: number; end: number; framing?: string; description?: string; performers?: string[] }[] }[])
    .flatMap((sc) => sc.shots.map((sh) => ({ id: sh.id, scene: sc.number, start: sh.start, end: sh.end, framing: sh.framing, beat: sh.description ?? "", performers: sh.performers ?? [],
      status: "planned", locked: false, approved: null, thumb_src: null, thumb_source: "placeholder", preview: null, keyframe: null, versions: [], references: [] })));
  const withKf = shots.map((sh) => sh.id === "S01-04" ? { ...sh, keyframe: "assets/kf.png", status: "ready", approved: "j4",
    versions: [{ id: "j4", n: 1, state: "ready", provider: "fal", model: preview.manifest.model, output: "x.mp4", kind: "video", created: now, approved: true, media_kind: "video" }] } : sh);
  const TRANS: Record<string, [string, number | null]> = { "01-02": ["dissolve", null], "01-04": ["wipe_right", 0.8], "02-01": ["whip_left", null] };   // a few cuts that are not plain cuts, so the timeline shows handles in use
  const board = { plan: "production", shots: withKf.map((s) => { const t = Object.entries(TRANS).find(([k]) => s.id.endsWith(k)); return t ? { ...s, transition: t[1][0], transition_s: t[1][1] } : s; }), library: { items: [], assign: { project: [], scenes: {}, shots: {} } } };
  // Sound layers (Takes panel): kept in memory so ticking, volume, delete, restore and split can be tried in the preview
  const sound: Record<string, { split: boolean; layers: Record<string, { on: boolean; gain: number | null; removed: boolean }> }> = {};
  const soundOf = (shot: string) => {
    const e = (sound[shot] ??= { split: false, layers: { song: { on: true, gain: null, removed: false }, all: { on: false, gain: 1, removed: false } } });
    const ids = e.split ? ["song", "voice", "other"] : ["song", "all"];
    const label: Record<string, string> = { song: "Song", all: "Sound from the video model", voice: "Voices", other: "Sound effects and music" };
    const anyTake = ids.some((i) => i !== "song" && e.layers[i].on && !e.layers[i].removed);
    return { shot, native: false, take: { id: "j4", model: "seedance-2", output: "x.mp4" }, has_audio: true, silent: false, split: e.split, changed: Object.keys(soundTouched).includes(shot),
      layers: ids.map((i) => ({ id: i, label: label[i], on: e.layers[i].on && !e.layers[i].removed, gain: e.layers[i].gain, removed: e.layers[i].removed,
        ...(i === "song" ? { effective_gain: e.layers[i].gain ?? (anyTake ? 0.4 : 1), auto: e.layers[i].gain === null } : {}) })) };
  };
  const soundTouched: Record<string, true> = {};
  const mockShotLooks: Record<string, string> = {};
  const soundCall = (a: { action?: string; data?: Record<string, unknown> }) => {
    const d = (a.data ?? {}) as { shot?: string; layer?: string; on?: boolean; gain?: number | null };
    if (a.action === "overview") return soundTouched;
    if (a.action === "levels") {
      const v = soundOf((a.data as { shot?: string } | undefined)?.shot ?? "S01-04");
      const takeOn = v.layers.some((l) => l.id !== "song" && l.on);
      const layers: Record<string, number | null> = {};
      for (const l of v.layers) layers[l.id] = l.on ? (l.id === "song" ? (takeOn ? -21.5 : -13.5) : -21.9 + 20 * Math.log10(l.gain ?? 1)) : null;
      return { shot: v.shot, layers, mix_db: takeOn ? -18.4 : -13.5, peak_db: takeOn ? -7.9 : -10.4, seconds: 2.5 };
    }
    const shot = d.shot ?? "S01-04";
    soundOf(shot);
    const e = sound[shot];
    if (a.action === "reset") { delete sound[shot]; delete soundTouched[shot]; return soundOf(shot); }
    if (a.action === "split") { e.split = true; e.layers.voice = { on: true, gain: 1, removed: false }; e.layers.other = { on: true, gain: 1, removed: false }; soundTouched[shot] = true; }
    if (d.layer && e.layers[d.layer]) {
      const L = e.layers[d.layer];
      if (a.action === "set") { if (d.on !== undefined) { L.on = d.on; if (d.on) L.removed = false; } if ("gain" in d) L.gain = d.gain ?? null; }
      if (a.action === "delete") { L.on = false; L.removed = true; }
      if (a.action === "restore") { L.on = true; L.removed = false; }
      soundTouched[shot] = true;
    }
    return soundOf(shot);
  };
  mockWindows("main");
  let overlays: Record<string, unknown>[] = [
        { id: "o1", kind: "text", text: "EXIT PLAN", x: 0.5, y: 0.5, width: 0.5, start: 0, end: 6, anim: "zoom_in", color: "#ffffff", enabled: true, placed: true, keys: [{ t: 1 }, { t: 4 }] },
        { id: "o2", kind: "shape", shape: "line", x: 0.5, y: 0.6, width: 0.4, height: 0.006, color: "#ffd166", start: 1, end: 6, anim: "wipe", enabled: true, placed: true },
        { id: "o3", kind: "icon", icon: "star", x: 0.8, y: 0.2, width: 0.1, color: "#ffd166", start: 8, end: 12, anim: "pop", name: "Star burst", enabled: true, placed: true },
        { id: "o4", kind: "text", text: "Come downstairs!", x: 0.5, y: 0.8, width: 0.6, start: 14, end: 19, anim: "typewriter", color: "#ffffff", enabled: false, placed: true }];   // layers live in memory so adding, moving, trimming and hiding can be tried in the preview
  mockIPC((cmd, args) => {
    const a = (args ?? {}) as { action?: string; data?: Record<string, unknown> };
    switch (cmd) {
      case "agent_studio": {
        const stages = ["story", "direction", "storyboard", "first_scene", "scenes", "audio", "preview", "export"].map((id, i) => ({ id, label: ["Story & shot plan", "Cast & visual direction", "Storyboard & keyframes", "First scene preview", "Remaining scenes", "Voices & sound", "Preview cut", "Final review & export"][i], state: i === 0 ? "needs_approval" : "not_started" }));
        return { version: 1, paused: false, current: "story", updated: Date.now() / 1000,
          brief: { story: "A young man faces the memories he has avoided and chooses to come home.", style: "Cinematic storybook", duration: "3–4 minutes", aspect: "2.39:1", budget_limit: 30, checkin_mode: "balanced", checkpoints: ["story", "direction", "first_scene", "preview"] },
          stages, approvals: [], revisions: [], activity: [{ id: "a1", at: Date.now() / 1000, kind: "plan", text: "Production plan prepared. No paid work was submitted." }], existing: { scenes: production.scenes.length, shots: production.scenes.flatMap((s: { shots: unknown[] }) => s.shots).length }, spending: { actual: 3.33, committed: 0, limit: 30, pricing_known: true }, jobs: { ready: 1, working: 0, failed: 0 } };
      }
      case "director_chat": {
        if (a.action === "proposals") return [];
        if (a.action === "turn") return { reply: "Your plan is coherent. I would preserve approved shots and focus next on the missing keyframes.", model: "gpt-5", steps: [], proposals: [] };
        return { proposal: { ...(a.data ?? {}), state: a.action === "apply" ? "applied" : "rejected" } };
      }
      case "director_style": return { current: null, styles: [
        { id: "ryan-coogler", name: "Ryan Coogler", region: "North America", origin: "USA", known_for: "Warm community, intimate faces, mythic scale", palette: ["gold", "green"], traits: { camera: "Long moving takes through lived-in places; steady close-ups for feeling.", light: "Warm natural light on skin and golden-hour exteriors.", editing: "Cut for the emotional beat.", movement: "Grounded physical action." } },
        { id: "christopher-nolan", name: "Christopher Nolan", region: "North America", origin: "UK and USA", known_for: "Large-format scale and temporal precision", palette: ["steel blue", "amber"], traits: { camera: "Large-format wides, controlled dolly movement and deep staging.", light: "Hard directional daylight and strong practical sources.", editing: "Parallel action converges with exact timing.", movement: "Physical weight and purpose." } },
        { id: "kemi-adetiba", name: "Kemi Adetiba", region: "Africa", origin: "Nigeria", known_for: "Commanding portraits, glamour and dramatic power", palette: ["gold", "black"], traits: { camera: "Low heroic angles and polished close-ups.", light: "Warm skin, strong rim light and jewel-toned interiors." } }
      ] };
      case "library": return a.action === "storyboard" ? board : a.action === "pending_keyframes" ? {} : a.action === "thumbs" ? {} : null;
      case "overlays": {
        const x = (a.data ?? {}) as Record<string, unknown> & { id?: string };
        if (a.action === "update") overlays = overlays.map((o) => (o.id === x.id ? { ...o, ...x } : o));
        else if (a.action === "add") overlays = [...overlays, { id: `o${overlays.length + 5}`, kind: "text", text: "Your text", enabled: true, placed: true, anim: "fade", ...x }];
        else if (a.action === "remove") overlays = overlays.filter((o) => o.id !== x.id);
        return a.action === "history" ? { can_undo: false, can_redo: false } : overlays;
      }
      case "golden": if (a.action === "changes") return { has_take: true, same: false, take: { id: "j4", model: "kling", created: 1 }, note: "", changes: [
        { kind: "first_frame", text: "The keyframe is no longer the first frame (it goes as a reference picture)." }, { kind: "audio", text: "The voice or sung line is now sent for the mouth to follow." },
        { kind: "prompt_removed", text: "Sege lifts his head toward the door." }, { kind: "prompt_added", text: "Sege throws the door open, breath held." }] };
        return null;
      case "frames": if (a.action === "get") return { "S01-04": { start: "assets/kf.png", start_mode: "keyframe", end: null, end_mode: "own", end_state: "", next: "S01-05", prev: "S01-03", next_has_start: false } };
        if (a.action === "options") return { "S01-04": { chosen: null, options: [], active: 0 } };
        if (a.action === "support") return { title: "Seedance 2 Reference to Video", shots: { "S01-04": { model: "bytedance/seedance-2.0/image-to-video", swapped: true, supports_end: true, proven: false, end: null } } };
        if (a.action === "extend_info") return { shot: "S01-04", can_extend: true, advice: ["This shot changes who or what is on screen. Set an end frame (Frames, “where it lands”) with the changed look: a model that is shown where the shot must end completes the change, which extending alone will not."],
          shot_seconds: 12, take_seconds: 8, short_seconds: 4, model_longest: 8, take: "j4", source_take: "j4", provider: "fal", model: "bytedance/seedance-2.0/reference-to-video", suggest_seconds: 4, will_cover: 12, estimate_usd: 0.9, lip_synced: false }; return null;
      case "supervisor": case "media": return a.action === "list" ? [] : null;
      case "shot_sound": return soundCall(a);
      case "routing": if (a.action === "pick") return { provider: "fal", model: "bytedance/seedance-2.0/reference-to-video", label: "Seedance 2 Reference to Video" };
        return a.action === "models" ? { video: [
        { label: "Kling", provider: "fal", model: "kling", price_usd: 0.7, verified: true }, { label: "Veo 3.1", provider: "fal", model: "veo", price_usd: 0.75, verified: true },
        { label: "Seedance 2", provider: "kie", model: "bytedance/seedance-2", price_usd: 0.82, verified: true }, { label: "MiniMax Hailuo 2.3", provider: "fal", model: "hailuo", price_usd: null, verified: true }] } : null;
      case "performance": return { profiles: [{ id: "natural", label: "Natural", blurb: "Truthful, everyday acting. Small motivated gestures; the default." },
        { id: "expressive", label: "Expressive", blurb: "Open and readable. Clear faces and gestures, still grounded." }], default: "natural", scenes: {}, characters: {}, shots: {}, set: false, dance: {} };
      case "camera": if (a.action === "vocab") return Object.fromEntries(["size", "angle", "movement", "lens", "lighting", "focus", "energy"].map((g) => [g, { label: g[0].toUpperCase() + g.slice(1), terms: [{ id: "a", label: "Option A", video_only: false }, { id: "b", label: "Option B", video_only: false }] }]));
        if (a.action === "get") return { picked: {}, detected: {}, director: { energy: "gentle" }, effective: { framing: "extreme close-up", lens: "", movement: "" }, changed_since_take: false };
        if (a.action === "suggest") return { count: 2, note: "", shots: [
        { shot: "S01-04", emotion: "dread", intensity: 8, why: "Fear and unease read in deep shadow and a camera that creeps closer.", proposals: [{ group: "lighting", term: "lowkey", label: "Low key / chiaroscuro", wording: "" }, { group: "movement", term: "push", label: "Slow push in", wording: "" }, { group: "angle", term: "dutch", label: "Tilted (Dutch)", wording: "" }] },
        { shot: "S02-02", emotion: "joy", intensity: 6, why: "Joy reads in warm, open light and a camera that floats.", proposals: [{ group: "lighting", term: "golden", label: "Golden hour", wording: "" }] }] };
        return a.action === "suggest_apply" ? { changed: [] } : null;
      case "direction_library": return a.action === "list" ? { directions: [{ id: "french-new-wave", name: "French New Wave", region: "Europe", origin: "France · 1960s cinema", tags: ["romantic"], genres: [], bpm: [90, 140], energy: "mid", summary: "Jump cuts, street shooting, lovers talking in cafés and running through Paris; cool and free.", camera: "", light: "", palette: ["amber", "teal", "gold"], editing: "", movement: "", design: "", look: "", acting: "" },
        { id: "americana-road", name: "Americana Road Movie", region: "Americas", origin: "USA · road movie", tags: ["melancholic"], genres: [], bpm: [90, 140], energy: "mid", summary: "Open highways, diners, motel neon and dust; freedom and loneliness in wide screen.", camera: "", light: "", palette: ["amber", "teal", "gold"], editing: "", movement: "", design: "", look: "", acting: "" },
        { id: "one-take", name: "One-Take Performance", region: "Global", origin: "Music video tradition", tags: ["intimate"], genres: [], bpm: [90, 140], energy: "mid", summary: "The whole song as one continuous move around the performer: no cuts, pure presence.", camera: "", light: "", palette: ["amber", "teal", "gold"], editing: "", movement: "", design: "", look: "", acting: "" },
        { id: "stop-motion", name: "Handmade Stop Motion", region: "Europe", origin: "Craft animation tradition", tags: ["gentle"], genres: [], bpm: [90, 140], energy: "mid", summary: "Felt, clay and paper worlds built by hand; visible fingerprints and charm.", camera: "", light: "", palette: ["amber", "teal", "gold"], editing: "", movement: "", design: "", look: "", acting: "" },
        { id: "wuxia", name: "Wuxia Poetry", region: "Asia", origin: "China · martial-arts cinema", tags: ["romantic"], genres: [], bpm: [90, 140], energy: "mid", summary: "Swordplay as dance: bamboo forests, flowing silk, colour-coded chapters and weightless motion.", camera: "", light: "", palette: ["amber", "teal", "gold"], editing: "", movement: "", design: "", look: "", acting: "" },
        { id: "lagos-nights", name: "Lagos Nights", region: "Africa", origin: "Nigeria · Afrobeats video", tags: ["romantic","joyful"], genres: [], bpm: [90, 140], energy: "mid", summary: "Warm, glossy city nights: rooftops, danfo lights, fashion-forward friends, easy swagger and romance.", camera: "", light: "", palette: ["amber", "teal", "gold"], editing: "", movement: "", design: "", look: "", acting: "" }], current: null } : a.action === "match" ? { song: { bpm: 120, energy: "mid", moods: ["building", "intimate"] }, matches: ["french-new-wave", "americana-road", "one-take", "stop-motion", "wuxia", "lagos-nights"].map((id, i) => ({ id, score: 0.8 - i * 0.05, why: ["tempo 120 BPM fits", "mid energy", "mood: romantic"] })) } : null;
      case "fidelity": {
        const rep = { width: 1536, height: 1024, aspect: "3:2", format: "PNG", analysed_at: "1536×1024", reduced: false, verdict: "optional", action: "Optional: Clean Enhance can tidy this up.", low_resolution: false,
          not_assessed: ["Faces and hands (needs an image model)", "Whether the picture suits the story"],
          rows: [{ id: "sharpness", label: "Sharpness", level: "Moderate", value: 0.24, confidence: "high", note: "The sharpest parts are only gently defined.", depth_of_field: false },
                 { id: "noise", label: "Noise", level: "Low", value: 0.8, confidence: "high", note: "Clean." }] };
        if (a.action === "check") return { shot: "S01-04", ref: "project:keyframes/S01-04.png", report: rep };
        if (a.action === "enhance") return { id: "f1", shot: "S01-04", source: "project:keyframes/S01-04.png", output: "project:fidelity/S01-04_f1_clean.png", strength: 0.5, state: "ready", size: [1536, 1024], source_path: "x.png", output_path: "y.png", before_report: rep, after_report: { ...rep, verdict: "ok" } };
        if (a.action === "upscale_status") return { available: false, models: [], help: "Local upscaling needs the free Real-ESRGAN ncnn-vulkan tool. Nothing is downloaded for you." };
        return a.action === "status" ? { items: [] } : { shot: "S01-04" };
      }
      case "upscale": {
        if (a.action === "tools") { const media = (a.data as { media?: string } | undefined)?.media;
          return { tools: [
            { id: "kie-topaz-image", provider: "kie", model: "topaz/image-upscale", media: "image", label: "Topaz · picture", blurb: "Topaz Gigapixel quality: the usual first choice for faces and detail. 2× or 4×.", ready: true, factors: [2, 4] },
            { id: "kie-recraft-image", provider: "kie", model: "recraft/crisp-upscale", media: "image", label: "Recraft · crisp", blurb: "Clean, crisp edges; good for illustration and 3D renders.", ready: true, factors: [2, 4] },
            { id: "kie-topaz-video", provider: "kie", model: "topaz/video-upscale", media: "video", label: "Topaz · video", blurb: "Topaz Video AI quality for a finished take. 2× or 4×.", ready: true, factors: [2, 4] },
            { id: "fal-clarity-image", provider: "fal", model: "fal-ai/clarity-upscaler", media: "image", label: "Clarity · picture (fal)", blurb: "Adds fine detail while it enlarges.", ready: false, factors: [2, 4] },
          ].filter((t) => !media || t.media === media) }; }
        if (a.action === "status") return { runs: [], upscaled_keyframes: [] };
        return { id: "u1", state: "ready", kind: "keyframe", shot: "S01-04", output: "x.png", error: null, cost: null };
      }
      case "local_models": {
        if (a.action === "test") return { ok: true, model: "qwen2.5vl:7b", seconds: 1.8, answer: (a.data as { vision?: boolean })?.vision ? "Red on the left and blue on the right." : "ready", vision: !!(a.data as { vision?: boolean })?.vision, saw: true };
        const rec = (name: string, role: string, size_gb: number, why: string, fit: string, installed = false) => ({ name, role, size_gb, why, installed, fit, fit_note: "" });
        return { installed: { ollama: "C:/Ollama", lmstudio: null, lms: null }, brain: { provider: "ollama", model: "qwen2.5vl:7b", vision_model: "qwen2.5vl:7b" },
          hardware: { summary: "NVIDIA GeForce RTX 3060 with 12 GB of video memory, 34.2 GB memory", ram_gb: 34.2, disk_free_gb: 412.6, model_gb: 12, kind: "gpu", gpus: [], gpu: null },
          ollama: { running: true, models: [{ name: "qwen2.5vl:7b", size_gb: 6, vision: true, fit: "great" }, { name: "llama3.1:8b", size_gb: 4.9, vision: false, fit: "great" }] },
          ollama_loaded: [{ name: "qwen2.5vl:7b", gb: 7.4, gpu_gb: 7.4 }], lmstudio: { running: false, models: [] }, comfyui: { connected: true, device: "NVIDIA GeForce RTX 3060", workflows: [] },
          recommended: [rec("gemma3:12b", "both", 8.1, "Strong writing, and it can see images.", "great"), rec("llama3.2-vision:11b", "both", 7.8, "Good at describing pictures; plans well too.", "great"),
            rec("qwen2.5vl:7b", "both", 6, "Plans and sees: directions, Director, keyframe and continuity checks.", "great", true), rec("qwen3:14b", "planning", 9.3, "Better plans and structure than the 8B; can't see images.", "great"),
            rec("mistral-small3.1", "both", 15, "Plans and sees with a very good eye; needs a big graphics card.", "slow"), rec("gemma3:27b", "both", 17, "The best local writer here, and it sees images; needs a big graphics card.", "slow")] };
      }
      case "comfy_setup": {
        if (a.action === "health") return { url: "http://127.0.0.1:8188", connected: true, version: "0.3.60", device: "NVIDIA GeForce RTX 3060", vram_gb: 12, vram_free_gb: 4.6, running: 0, waiting: 0,
          advice: ["Only 4.6 GB of the card is free: another program (often an Ollama model) is holding it. Settings → Models on this computer → Free memory."] };
        if (a.action === "test") return { ok: true, seconds: 6.4, url: "" };
        if (a.action === "detect") return { running: [{ url: "http://127.0.0.1:8188", device: "NVIDIA GeForce RTX 3060", vram_gb: 12, version: "0.3.60" }], installs: [], configured_url: "http://127.0.0.1:8188" };
        return { url: "http://127.0.0.1:8188", templates: [], workflows: [] };
      }
      case "compose": {
        if (a.action === "models") { const c = (model: string, title: string, rec: number | null = null) => ({ provider: "kie", model, title, category: "video", sees: true, text: false, rec, fresh: false });
          return { start_end: [c("bytedance/seedance-2", "Bytedance · Seedance 2.0", 0), c("bytedance/seedance-2-fast", "Bytedance · Seedance 2.0 Fast", 1), c("kling-3.0/video", "Kling · Kling 3.0", 2), c("hailuo/02-image-to-video-standard", "Hailuo · 02 Standard")],
            references: [c("bytedance/seedance-2", "Bytedance · Seedance 2.0", 0), c("happyhorse/reference-to-video", "HappyHorse · Reference to Video")], motion: [c("kling/motion-control-v3", "Kling · Kling 3.0 Motion Control", 0), c("kling/motion-control", "Kling · Kling 2.6 Motion Control", 1), c("wan/2-2-animate-move", "Wan · Animate Move")] }; }
        if (a.action === "queue_motion") return [];
        if (a.action === "library_list" || a.action === "library_rename" || a.action === "library_remove") { const px = (c: string) => `data:image/svg+xml;utf8,${encodeURIComponent(`<svg xmlns="http://www.w3.org/2000/svg" width="240" height="135"><rect width="240" height="135" fill="${c}"/><circle cx="120" cy="45" r="16" fill="#ffffff55"/><rect x="95" y="65" width="50" height="60" rx="14" fill="#ffffff44"/></svg>`)}`;
          return [{ id: "a1b2c3d4e5", name: "Slow waltz", seconds: 12.4, width: 1080, height: 1920, added: 2, thumb: px("#3b4a63") }, { id: "f6a7b8c9d0", name: "Chorus dance, big arms", seconds: 8, width: 1280, height: 720, added: 1, thumb: px("#63503b") }]; }
        if (a.action === "library_add") return { id: "a1b2c3d4e5", name: "Slow waltz", seconds: 12.4, width: 1080, height: 1920, added: 2, thumb: null, already: false };
        if (a.action === "library_use") return { shot: "S01-04", shot_seconds: 2, video: "media/dance.mp4", video_seconds: 12.4, image: "assets/kf.png", image_is_start: true, orientation: "video", quality: "pro", background: "video", note: "", notes: [], ready: true, missing: [], prompt: { mode: "auto", text: "", only: false } };
        if (a.action === "prompt_set") return { mode: "auto", text: "", only: false, ...(a.data as object) };
        if (a.action === "prompt_lint") { const txt = String((a.data as { text?: string }).text ?? ""); return { limit: 20000, seconds: 2, issues: txt.trim() ? [{ level: "tip", text: "Looks good: it says what happens, in order, and fits the length." }] : [{ level: "problem", text: "Nothing written yet. Say what happens between the first picture and the last." }] }; }
        if (a.action === "prompt_recipes") return [{ id: "absorb", title: "Dissolves into light, absorbed", blurb: "One figure dissolves into a bright light that is drawn into another.", text: "Sege and Older Sege stand close, Sege held in Older Sege's arms. A soft, bright light begins to glow in Older Sege's chest and slowly grows. Sege dissolves into the light, which is drawn gently into Older Sege's chest. The glow fades until only Older Sege remains, still and calm." },
          { id: "age", title: "Ages in front of us", blurb: "The same person, older, with no cut.", text: "Sege stays in place, looking ahead. Slowly and continuously, time passes on Sege's face." }];
        if (a.action === "prompt_write") return { prompt: "Little Sege and Older Sege embrace. A bright light glows in Older Sege's chest and Little Sege dissolves into it, drawn into his heart. The light fades and Older Sege stands calm.", why: "Read as a farewell by absorption: one cause (the light), one effect (Little Sege dissolves into it).", tips: ["Make the shot at least 6 seconds so the light has time to build."], source: "ai", issues: [] };
        if (a.action === "prompt_preview") return { prompt: String((a.data as { text?: string }).text || "Two figures embrace in a bare room. Characters: Sege; Older Sege. Camera: medium. Look: stylised 3D animation. No on-screen text, no subtitles, no watermark."), chars: 160, limit: 20000, left_out: [] };
        const st = (a.data as { video_path?: string }) ?? {};
        return { shot: "S01-04", shot_seconds: 2, video: st.video_path ? "media/dance.mp4" : null, video_seconds: st.video_path ? 6 : null, image: "assets/kf.png", image_is_start: true, orientation: "video", quality: "pro", background: "video", note: "",
          notes: st.video_path ? ["The motion video is 6 s but the shot is 2 s: the take will be trimmed to the shot when the film is built."] : [], ready: !!st.video_path, missing: st.video_path ? [] : ["a motion video"], prompt: { mode: "auto", text: "", only: false } };
      }
      case "comfy_install": return { dest: "C:/Users/you/FilmCrafter ComfyUI", source: "github.com/comfyanonymous/ComfyUI (releases)", ok: true, reason: "", warnings: [], gpu: "NVIDIA GeForce RTX 3060", vendor: "nvidia", vram_gb: 12, tag: "v0.39.0",
        asset: { name: "ComfyUI_windows_portable_nvidia.7z", size: 2003629308, url: "", sha256: null }, download_gb: 2.0, need_gb: 12.8, free_gb: 640.9 };
      case "providers": return { providers: [], comfyui: { url: "http://127.0.0.1:8188", connected: !new URLSearchParams(location.search).has("nocomfy"), device: "NVIDIA GeForce RTX 3060", workflows: [] } };
      case "stylebible": {
        if (a.action === "set_shot") { const d = a.data as { shot: string; style: string | null }; if (d.style) mockShotLooks[d.shot] = d.style; else delete mockShotLooks[d.shot]; }
        return { style: { id: "auto", name: "Auto", prompt: "" }, styles: [{ id: "auto", name: "Auto", group: "", description: "" }, { id: "claymation", name: "Claymation", group: "", description: "" }, { id: "anime", name: "Anime", group: "", description: "" }],
          scenes: [], shots: { ...mockShotLooks }, precedence: [] };
      }
      case "lighting": {
        if (a.action === "apply") return { changed: ["S01-01", "S01-02"], skipped: ["S01-03"], undo: true };
        if (a.action === "undo") return { restored: ["S01-01", "S01-02"], more: false };
        const d = (term: string, label: string, kelvin: number, level: number, wording: string) => ({ term, label, kelvin, contrast: "", level, key: "", accent: "", motion: "steady", practical: false, haze: false, wording });
        const row = (shot: string, scene: number, start: number, end: number, mood: string, label: string, design: ReturnType<typeof d>, why: string, extra = {}) => ({ shot, scene, start, end, section: "verse", mood, label, valence: 0, arousal: 0.4, intensity: 5, confidence: 0.8, also: [], held: false, user_set: false, director: "", design, why, ...extra });
        return { count: 5, user_set: 1, shots: [
          row("S01-01", 1, 0, 2, "loneliness", "Loneliness", d("lowkey", "Low key / chiaroscuro", 6200, 1, "low-key chiaroscuro lighting, deep shadows and a single pool of light; cold colour (about 6200 K); key a single small source far from the subject; gentle contrast; colour accents: cold blue, a lone warm window; visible practical lamps in frame"), "Loneliness (read from the feeling and words of the shot; the song is quiet here) → low key / chiaroscuro, cold, gentle contrast."),
          row("S01-02", 1, 2, 4.5, "loneliness", "Loneliness", d("lowkey", "Low key / chiaroscuro", 6200, 1, "low-key chiaroscuro lighting"), "Loneliness, held steady to keep the scene's light.", { held: true }),
          row("S01-03", 1, 4.5, 6.5, "grief", "Grief", d("overcast", "Soft overcast", 7000, 1, "soft overcast light, flat and grey"), "Grief (read from the feeling and words of the shot) → soft overcast, cold, gentle contrast.", { user_set: true }),
          row("S01-04", 2, 6.5, 8.5, "hope", "Hope", d("golden", "Golden hour", 4500, 2, "golden hour sunlight, warm low rays and long shadows; neutral colour (about 4500 K); key rising from behind the subject; moderate contrast; a little haze to give the light shape"), "Hope (read from the song and the performance; the song is loud here) → golden hour, neutral, moderate contrast."),
          row("S01-05", 2, 8.5, 11, "triumph", "Triumph", d("rim", "Rim / backlit", 5000, 3, "strong rim light and backlight outlining the subject; strong contrast"), "Triumph (read from the feeling and words of the shot; the song is loud here) → rim / backlit, neutral, strong contrast.")],
          scenes: [{ scene: 1, heading: "INT. ROOM - NIGHT", from: "Loneliness", to: "Grief", arc: "Loneliness → Grief", terms: ["lowkey", "overcast"] }, { scene: 2, heading: "EXT. ROOF - DAWN", from: "Hope", to: "Triumph", arc: "Hope → Triumph", terms: ["golden", "rim"] }] };
      }
      case "ai_brain": {
        if (a.action === "models") return { base_url: "https://openrouter.ai/api/v1", models: ["meta/free-one:free", "deepseek/deepseek-chat-v3.1", "google/gemini-2.5-flash", "openai/gpt-4.1-mini", "openai/gpt-5"],
          vision_capable: ["google/gemini-2.5-flash", "openai/gpt-4.1-mini", "openai/gpt-5"], structured: ["deepseek/deepseek-chat-v3.1", "google/gemini-2.5-flash", "openai/gpt-4.1-mini", "openai/gpt-5"],
          prices: { "meta/free-one:free": { in: 0, out: 0 }, "deepseek/deepseek-chat-v3.1": { in: 0.2, out: 0.8 }, "google/gemini-2.5-flash": { in: 0.3, out: 2.5 }, "openai/gpt-4.1-mini": { in: 0.4, out: 1.6 }, "openai/gpt-5": { in: 1.25, out: 10 } } };
        if (a.action === "set") return { provider: "openai", base_url: "", model: "", vision_model: "", ...(a.data as object) };
        if (a.action === "test") return { model: "google/gemini-2.5-flash", seconds: 1.4, sample: { shot: "A slow push toward the open door.", energy: 6 } };
        return { provider: "openai", base_url: "", model: "", vision_model: "" };
      }
      case "track": return { checked_now: 0, models: [
        { provider: "fal", model: preview.manifest.model, takes: 7, failed: 2, failures: { service: 2 }, cost: 4.9, reviews: { good: 4, needs_attention: 1 }, sound: { in_time: 3, own_audio: 1 }, sung: 4 },
        { provider: "kie", model: "bytedance/seedance-2", takes: 3, failed: 0, failures: {}, cost: 2.46, reviews: {}, sound: {}, sung: 0 }] };
      case "dance": return { dance_shots: 3, clean: 1, note: "", shots: [
        { shot: "S01-04", start: 4, end: 8, framing: "wide shot", issues: [] },
        { shot: "S02-02", start: 20, end: 21, framing: "close-up", issues: [{ kind: "close", text: "The frame is close-up: the body, which is the dance, is mostly out of shot.", fix: "Use a wide or full-body frame for this shot." }, { kind: "short", text: "The shot is only 1.0 s: too short for a move to read.", fix: "Make it at least 1.5 s, or merge it with a neighbour." }] },
        { shot: "S03-01", start: 30.3, end: 34, framing: "full shot", issues: [{ kind: "off_beat", text: "The cut lands 0.20 s away from the nearest beat (30.50 s).", fix: "Move the start of the shot to 30.50 s." }] }] };
      case "acting": {
        const secs = ["Intro 1", "Verse 1", "Chorus 1", "Verse 2", "Chorus 2", "Outro 1"];
        if (a.action === "beats_get") return { shot: (a.data as { shot?: string } | undefined)?.shot ?? "S01-04", seconds: 2.5, source: "director", beats: [
          { t0: 0, t1: 1, what: "Sege glances at the door, then back to Amara", eyes: "door, then Amara", breath: "held" },
          { t0: 1, t1: 2.5, what: "His shoulders drop as he decides to speak", face: "a small, unsure smile", hands: "the tablet slips against his hip" }] };
        if (a.action === "beats_estimate") return { calls: 1, usd: 0.007, local: false, note: "A rough estimate from the size of the request; your provider's own price applies.", shots: ["S01-04"] };
        if (a.action === "arc_estimate") return { calls: 1, usd: 0.012, local: false, note: "A rough estimate from the size of the request; your provider's own price applies.", characters: ["Sege", "Amara"] };
        return { business: { Sege: [{ when: "nervous", do: "taps the tablet's edge with his thumb" }, { when: "proud", do: "lifts his chin and half-smiles" }], Amara: [] }, beats_shots: ["S01-04"],
          arc: { sections: secs, characters: ["Sege", "Amara"], arcs: {
            Sege: { source: "director", points: [{ section: "Intro 1", emotion: "guarded", intensity: 3, note: "" }, { section: "Verse 1", emotion: "uneasy", intensity: 5, note: "" },
              { section: "Chorus 1", emotion: "cornered", intensity: 8, note: "" }, { section: "Chorus 2", emotion: "relieved", intensity: 6, note: "" }, { section: "Outro 1", emotion: "warm", intensity: 3, note: "" }] },
            Amara: { source: null, points: [] } } } };
      }
      case "layer_kit": return { styles: [], templates: [] };
      case "backups": return [];
      case "list_projects": return [{ dir: "mock", title: "Exit Plan", state: "analyzed", modified: Date.now() / 1000, song: "song.wav" }];
      case "load_project": return noScript
        ? { dir: "mock", project: { ...project, look: { style: "auto" } }, song_path: url("song.wav"), song_map, production: null, directed: null, jobs: [], concepts }
        : { dir: "mock", project, song_path: url("song.wav"), song_map, production, directed: null, jobs };
      case "key_status": return { openai: true, fal: true, kie: false, google: false };
      case "set_keyframe": return null;
      case "add_reference": case "remove_reference": return { cast: { Sege: "x.png" } };
      case "director_command": return new Promise((r) => setTimeout(() => r({ id: "c1", summary: "The second chorus is redirected with stronger physical urgency, faster camera language and higher performance intensity.", not_done: "", changed: ["S07-01", "S07-02", "S07-03", "S07-04"] }), 900));
      case "undo_command": return { id: "c1", restored: [] };
      case "render_preview": return { ...preview, inputs: [
        { role: "first_frame", label: "Starts from this frame (your approved keyframe)", path: "assets/keyframes/S01-04.png", sent: true },
        { role: "reference", label: "reference for Sege", path: "assets/refs/character_sege.png", sent: false },
        { role: "reference", label: "reference for Amara", path: "assets/refs/character_amara.png", sent: false },
        { role: "audio", label: "The song's vocal under this shot, for Sege to follow", path: null, sent: true }] };
      case "render_catalog": return [{ provider: "fal", model: preview.manifest.model, title: preview.manifest.title, category: "image-to-video" }];
      case "queue_render": return [];
      case "confirm_spend": return "devmock-token";
      case "list_styles": return fetch(url("styles.json")).then((r) => r.json()).then((j) => j.styles);
      case "set_look": return null;
      case "app_ready": return null;
      case "engine_status": return { ready: true, dev: true, gpu: true };
      case "launch_path": return null;
      case "set_project_settings": return null;
      case "import_reference": return { ref: "project:assets/refs/sege-closeup.png", kind: "image", name: "sege-closeup.png", path: "" };
      case "save_project": return { saved: Date.now() / 1000 };
      case "render_estimate": {
        const m = (args as { model?: string } | undefined)?.model ?? "";
        if (m === "kling") return { provider: "fal", model: m, shots: 1, usd: 0.56, usd_known: 0.56, unknown: 0, basis: "4 s (the shortest this model makes) × $0.14/s" };
        if (m.includes("seedance")) return { provider: "kie", model: m, shots: 1, usd: null, usd_known: 0, unknown: 1, kie_credits_est: 99, kie_usd_est: 0.49, basis: "≈99 credits per shot (what seedance-2 cost before)" };
      }
      // falls through to the project-wide estimate
      return { provider: "fal", model: preview.manifest.model, shots: 68, usd: 108.12, usd_known: 108.12, unknown: 0, basis: "≈113k tokens × $0.014/1,000 tokens" };
      case "export_project": return new Promise((r) => setTimeout(() => r({ loudness: { lufs: -14.6, range_lu: 6.2, true_peak_db: -1.3 }, path: "C:\Users\you\Documents\FilmCrafter\Exit Plan.filmcrafter\exports\Exit Plan - Cinema (draft).mp4", preset: "Cinema 2.39:1", width: 1920, height: 804, fps: 24, duration: 191.44, shots: 70, rendered: 2, draft: true }), 800));
      case "plugin:event|listen": return 1;
      default: return null;
    }
  });
  (window as unknown as { __PF_MOCK__: boolean }).__PF_MOCK__ = true;
}
