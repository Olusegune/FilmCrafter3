import { invoke, convertFileSrc } from "@tauri-apps/api/core";
import { listen, type UnlistenFn } from "@tauri-apps/api/event";

export type Section = { start: number; end: number; label: string; group: string; energy: number; mood: string };
export type LyricLine = { section: string; text: string; start: number | null; end: number | null };
export type SongMap = {
  duration: number; bpm: number; beats: number[]; downbeats: number[];
  energy_curve: [number, number][]; accents: number[]; sections: Section[];
  lyrics: LyricLine[]; lyric_match: number | null; peaks: number[]; analyzer: string;
};

/** A shot as shown in the studio: planned (script import) or directed (Director Engine). */
export type Shot = {
  id: string; scene: number; number: number; start: number; end: number;
  beats: string[]; source_shots: string[]; performers: string[];
  framing: string; state: string; renderer: string;
  description?: string; camera_moves?: string[]; lyrics?: string[]; section?: string;
  flags?: string[]; sync_accents?: number[];
  // directed-only
  purpose?: string; emotion?: string; performance_intensity?: number; performance?: string;
  expression?: string; movement?: string; lens?: string; camera_movement?: string; camera_energy?: string;
  lighting?: string; environment?: string; wardrobe?: string; continuity?: string; sync_event?: string;
  visual_prompt?: string; dropped_beats?: string[]; revised?: number;
};
export type Scene = {
  number: number; heading: string; start: number; end: number; notes: Record<string, string>;
  fields?: Record<string, string>; characters?: string[]; shots: Shot[];
  director_note?: string; issues?: string[];
};
export type Character = { name: string; archetype: string; appearance: string; motivation: string; acting_notes: string };
export type Plan = { meta: Record<string, string>; characters: Character[]; scenes: Scene[]; model?: string };

export type ProjectSummary = { dir: string; title: string; state: string; modified: number; aspect?: string; thumb?: string | null; song?: string; kind?: "film" | "show"; onboarding?: { stage: string } };
export type LoadedProject = {
  dir: string;
  project: { title: string; state: string; song: string; lyrics?: string; script?: string; aspect_ratio?: string; artist?: string; look?: Look | string;
    quality?: ProjectSettings["quality"]; lip_sync?: ProjectSettings["lip_sync"]; onboarding?: Onboarding; source_song?: string };
  song_path: string | null;
  song_map: SongMap | null;
  production: Plan | null;
  directed: Plan | null;
  jobs: Job[];
  doc?: string | null;
  keyframes?: Record<string, Record<string, string>>;
  concepts?: { concepts: Concept[]; model?: string } | null;
  treatment?: { concept: Concept; notes?: string } | null;
};
export type AgentStageState = "not_started" | "ready" | "working" | "needs_approval" | "complete" | "failed" | "paused";
export type AgentStage = { id: string; label: string; state: AgentStageState };
export type AgentStudioState = {
  version: number; paused: boolean; current: string; updated: number;
  brief: { story: string; style: string; duration: string; aspect: string; budget_limit: number; checkin_mode: "guided" | "balanced" | "autopilot" | "custom"; checkpoints: string[];
    image_provider?: string; image_model?: string; video_provider?: string; video_model?: string; voice_provider?: string; voice_model?: string; music_provider?: string; sfx_provider?: string };
  stages: AgentStage[]; approvals: { id: string; stage: string; at: number; asset_versions: string[] }[];
  revisions: { id: string; stage: string; note: string; affected: string[]; at: number; state: string }[];
  activity: { id: string; at: number; kind: string; text: string }[];
  existing: { scenes: number; shots: number }; spending: { actual: number; committed: number; limit: number; pricing_known: boolean };
  jobs: { ready: number; working: number; failed: number };
  analysis?: { status: "proposed" | "accepted"; model: string; logline: string; genre: string; tone: string; characters: { name: string; role: string; appearance: string; wardrobe: string; voice: string }[]; locations: { name: string; design: string; lighting: string }[]; props: { name: string; design: string; continuity: string }[]; scenes: { heading: string; summary: string }[]; sound_direction: string; score_prompt: string; sfx_plan: { scene: string; sound: string; purpose: string }[]; motion_graphics: { type: string; text: string; when: string }[]; visual_style: string; visual_style_reason: string; director_style_id: string; director_style_reason: string; questions: string[] } | null;
};
export type DirectorStyle = { id: string; name: string; region: string; origin: string; known_for: string; palette: string[]; traits: Record<string, string> };
export type Concept = {
  title: string; premise: string; mood: string; performance_approach: string; cinematic_style: string; palette: string[];
  environment: string; wardrobe: string; movement: string; narrative_level: "performance" | "hybrid" | "narrative";
  hero_frame: string; suggested_look: string;
};
export type JobState = "queued" | "submitting" | "submitted" | "ready" | "failed" | "uncertain" | "dismissed";
export type Job = {
  id: string; shot_id: string; plan: string; provider: "fal" | "kie" | "google" | "byteplus"; model: string; state: JobState; kind?: "video" | "image" | "lipsync" | "asset"; source_job?: string | null;
  overrides: Record<string, unknown>; payload?: Record<string, unknown>; provider_job_id: string | null;
  output: string | null; error: string | null; cost: number | null; cost_unit?: string | null;
  created: number; updated: number; attempts: number; shot_start: number; shot_end: number; look?: string;
  fix_notes?: string[]; review?: Review; error_kind?: string;
  extend_of?: string; extension_part?: string; submitted?: number; detail?: string | null; progress?: number | null; estimate_usd?: number | null; asset_name?: string; retry_note?: string; retried_as?: string | null; retry_of?: string; auto_retried?: boolean;
  still_check?: { ok: boolean | null; problems?: { kind: string; severity?: "minor" | "major"; detail: string }[]; fix?: string; error?: string; model?: string };
};
export type ProjectSettings = { aspect_ratio: string; quality: "draft" | "standard" | "high" | "max"; lip_sync: "auto" | "closeups" | "off"; lip_sync_mode: "first_frame" | "audio_first" | "auto"; vocalist: "onscreen" | "offscreen"; sing_shot: { id: string; value: "auto" | "on" | "off" }; title: string };
export type Estimate = { provider: string; model: string; shots: number; usd: number | null; usd_known: number;
  unknown: number; basis: string; kie_credits?: number; kie_credits_est?: number; kie_usd_est?: number; lipsync_shots?: number;
  native_shots?: number; native_note?: string; native_blocked?: string[]; native_crowded?: string[] };
export type ReviewIssue = { kind: string; severity: "minor" | "major"; detail: string; fix: string };
export type Review = {
  reviewed: boolean; status?: "good" | "minor" | "needs_attention" | "unchecked"; summary?: string; issues?: ReviewIssue[];
  fixes?: string[]; visual?: { model: string } | null; visual_error?: string; accepted?: boolean; error?: string;
};
export type ManifestInput = {
  name: string; type: string; items: string | null; enum: (string | number)[] | null; default: unknown; max_length?: number | null;
  minimum: number | null; maximum: number | null; max_items: number | null; description: string; required: boolean;
};
export type Manifest = {
  provider: string; model: string; title: string; category: string; inputs: ManifestInput[];
  roles: Record<string, string>; ref_syntax: string | null;
};
export type CatalogItem = { provider: string; model: string; title: string; category: string; sees?: boolean; text?: boolean; rec?: number | null; fresh?: boolean; max_size?: string };
export const AUTO_MODEL: Record<string, string> = {
  fal: "bytedance/seedance-2.0/reference-to-video",
  kie: "bytedance/seedance-2",
  google: "veo-3.1-fast-generate-preview",
};
export const AUTO_LIPSYNC_MODEL: Record<string, string> = { fal: "fal-ai/sync-lipsync/v3", kie: "volcengine/video-to-video-lip-sync" };
export const AUTO_IMAGE_MODEL: Record<string, string> = {
  openai: "gpt-image-2.5-flare",
  fal: "fal-ai/nano-banana/edit",
  kie: "google/nano-banana-edit",
  google: "gemini-nano-banana-2.1",
  byteplus: "dola-seedream-5-0-pro-260628",
};

export type Style = { id: string; name: string; group: string; description: string; prompt: string; avoid: string; fit?: string; family?: string };
/** The Performance Director (performance_director.py): free and local. A field is "auto" (a draft from the film) or "you" (written or accepted by you; only these reach a prompt). */
export type PField = { value: string; source: "auto" | "you"; from: string };
export type PersonProfile = Record<string, string>;
export type CastPerson = { name: string; profile: PersonProfile; known: Record<string, string | { label: string; age: string }[]>; style: string; gestures: { when: string; do: string }[] };
export type CastProfiles = { fields: string[]; people: CastPerson[] };
export type SceneBreakdown = {
  number: number; heading: string; shots: string[]; fields: Record<"purpose" | "start" | "end" | "tension", PField>;
  people: ({ name: string } & Record<"wants" | "obstacle" | "outward" | "inner" | "hiding", PField>)[];
  subtext: { id: string; shot: string; person: string; says: string; means: PField; confidence: "low" | "medium" | "high"; why: string }[];
  turning_points: { shot: string; person: string; what: string }[]; nonverbal: { shot: string; what: string }[]; reactions: { shot: string; person: string; what: string }[];
};
export type Breakdown = { has_contracts: boolean; scenes: SceneBreakdown[] };
export type ArcFlag = { id: string; kind: "abrupt" | "flat" | "nonstop" | "unrested"; scenes: string[]; message: string };
export type EmotionalArc = { people: { name: string; track: { section: string; emotion: string; intensity: number }[]; flags: ArcFlag[]; dismissed: number }[]; sections: string[]; dismissed: string[] };
export type KindOptions = { kinds: { id: string; label: string }[] };
export type NudgeState = { shot: string; nudges: { id: string; label: string; level: number; levels: number }[] };
export type PDAction = "characters_get" | "character_set" | "character_clear" | "breakdown_get" | "breakdown_set" | "breakdown_reset" | "breakdown_accept" | "beats_suggest" | "nudges_get" | "nudge_set"
  | "kind_options" | "continuity_get" | "continuity_dismiss" | "model_labels" | "delivery_hint";
export type Look = { style: string; notes?: string; prompt?: string; avoid?: string };
/** A look for one scene or one shot (stylebible.py). `scenes[].style` and `shots[id]` are the scene's and the shot's own look ids; absent means the film's. */
export type StyleBibleRead = { style: { id: string; name: string; prompt: string }; styles: { id: string; name: string; group: string; description: string }[]; scenes: { scene: number; heading: string | null; style: string | null }[]; shots: Record<string, string>; keep_cast?: Record<string, boolean>; precedence: string[] };

/** What reading the finished file back found: faults (the film is wrong), things worth a look, and notes. `ok` is null when the check could not run. */
export type ExportCheck = { ok: boolean | null; checked: boolean; findings: { level: "fix" | "look" | "note"; what: string; from?: number; to?: number }[]; frames?: number; has_sound?: boolean; picture_seconds?: number };
export type ExportResult = {
  path: string; preset: string; width: number; height: number; fps: number; duration: number;
  shots: number; rendered: number; draft: boolean; loudness?: { lufs: number; range_lu: number | null; true_peak_db: number | null } | null; check?: ExportCheck | null; overlays?: number; captions?: number; subtitles?: string | null; overlay_error?: string };

/** The sound layers of one shot: the song under it and the take's own sound (whole, or split into voices and effects). Nothing here renders again. */
export type SoundLayer = { id: "song" | "all" | "voice" | "other"; label: string; on: boolean; gain: number | null; removed: boolean; effective_gain?: number; auto?: boolean; note?: string };
/** How loud each layer is under a shot in the film (dB below full scale, RMS over the shot; null when off or silent), the mix of them, and its peak. */
export type ShotLevels = { shot: string; layers: Record<string, number | null>; mix_db: number | null; peak_db: number | null; seconds: number | null };
export type ShotSound = { shot: string; native: boolean; take: { id: string; model?: string; output: string } | null; has_audio: boolean; silent: boolean; split: boolean; changed: boolean;
  layers: SoundLayer[]; note?: string };

export type KeyStatus = { openai: boolean; anthropic?: boolean; fal: boolean; kie: boolean; google: boolean; elevenlabs: boolean; openrouter?: boolean; byteplus?: boolean };
export type EngineEvent = { task: string; event: string; job?: unknown; stage?: string; progress?: number; message?: string; [k: string]: unknown };

export type RefKind = "character" | "set" | "prop" | "wardrobe" | "lighting" | "style" | "video" | "audio";
export type RefItem = { id: string; kind: RefKind; name: string; files: string[]; notes?: string; sheet?: boolean };
export type LookSuggestion = { shot: string; emotion: string; intensity: number; why: string; proposals: { group: string; term: string; label: string; wording: string }[] };
export type ModelInput = { role: "first_frame" | "reference" | "end_frame" | "audio"; label: string; path: string | null; sent: boolean };
export type UpscaleTool = { id: string; provider: "kie" | "fal"; model: string; media: "image" | "video"; label: string; blurb: string; ready: boolean; factors: number[] };
export type UpscaleRun = { id: string; tool: string; provider: string; model: string; kind: "keyframe" | "take"; shot: string; source: string; factor: number; state: "queued" | "submitted" | "ready" | "failed" | "undone";
  output: string | null; error: string | null; cost: number | null; job?: string };
export type ModelTrack = { provider: string; model: string; takes: number; failed: number; failures: Record<string, number>; cost: number; reviews: Record<string, number>; sound: Record<string, number>; sung: number };
export type TrackStats = { models: ModelTrack[]; checked_now: number };
export type TakeChange = { kind: string; text: string };
export type ChangesSince = { has_take: boolean; same: boolean; changes: TakeChange[]; note: string; take?: { id: string; model: string | null; created: number | null } };
export type DanceIssue = { kind: "close" | "nobody" | "short" | "long" | "off_beat"; text: string; fix: string };
export type DanceCheck = { dance_shots: number; clean: number; note: string; shots: { shot: string; start: number; end: number; framing: string; issues: DanceIssue[] }[] };
export type Library = { items: RefItem[]; assign: { project: string[]; scenes: Record<string, { add?: string[]; remove?: string[] }>;
  shots: Record<string, { add?: string[]; remove?: string[] }> } };
export type ShotStatus = "planned" | "queued" | "generating" | "ready" | "failed" | "needs_review" | "locked";
export type Version = { id: string; n: number; state: string; provider: string; model: string; output: string | null; kind: string;
  created: number; error?: string | null; error_kind?: string | null; cost?: number | null; cost_unit?: string | null; approved: boolean;
  review?: Job["review"]; media_kind?: "image" | "video" | null; motion?: string | null };
export type BoardShot = { id: string; scene: number; heading?: string; start: number; end: number; framing?: string; beat: string;
  performers: string[]; status: ShotStatus; locked: boolean; approved: string | null; end_mode?: "none" | "own" | "next"; thumb_src: string | null;
  thumb_source: "render" | "keyframe" | "storyboard" | "placeholder"; preview: string | null; keyframe: string | null;
  transition?: string; transition_s?: number | null; preview_drift?: { amp: number; period: number } | null; preview_kind?: "image" | "video" | null; preview_proxy?: string | null; preview_motion?: string | null; keyframe_check?: "fail" | "look" | "pass" | null; keyframe_model?: string | null;
  versions: Version[]; references: { id: string; kind: RefKind; name: string; from: string }[] };
export type Board = { plan: string; shots: BoardShot[]; library: Library };

export type ProposedAction = { type: "action" | "direction" | "error"; message?: string; action?: "render" | "lock" | "unlock" | "approve_latest" | "approve_keyframes";
  render_kind?: "video" | "image" | "lipsync"; shots?: string[]; skipped?: { id: string; reason: string }[]; what?: string;
  provider?: string; model?: string; label?: string; verified?: string | null; sources?: Record<string, string>; billable?: boolean; summary?: string; warning?: string | null };
export type ProviderStatus = { providers: { provider: string; name: string; connected: boolean; families: string[]; verified: string[] }[];
  comfyui: { url: string; connected: boolean; device?: string; error?: string; workflows: { model: string; title: string; kind: string; placeholders: string[] }[] } };

export type Probe = { duration: number; peaks: number[]; title?: string | null; artist?: string | null; kind: "audio" | "video" };
export type Onboarding = { stage: WizardStage; done: WizardStage[]; skipped: WizardStage[]; concept?: "propose" | null;
  concept_notes?: string; source_video?: string | null; song_name?: string; probe?: { duration: number; peaks: number[] } };
export type WizardStage = "music" | "lyrics" | "script" | "assets" | "choreography" | "review" | "done";
export type ChoreoPlan = { concept: string; dancers: string[]; bpm: number; source: "sheet" | "designed"; made: number; model: string;
  sections: { section: string; feel: string; counts: { counts: string; move: string }[] }[];
  shots: Record<string, { dancing: boolean; pose: string; motion: string; energy: number }> };
export type Choreography = { mode: "none" | "upload" | "written" | "style" | "ai" | null; style: string | null; notes: string;
  files: string[]; sections: { section: string; performers: string[]; notes: string }[]; precise: boolean; plan?: ChoreoPlan };

export type Brain = { provider: "openai" | "anthropic" | "openrouter" | "gemini" | "ollama" | "lmstudio"; base_url: string; model: string; vision_model: string };
export type AgentProposal = { id: string; tool: string; args: Record<string, unknown>; risk: "write" | "spend"; state: "pending" | "applied" | "rejected" | "stale"; created: number };
export type DirectorTurn = { reply: string; model: string; steps: { tool: string; result: unknown }[]; proposals: AgentProposal[] };

export type Balance = { provider: string; amount: number | null; unit: "usd" | "credits" | null; known: boolean; usd?: number };
export type BudgetStatus = { balances: Record<string, Balance>;
  spent: { fal_usd: number; kie_credits: number; kie_usd: number; byteplus_usd?: number; total_usd: number; renders: number; openai_images: number } | null;
  fits: Record<string, { fits: boolean | null; short?: number; reason?: string }> };

/** The engine commands that change a shot's settings and can be undone (shothistory.py): after one of them succeeds the Studio is told, so it can offer Undo. */
const TRACKED: Record<string, string[]> = {
  library: ["approve", "approve_keyframes", "choose_keyframe", "lock"],
  frames: ["set", "start", "chain", "choose", "use_image", "use_start"],
  compose: ["set_motion", "clear_motion", "prompt_set", "library_use"],
};
export function isTracked(command: string, action: string): boolean { return TRACKED[command]?.includes(action) ?? false; }
function noteChange<T>(command: string, action: string, p: Promise<T>): Promise<T> {
  if (isTracked(command, action)) p.then(() => window.dispatchEvent(new Event("pf-shot-changed")), () => { /* the caller reports the failure */ });
  return p;
}

export const api = {
  directorStyle: <T = { styles: DirectorStyle[]; current: string | null }>(dir: string, action: "list" | "set" | "clear", data: Record<string, unknown> = {}) => invoke<T>("director_style", { dir, action, data }),
  agentStudio: (dir: string, action: "state" | "update_brief" | "analyze" | "accept_analysis" | "create_plan" | "approve" | "request_changes" | "pause" | "resume", data: Record<string, unknown> = {}) =>
    invoke<AgentStudioState>("agent_studio", { dir, action, data }),
  directorChat: <T = DirectorTurn>(dir: string, action: "turn" | "proposals" | "apply" | "reject", data: Record<string, unknown> = {}) =>
    invoke<T>("director_chat", { dir, action, data }),
  media: <T = unknown>(dir: string, action: "import" | "fill" | "stills" | "motion" | "transition" | "plan", data: Record<string, unknown> = {}) =>
    invoke<T>("media", { dir, action, data }),
  continuity: <T = unknown>(dir: string, action: "get" | "set" | "shot" | "chain" | "check" | "ai_check", data: Record<string, unknown> = {}) =>
    invoke<T>("continuity", { dir, action, data }),
  performance: <T = unknown>(dir: string, action: "get" | "set", data: Record<string, unknown> = {}) => invoke<T>("performance", { dir, action, data }),
  routing: <T = unknown>(dir: string, action: "status" | "set" | "pick" | "models", data: Record<string, unknown> = {}) => invoke<T>("routing", { dir, action, data }),
  localModels: <T = unknown>(action: "status" | "pull" | "delete" | "use" | "start" | "lms_get" | "unload" | "test", data: Record<string, unknown> = {}) => invoke<T>("local_models", { action, data }),
  reviewBacklog: (dir: string, run: boolean) => invoke<{ unchecked: number }>("review_backlog", { dir, run }),
  handFix: <T = unknown>(dir: string, action: "plan" | "queue" | "locate", data: Record<string, unknown>) => invoke<T>("hand_fix", { dir, action, data }),
  keyframeSet: <T = unknown>(dir: string, action: "check_plan" | "check_run" | "remake_plan" | "remake_run" | "remodel_plan" | "remodel_run" | "swap_status" | "swap_apply", data: Record<string, unknown> = {}) => invoke<T>("keyframe_set", { dir, action, data }),
  retryCheaper: <T = unknown>(dir: string, action: "options" | "retry", data: Record<string, unknown>) => invoke<T>("retry_cheaper", { dir, action, data }),
  shotHistory: (dir: string, action: "list" | "undo" | "redo") => invoke<ShotHistory>("shot_history", { dir, action }),
  proof: <T = unknown>(dir: string, action: "check" | "record" | "forget" | "report", data: Record<string, unknown> = {}) => invoke<T>("proof", { dir, action, data }),
  compose: <T = ComposeState>(dir: string, action: "state" | "set_motion" | "clear_motion" | "models" | "queue_motion" | "library_list" | "library_add" | "library_rename" | "library_remove" | "library_restore" | "library_use" | "library_tag" | "library_export" | "library_import" | "prompt_set" | "prompt_write" | "prompt_lint" | "prompt_recipes" | "prompt_preview", data: Record<string, unknown> = {}) => noteChange("compose", action, invoke<T>("compose", { dir, action, data })),
  comfyInstall: <T = ComfyInstallPlan>(action: "plan" | "install", data: Record<string, unknown> = {}) => invoke<T>("comfy_install", { action, data }),
  comfySetup: <T = unknown>(action: "detect" | "start" | "setup" | "downloads" | "download" | "health" | "test", data: Record<string, unknown> = {}) => invoke<T>("comfy_setup", { action, data }),
  overnight: <T = unknown>(dir: string, action: "start" | "stop" | "status", confirmed = false) => invoke<T>("overnight", { dir, action, confirmed }),
  directorAudit: <T = DirectorAudit>(dir: string, action: "audit" | "split", data: Record<string, unknown> = {}) => invoke<T>("director_audit", { dir, action, data }),
  captions: <T = CaptionsState>(dir: string, action: "get" | "set" | "edit" | "preview" | "section", data: Record<string, unknown> = {}) =>
    invoke<T>("captions", { dir, action, data }),
  overlays: <T = Overlay[]>(dir: string, action: "list" | "add" | "update" | "remove" | "preview" | "sync" | "reorder" | "duplicate" | "history" | "undo" | "redo" | "key_suggest", data: Record<string, unknown> = {}) =>
    invoke<T>("overlays", { dir, action, data }),
  refgen: <T = RefGenStatus>(dir: string, action: "candidates" | "estimate" | "queue" | "use" | "discard" | "status" | "cards" | "own", data: Record<string, unknown> = {}) =>
    invoke<T>("refgen", { dir, action, data }),
  stylebible: (dir: string, action: "read" | "set_scene" | "set_shot" | "set_shot_options", data: Record<string, unknown> = {}) => invoke<StyleBibleRead>("stylebible", { dir, action, data }),
  lighting: <T = LightingPlan>(dir: string, action: "plan" | "apply" | "undo" | "moods", data: Record<string, unknown> = {}) => invoke<T>("lighting", { dir, action, data }),
  camera: <T = ShotCamera>(dir: string, action: "vocab" | "get" | "set" | "reset" | "suggest" | "suggest_apply", data: Record<string, unknown> = {}) => invoke<T>("camera", { dir, action, data }),
  editorExport: <T = EditorPackage>(dir: string, target: "premiere" | "resolve", film?: string) =>
    invoke<T>("editor_export", { dir, action: "package", data: { target, film } }),
  fonts: <T = FontList>(dir: string, action: "list" | "add", data: Record<string, unknown> = {}) => invoke<T>("fonts", { dir, action, data }),
  golden: <T = unknown>(dir: string, action: "status" | "preview" | "split" | "changes", data: Record<string, unknown> = {}) => invoke<T>("golden", { dir, action, data }),
  upscale: <T = unknown>(dir: string, action: "tools" | "status" | "resume" | "revert" | "run", data: Record<string, unknown> = {}) => invoke<T>("upscale", { dir, action, data }),
  track: (dir: string) => invoke<TrackStats>("track", { dir, action: "stats" }),
  lipsyncCheck: <T = unknown>(dir: string, action: "count" | "run" | "timing", data: Record<string, unknown> = {}) => invoke<T>("lipsync_check", { dir, action, data }),
  supervisor: <T = unknown>(dir: string, action: "list" | "decide" | "decide_many", data: Record<string, unknown> = {}) => invoke<T>("supervisor", { dir, action, data }),
  directionLibrary: <T = unknown>(action: "list" | "match" | "apply" | "save" | "delete", dir: string | null, data: Record<string, unknown> = {}) =>
    invoke<T>("direction_library", { action, dir, data }),
  diagnostics: () => invoke<{ providers: Diagnosis[] }>("diagnostics"),
  budget: (dir: string | null, need: Record<string, number> = {}) => invoke<BudgetStatus>("budget", { action: "status", dir, need, provider: null }),
  aiBrain: <T = Brain>(action: "get" | "set" | "models" | "test", data: Record<string, unknown> = {}) => invoke<T>("ai_brain", { action, data }),
  /** Is the chosen AI brain ready: OpenAI with its key, OpenRouter with its key and a model, or a local model chosen? */
  aiReady: async () => {
    const [k, b] = await Promise.all([invoke<KeyStatus>("key_status"), invoke<Brain>("ai_brain", { action: "get", data: {} }).catch(() => null)]);
    if (!b || b.provider === "openai") return !!k.openai;                                  // OpenAI: its key
    if (b.provider === "openrouter") return !!k.openrouter && !!b.model;                     // OpenRouter: its key and a model chosen
    if (b.provider === "anthropic") return !!k.anthropic && !!b.model;                        // Claude: Anthropic key and a model chosen
    if (b.provider === "gemini") return !!k.google && !!b.model;                             // Gemini: Google key and a model chosen
    return !!b.model;                                                                         // Ollama / LM Studio: a model chosen
  },
  titleCard: <T = TitleCardState>(dir: string, action: "state" | "preview" | "make" | "remove" | "intro_shot", data: Record<string, unknown> = {}) => invoke<T>("title_card", { dir, action, data }),
  cleanup: <T = CleanupScan>(dir: string, action: "scan" | "discard" | "restore" | "empty", data: Record<string, unknown> = {}) => invoke<T>("cleanup", { dir, action, data }),
  customFrame: <T = CustomFrameState>(dir: string, action: "state" | "insert" | "remove", data: Record<string, unknown> = {}) => invoke<T>("custom_frame", { dir, action, data }),
  layerKit: <T = { styles: LayerStyle[] }>(dir: string, action: "styles" | "save" | "apply" | "delete_style" | "lyrics" | "lyrics_remove" | "templates" | "template_save" | "template_apply" | "template_delete" | "template_remove" | "builtin_list" | "builtin_preview" | "builtin_apply", data: Record<string, unknown> = {}) => invoke<T>("layer_kit", { dir, action, data }),
  shotSound: (dir: string, action: "get" | "set" | "delete" | "restore" | "reset" | "split", data: Record<string, unknown>) => invoke<ShotSound>("shot_sound", { dir, action, data }),
  performanceDirector: <T = unknown>(dir: string, action: PDAction, data: Record<string, unknown> = {}) => invoke<T>("performance_director", { dir, action, data }),
  acting: <T = unknown>(dir: string, action: "get" | "beats_get" | "beats_set" | "beats_clear" | "beats_estimate" | "beats_write" | "arc_set" | "arc_clear" | "arc_estimate" | "arc_write" | "business_set",
                        data: Record<string, unknown> = {}) => invoke<T>("acting", { dir, action, data }),
  shotLevels: (dir: string, shot: string) => invoke<ShotLevels>("shot_sound", { dir, action: "levels", data: { shot } }),
  proxies: (dir: string, action: "status" | "build" | "clear", data: Record<string, unknown> = {}) => invoke<ProxyStatus>("proxies", { dir, action, data }),
  smartEditor: <T = unknown>(dir: string, action: "recipes" | "suggest" | "ask" | "accept" | "reject" | "reset_rejected" | "preview", data: Record<string, unknown> = {}) => invoke<T>("smart_editor", { dir, action, data }),
  presets: <T = PresetCatalog>(dir: string, action: PresetAction, data: Record<string, unknown> = {}) => invoke<T>("presets", { dir, action, data }),
  series: <T = SeriesState>(dir: string, action: "get" | "create" | "set_season" | "set_episode" | "reset_field" | "resize" | "report" | "export_markdown" | "make_films", data: Record<string, unknown> = {}) => invoke<T>("series", { dir, action, data }),
  editing: <T = Cut>(dir: string, action: CutAction, data: Record<string, unknown> = {}) => invoke<T>("editing", { dir, action, data }),
  grading: <T = GradingState>(dir: string, action: GradingAction, data: Record<string, unknown> = {}) => invoke<T>("grading", { dir, action, data }),
  colourMatch: (dir: string, action: "state" | "analyze" | "set" | "clear", data: Record<string, unknown> = {}) => invoke<ColourMatchState>("colour_match", { dir, action, data }),
  checkUpdate: () => invoke<UpdateInfo>("check_update"),
  setOnboarding: (dir: string, value: Onboarding) => invoke<void>("set_onboarding", { dir, value }),
  adoptScript: (dir: string, source: { path?: string; text?: string }) =>
    invoke<{ scenes: number; shots: number; archived: string[] }>("adopt_script", { dir, path: source.path ?? null, text: source.text ?? null }),
  parseAction: (dir: string, note: string, selected: string | null, playhead: number | null) =>
    invoke<ProposedAction>("parse_action", { dir, note, selected, playhead }),
  providers: (action: "status" | "comfy_config" | "comfy_add" | "comfy_remove", data: Record<string, unknown> = {}) =>
    invoke<ProviderStatus | ProviderStatus["comfyui"]>("providers", { action, data }),
  library: <T = unknown>(dir: string, action: string, data: Record<string, unknown> = {}) => noteChange("library", action, invoke<T>("library", { dir, action, data })),
  storyboard: (dir: string) => invoke<Board>("library", { dir, action: "storyboard", data: {} }),
  thumbs: (dir: string, srcs: string[]) => invoke<Record<string, string | null>>("library", { dir, action: "thumbs", data: { srcs } }),
  appReady: () => invoke<void>("app_ready"),
  engineStatus: () => invoke<{ ready: boolean; dev: boolean; gpu: boolean }>("engine_status"),
  engineSetupSize: () => invoke<number>("engine_setup_size"),
  setupEngine: () => invoke<{ ready: boolean }>("setup_engine"),
  setProjectSettings: (dir: string, settings: Partial<ProjectSettings>) => invoke<void>("set_project_settings", { dir, settings }),
  importReference: (dir: string, path: string) =>
    invoke<{ ref: string; kind: string; name: string; path: string }>("import_reference", { dir, path }),
  directorCommand: (dir: string, note: string, selected: string | null, playhead: number | null) =>
    invoke<{ id: string | null; summary: string; not_done: string; changed: string[] }>("director_command", { dir, note, selected, playhead }),
  undoCommand: (dir: string, id: string) => invoke<{ id: string; restored: string[] }>("undo_command", { dir, id }),
  saveProject: (dir: string) => invoke<{ saved: number }>("save_project", { dir }),
  saveProjectAs: (dir: string, dest: string) => invoke<string>("save_project_as", { dir, dest }),
  launchPath: () => invoke<string | null>("launch_path"),
  onMenu: (fn: (id: string) => void): Promise<UnlistenFn> => listen<string>("menu", (e) => fn(e.payload)),
  onOpenPath: (fn: (path: string) => void): Promise<UnlistenFn> => listen<string>("open-path", (e) => fn(e.payload)),
  keyStatus: () => invoke<KeyStatus>("key_status"),
  setKey: (provider: string, key: string) => invoke<void>("set_key", { provider, key }),
  deleteKey: (provider: string) => invoke<void>("delete_key", { provider }),
  frames: <T = unknown>(dir: string, action: "get" | "set" | "start" | "chain" | "support" | "options" | "choose" | "use_image" | "use_start" | "extend_info",
                        data: Record<string, unknown> = {}) => noteChange("frames", action, invoke<T>("frames", { dir, action, data })),
  isFilm: (path: string) => invoke<boolean>("is_film", { path }),
  shots: <T = ShotsView>(action: "get" | "breakdown" | "shot" | "set" | "add" | "duplicate" | "delete" | "move" | "merge" | "split" | "suggest" | "command" | "principles" | "blocking", target: string, data: Record<string, unknown> = {}) =>
    invoke<T>("film_shots", { action, target, data }),
  voice: <T = VoiceStatus>(action: "status" | "match" | "import" | "remove", target: string, data: Record<string, unknown> = {}) => invoke<T>("film_voice", { action, target, data }),
  /** Custom voices with ElevenLabs inside a film (filmcrafter_engine.cast_voice). Looking things up is free; the engine refuses to spend without `confirmed: true`, and to clone without `consent: true`. */
  castVoice: <T = CastStatus>(action: "status" | "library" | "set" | "clear" | "design" | "design_save" | "clone" | "estimate" | "speak" | "preview" | "takes" | "use_take" | "sample" | "ledger" | "ledger_resolve" | "set_limit", target: string, data: Record<string, unknown> = {}) => invoke<T>("film_cast_voice", { action, target, data }),
  /** A take recorded in the app (a 16-bit WAV): saved under ~/.filmcrafter/incoming, the path comes back for `voice("import")`. */
  saveVoiceTake: (wav: Uint8Array) => invoke<string>("save_voice_take", wav),
  make: <T = MakeStatus>(action: "sync" | "status" | "tag" | "choose" | "lock" | "reference" | "import" | "soundtrack" | "progress", target: string, data: Record<string, unknown> = {}) =>
    invoke<T>("film_make", { action, target, data }),
  assist: <T = AssistResult>(action: "estimate" | "suggest", target: string, data: Record<string, unknown>) => invoke<T>("film_assist", { action, target, data }),
  interchange: (target: string) => invoke<InterchangeResult>("film_interchange", { target }),
  filmCheck: <T = ContinuityView>(action: "check" | "decide" | "apply", target: string, data: Record<string, unknown> = {}) => invoke<T>("film_check", { action, target, data }),
  bible: <T = BibleView>(action: "get" | "seed" | "update_rules" | "update_sound_style" | "set_voice_profile" | "upsert" | "remove" | "add_state" | "remove_state" | "add_wardrobe" | "add_media" | "replace_media" | "update_media" | "remove_media", target: string, data: Record<string, unknown> = {}) =>
    invoke<T>("film_bible", { action, target, data }),
  film: <T = FilmStatus>(action: "create" | "status" | "preview" | "read_file" | "add_version" | "set_current" | "lock" | "as_is" | "rec_set" | "set_mode" | "set_aspect" | "reread", target: string | null, data: Record<string, unknown> = {}) =>
    invoke<T>("film", { action, target, data }),
  voiceDirect: <T = unknown>(action: "performance" | "performance_set" | "performance_clear" | "natural_estimate" | "natural_suggest" | "voices_estimate" | "voices_suggest" | "voices_match" | "scene_plan" | "scene_voice" | "table_read", target: string, data: Record<string, unknown> = {}) => invoke<T>("film_voice_direct", { action, target, data }),
  filmCues: <T = CueList>(action: "list" | "add" | "update" | "approve" | "remove" | "restore" | "refresh" | "quick" | "director_estimate" | "director_suggest", target: string, data: Record<string, unknown> = {}) => invoke<T>("film_cues", { action, target, data }),
  audioGen: <T = unknown>(action: "providers" | "estimate" | "generate" | "pending" | "check" | "rights", target: string, data: Record<string, unknown> = {}) => invoke<T>("film_audiogen", { action, target, data }),
  audioMix: <T = MixSettings>(action: "settings" | "set_settings" | "preview", target: string, data: Record<string, unknown> = {}) => invoke<T>("film_mix", { action, target, data }),
  filmChoreography: <T = ActionPlan>(action: "types" | "generate" | "update" | "apply" | "list" | "remove" | "get", target: string, data: Record<string, unknown> = {}) => invoke<T>("film_choreography", { action, target, data }),
  filmAudioPlan: (action: "report" | "apply" | "set", target: string, data: Record<string, unknown> = {}) => invoke<SoundPlan>("film_audioplan", { action, target, data }),
  filmReadiness: (target: string) => invoke<Readiness>("film_readiness", { action: "report", target }),
  filmPacing: (target: string) => invoke<PacingReport>("film_pacing", { action: "report", target }),
  filmComposition: <T = CompositionGuideData>(action: "guide" | "set", target: string, data: Record<string, unknown> = {}) => invoke<T>("film_composition", { action, target, data }),
  filmPlaces: (action: "status" | "draft", target: string) => invoke<PlacesStatus>("film_placecare", { action, target }),
  filmMaterials: <T = MaterialsPlan>(action: "scan" | "apply" | "review" | "history", target: string, data: Record<string, unknown> = {}) => invoke<T>("film_materials", { action, target, data }),
  filmSpending: (target: string) => invoke<SpendingSummary>("film_spending", { action: "summary", target }),
  filmOutdated: (target: string) => invoke<OutdatedReport>("film_outdated", { target }),
  registry: <T = RegistryStatus>(action: "status" | "list" | "refresh" | "in_use" = "status", target: string | null = null, data: Record<string, unknown> = {}) => invoke<T>("model_registry", { action, target, data }),
  prepareUpdate: (version: string) => invoke<{ version: string; films: { film: string; ok: boolean; why: string }[]; settings: string[]; summary: string }>("prepare_update", { version }),
  filmAudio: <T = AudioLibrary>(action: "list" | "import" | "update" | "approve" | "remove" | "restore", target: string, data: Record<string, unknown> = {}) => invoke<T>("film_audio", { action, target, data }),
  filmBackup: <T = unknown>(target: string, action: "make" | "list" | "verify" | "restore", name: string | null = null) => invoke<T>("film_backup", { action, target, name }),
  backups: <T = unknown>(dir: string, action: "backup" | "backups" | "restore", name: string | null = null) => invoke<T>("backups", { dir, action, name }),
  packFilm: (target: string, dest: string) => invoke<{ path: string; files: number; bytes: number; title: string }>("pack_film", { target, dest }),
  packProject: (dir: string, dest: string) => invoke<{ path: string; files: number; bytes: number }>("pack_project", { dir, dest }),
  openPulse: (path: string) => invoke<string>("open_pulse", { path }),
  listProjects: () => invoke<ProjectSummary[]>("list_projects"),
  recents: (action: "remove" | "clear" | "restore", dir: string | null = null) => invoke<{ hidden: number }>("recents", { action, dir }),
  hiddenCount: () => invoke<number>("hidden_count"),
  listStyles: () => invoke<Style[]>("list_styles"),
  setLook: (dir: string, look: Look) => invoke<void>("set_look", { dir, look }),
  loadProject: (dir: string) => invoke<LoadedProject>("load_project", { dir }),
  ensureRenderer: (dir: string) => invoke<void>("ensure_renderer", { dir }),
  renderCatalog: (provider: string, kind: "video" | "image" | "lipsync" | "upscale" = "video", refresh = false) => invoke<CatalogItem[]>("render_catalog", { provider, kind, refresh }),
  setKeyframe: (dir: string, plan: string, shot: string, image: string | null) => invoke<void>("set_keyframe", { dir, plan, shot, image }),
  renderPreview: (dir: string, shot: string, provider: string, model: string | null, overrides: Record<string, unknown>,
                  kind: "video" | "image" = "video") =>
    invoke<{ manifest: Manifest; payload: Record<string, unknown>; problems?: string[]; references?: { label: string; media: string; path?: string }[]; dropped_references?: string[]; audio_first?: boolean; lip_sync_mode?: string; sing_setting?: "auto" | "on" | "off"; vocal_heard?: number; inputs?: ModelInput[]; keyframe_blocks_audio?: boolean; prompt_blocks?: { priority: number; text: string; kept: boolean }[]; lip_sync?: boolean; singing?: { performer: string; lyrics: string[] } | null }>("render_preview", { dir, shot, provider, model, overrides, kind }),
  queueRender: async (dir: string, shots: string[], provider: string, model: string | null, overrides: Record<string, unknown>,
                fixNotes: string[] = [], kind: "video" | "image" | "lipsync" = "video", sourceJob: string | null = null) => {
    const spendToken = await invoke<string>("confirm_spend", { dir, shots, provider, kind });
    return invoke<Job[]>("queue_render", { dir, shots, provider, model, overrides, fixNotes, kind, sourceJob, spendToken });
  },
  renderEstimate: (dir: string, shots: string[], provider: string, model: string | null, kind: "video" | "image" = "video") =>
    invoke<Estimate>("render_estimate", { dir, shots, provider, model, kind }),
  resolveJob: (dir: string, job: string, action: "retry" | "dismiss" | "accept" | "recheck" | "cancel") => invoke<Job>("resolve_job", { dir, job, action }),
  onRenderIdle: (fn: (e: { dir: string; error: string | null }) => void): Promise<UnlistenFn> =>
    listen<{ dir: string; error: string | null }>("render-idle", (e) => fn(e.payload)),
  exportProject: (dir: string, preset: string) => invoke<ExportResult>("export_project", { dir, preset, window: null }),
  exportPreview: (dir: string, start: number, end: number) => invoke<ExportResult>("export_project", { dir, preset: "preview", window: [start, end] }),
  onEngine: (fn: (e: EngineEvent) => void): Promise<UnlistenFn> => listen<EngineEvent>("engine-progress", (e) => fn(e.payload)),
  mediaUrl: (path: string) => ((typeof window !== "undefined" && (window as unknown as { __PF_MOCK__?: boolean }).__PF_MOCK__) ? path : convertFileSrc(path)),
};

export const fmtTime = (t: number) => {
  const m = Math.floor(t / 60);
  const s = t - m * 60;
  return `${m}:${s.toFixed(2).padStart(5, "0")}`;
};

/** What to show for a failure. The engine's own messages are already written for people. A fault in the program itself (a TypeError and the like) is shown in plain words; the technical text goes to the console for whoever supports the app. */
export const isProgramFault = (e: unknown): e is Error => e instanceof TypeError || e instanceof RangeError || e instanceof ReferenceError || e instanceof SyntaxError;
export const FAULT_TEXT = "Something unexpected happened on this screen. Your project is safe. Try again, and if it keeps happening restart FilmCrafter and tell us what you were doing.";
export const errorText = (e: unknown): string => {
  if (typeof e === "string") {                                       // an error that was turned into text on its way here (a program fault of this screen, or one the engine had no plain words for)
    if (/^(Type|Range|Reference|Syntax|Key|Value|Attribute|Index|ZeroDivision|Overflow|Recursion|Unicode|JSONDecode|FileNotFound|Permission|OS)Error: /.test(e)) { console.error(e); return FAULT_TEXT; }
    return e;
  }
  if (isProgramFault(e)) {
    console.error(e);
    return FAULT_TEXT;
  }
  return e instanceof Error ? e.message : "Something went wrong.";
};

export type Diagnosis = {
  provider: string; name: string; status: "verified" | "unverified" | "blocked" | "unavailable";
  message: string; error_kind: string | null; explanation: string; recovery: string | null;
  history: { ready: number; failed: number;
    last_ok: { project: string; shot: string; model: string; at: number } | null;
    last_fail: { project: string; shot: string; model: string; at: number; error_kind: string; error: string; recovery: string } | null };
};

export type ShowItem = { id: string; kind: "number" | "scene" | "intermission"; title: string; dir: string; path: string; transition: "cut" | "black" | "flow";
  state: string; duration: number; shots: number; rendered: number; analysed: boolean; cost: { usd: number; kie_credits: number };
  lines: number; has_audio: boolean; problems: string[]; song_pending: boolean;
  seconds?: number; subtitle?: string; ambience?: { file: string; volume_db: number } };
export type Overlay = { id: string; kind: "text" | "svg" | "image" | "clip" | "fill" | "shape" | "icon"; text: string; file?: string; source: string; section?: string; start: number | null; end: number | null;
  x: number; y: number; size: number; width: number; color: string; font?: string; fade: number; shape?: string; icon?: string; height?: number; stroke?: string; stroke_w?: number; opacity?: number; rotation?: number; radius?: number; filled?: boolean; keys?: Key[]; scale?: number; angle?: number; gradient?: boolean; shadow?: boolean; name?: string; color2?: string; anim?: string; cover?: boolean; group?: string;
  in_s?: number; loop?: boolean; src_w?: number; src_h?: number; src_dur?: number;
  glow?: number; glow_color?: string; blur?: number; blend?: string; mask?: string; mask_size?: number; mask_feather?: number; mask_invert?: boolean; key_color?: string; key_tol?: number; key_soft?: number; key_spill?: number; enabled: boolean; placed: boolean; reason: string; explicit: boolean; explicit_end: boolean };
export type DirectorAudit = { planned: number; directed: number; ok: boolean;
  merges: { shot: string; scene: number; start: number; end: number; duration: number; check: boolean; risks: string[]; note: string;
            sources: { id: string; cue: string[]; people: string[]; description: string }[] }[];
  drops: { shot: string; beats: string[] }[]; uncovered: { id: string; description: string; cue: string[] }[] };
export type CaptionLook = { size: number; y: number; color: string; font: string };
export type CaptionLine = { key: string; text: string; original: string; start: number; end: number; hidden: boolean; edited: boolean; section: string; performer: string;
  look: CaptionLook; own: Partial<CaptionLook> };
export type CaptionsState = { enabled: boolean; available: boolean; reason: string; lines: CaptionLine[]; sections: Record<string, Partial<CaptionLook>>; section_names: string[];
  style: { size: number; y: number; color: string; font: string; names: boolean; srt: boolean; uppercase: boolean } };
export type RefCandidate = { id: string; name: string; kind: string; reason: string; prompt: string; prompt_from: string; refs: { path: string; label: string }[] };
export type RefJob = { id: string; asset_id: string; asset_name: string; asset_kind: string; state: string; output: string | null; error: string | null;
  model: string; provider: string; cost: number | null; cost_unit: string | null; used?: boolean };
export type PlanCharacter = { id: string; name: string; role: string; identity: string[]; outfit: string; performance: string; classification: string; library_id?: string };
export type PlanProp = { id: string; name: string; description: string; owner: string; library_id?: string };
export type PlanPlace = { id: string; name: string; layout: string; light: string; variant_of: string; library_id?: string };
export type PlanMove = { id: string; name: string; song_section: string; lyric_cue: string; action: string; footwork: string; arms: string; torso: string; head_gaze: string; energy: number };
export type PlanChoreo = { id: string; character_id: string; classification: string; moves: PlanMove[] };
export type PlanAssets = { visual_style: string; world: string; always: string; palette: string; never_show: string; rules: string[];
  characters: PlanCharacter[]; props: PlanProp[]; environments: PlanPlace[]; choreography: PlanChoreo[] };
export type PlanShot = { id: string; section: string; start: number; end: number; cue: string; action: string; framing: string; camera: string; place: string; people: string[]; props: string[];
  performance: string; lighting: string; place_id: string; people_ids: string[]; prop_ids: string[] };
export type PlanMoveView = { who: string; name: string; action: string; footwork: string; arms: string; energy: number };
export type ProducerPlanView = { stage: "start" | "assets" | "shots" | "built"; assets: PlanAssets | null; shots: PlanShot[]; warnings: string[]; shots_stale: boolean; built: number | null;
  report: { imported?: Record<string, unknown>; untimed_shots?: string[]; without_images?: { name: string; kind: string }[] } | null; model: string | null;
  history: { at: number; what: string }[]; brief: { direction_index?: number | null; concept?: Concept | null; notes?: string; cast?: string; dance?: string };
  counts: { people: number; props: number; places: number; dancers: number; shots: number }; has_renders: boolean; supplied: string[];
  approved: string[]; moves: Record<string, PlanMoveView[]>;
  script: { name: string; characters: number; scenes: number; logline: string } | null };
export type UpdateInfo = { status: "update" | "up_to_date" | "offline" | "unavailable" | "disabled"; current: string; latest: string | null; url: string; notes: string; published: string | null; prerelease: boolean };
/** Colour Studio (grading.py): a grade is a few named numbers, each inside a range; one grade per scope (film, scene, shot). */
export type Grade = Partial<Record<"exposure" | "brightness" | "contrast" | "highlights" | "shadows" | "whites" | "blacks" | "saturation" | "vibrance" | "hue" | "temperature" | "tint" | "gamma" | "lift" | "gain", number>>
  & Partial<Record<"lift_rgb" | "gamma_rgb" | "gain_rgb", number[]>> & { lut?: { id: string; intensity: number }; off?: boolean };
export type LutInfo = { id: string; name: string; kind: "creative" | "technical"; space_in: string; space_out: string; dims: number; size: number; favorite: boolean };
export type GradingState = {
  revision: number; grades: { film: Grade; scenes: Record<string, Grade>; shots: Record<string, Grade> }; luts: LutInfo[]; presets: { name: string; grade: Grade }[];
  ranges: Record<string, [number, number, number]>; swing: Record<string, { clipped_whites: boolean; crushed_blacks: boolean }>; history: { rev: number; at: number; what: string }[];
  spaces: string[]; picture_space: string; shots: { id: string; scene: number | null; heading: string }[];
};
export type GradingAction = "state" | "set_grade" | "clear_grade" | "lut_import" | "lut_remove" | "lut_favorite" | "preset_save" | "preset_apply" | "preset_delete" | "undo" | "redo" | "preview";
/** The film's cut (editing.py): clips on a track, in whole ticks (254,016,000,000 a second) and whole frames; `_s` fields are seconds for showing. */
export type CutClip = { id: string; shot: string; start: number; source_in: number; duration: number; take: string | null; start_s: number; duration_s: number; source_in_s: number; start_frame: number; frames: number };
export type CutTrack = { id: string; kind: "video"; locked: boolean; hidden: boolean; muted: boolean; clips: CutClip[] };
export type Cut = { stored: boolean; notes?: string[]; unplaced: string[]; orphans: string[]; can_undo: boolean; can_redo: boolean; history: { rev: number; at: number; what: string }[];
  sequence: { fps: number[]; frame_ticks: number; ticks_per_second: number; length: number; length_s: number; tracks: CutTrack[]; markers: { id: string; at: number; at_s: number; name: string }[];
    ranges: { id: string; start: number; end: number; start_s: number; end_s: number; name: string }[] } };
export type CutOp = "split" | "trim" | "delete" | "move" | "roll" | "close_gap" | "place" | "marker_set" | "marker_remove" | "range_set" | "range_remove" | "track_set";
export type ProxyStatus = { rows: { shot: string; take: string; output: string; big: boolean; proxy: string | null }[]; big: number; ready: number; bytes: number; made?: number; removed?: number };
/** The Smart Editor (smart_editor.py): a suggestion says what, why, which clips, and carries the edits it would make. */
export type Suggestion = { id: string; kind: "tighten" | "react"; title: string; what: string; why: string; clips: string[]; shots: string[]; saves: number; window: number[]; ops: Record<string, unknown>[] };
export type Suggestions = { recipe: { id: string; label: string; for?: string }; proposals: Suggestion[]; kept: { kind: string; shot: string; clip: string; why: string }[] };
/** Creative presets (presets.py): named settings, previewed before they are applied; a choice you made yourself is kept unless you say otherwise. */
export type PresetRow = { id: string; type: string; group: string; name: string; description: string; use: string; version: number; thumbnail: string | null; includes: string[]; settings: Record<string, unknown>;
  complexity: number; series?: string; mine: boolean; favorite: boolean; recent: boolean; in_stack: boolean };
export type PresetCatalog = { presets: PresetRow[]; stack: string[]; types: string[]; applied: number; current: Record<string, { value: unknown; set: boolean }>; is_film: boolean; pending?: string[]; setup?: { episodes?: number } };
export type PresetChange = { key: string; status: "new" | "same" | "yours" | "replace" | "unavailable"; now: unknown; to: unknown; by: string; set?: boolean; why?: string };
export type PresetPlan = { stack: string[]; order: string[]; changes: PresetChange[]; notes: string[] };
export type PresetApplied = { changed: string[]; kept: string[]; same: string[]; plan: PresetPlan };
export type PresetStack = { stack: string[]; reframe: Record<string, number>; editing: string | null; delivery: { export: string; safe: { top: number; bottom: number; side: number }; captions: boolean } | null; duration_hint_s: number | null;
  applied: { at: number; stack: string[]; changed: string[]; kept: string[] }[] };
export type PresetAction = "catalog" | "plan" | "apply" | "undo" | "save_mine" | "delete_mine" | "favorite" | "export" | "import_file" | "stack_get" | "reframe_set" | "set_pending";
export type SeriesField = { value: string; source: "scaffold" | "you" };
export type SeriesEpisode = { n: number; title: string; seconds: number; role: string; hook: SeriesField; escalation: SeriesField; turning_point: SeriesField; ending: SeriesField; continuity: SeriesField; cliffhanger: boolean; budget_usd: number | null };
export type SeriesPlan = { idea: string; preset: string; hero: string; cast: string[]; places: string[]; episodes: SeriesEpisode[];
  season: { logline: SeriesField; genre: string; tone: SeriesField; rules: SeriesField; ending: SeriesField; season_budget_usd: number | null } };
export type SeriesState = { plan: SeriesPlan | null; exists: boolean; note: string };
export type SeasonFilms = { made: { n: number; title: string; dir: string }[]; kept: { n: number; title: string; dir: string }[]; folder: string };
export type SeriesReport = { episodes: number; total_seconds: number; written: number; cliffhangers: number; cast: Record<string, number[]>; places: Record<string, number[]>; budget_total_usd: number | null; season_budget_usd: number | null;
  notes: { level: string; episode: number | null; what: string }[] };
export type CutAction = "sequence_get" | "edit" | "place_missing" | "snap" | "undo" | "redo";
export type ColourMatchState = { enabled: boolean; strength: number; reference: string | null; analysed: number | null; adjusted: number;
  rows: { shot: string; distance: number; bright: number; adjusted: boolean; is_reference: boolean }[];
  cast: boolean; cast_strength: number; cast_seen: { u: number; v: number; size: number; label: string; noticeable: boolean } | null; cast_fix: { u: number; v: number } | null;
  denoise: boolean; grain: boolean; picture_care: boolean };
export type LayerTemplate = { name: string; layers: number; seconds: number; saved: number };
export type LayerStyle = { name: string; kind: string; saved: number; has_keys: boolean };
export type CustomFrameState = { shots: { id: string; start: number; end: number; intro: boolean; custom: boolean }[]; min: number; max: number; keep: number };
export type CustomFrameMade = { shot: string; plan: string; start: number; end: number; trimmed: { shot: string; by: number } | null; mode: string; keyframe: boolean };
export type CleanupItem = { path: string; name: string; kind: "video" | "image" | "audio"; size: number; shot: string | null; model: string | null; created: number; cost: number | null; cost_unit: string | null; what: string };
export type CleanupScan = { items: CleanupItem[]; bytes: number; kept: number; rendering: number; trash: { batches: number; files: number; bytes: number } };
import type { Key } from "./overlayKeys";
export type TitleCardSpec = { title: string; subtitle: string; anim: string; color: string; size: number; font?: string | null; start?: number | null; end?: number | null;
  background: { type: "none" | "colour" | "picture"; color?: string; color2?: string; picture?: string; file?: string } };
export type TitleCardState = { gap: [number, number] | null; span: [number, number] | null; card: (TitleCardSpec & { start: number; end: number }) | null; title: string; animations: { id: string; name: string }[] };
export type CameraGroup = "size" | "angle" | "movement" | "lens" | "lighting" | "focus" | "energy";
export type CameraVocab = Record<CameraGroup, { label: string; terms: { id: string; label: string; video_only: boolean }[] }>;
export type ShotCamera = { shot: string; picked: Partial<Record<CameraGroup, string>>; detected: Record<CameraGroup, string | null>;
  director: { framing: string; lens: string; movement: string; lighting: string; energy: string };
  effective: { framing: string; movement: string; lens: string; lighting: string; focus: string }; changed_since_take: boolean };
export type EditorPackage ={ path: string; folder: string; target: "premiere" | "resolve"; app: string; film: string; sequences: number; shot_clips: number;
  missing: string[]; steps: string };
export type FontEntry ={ id: string; name: string; file: string };
export type FontList = { installed: FontEntry[]; project: FontEntry[]; default: string };
export type RefGenStatus ={ candidates: RefCandidate[]; jobs: RefJob[] };
export type PictureCard = { id: string; name: string; kind: "character" | "set" | "prop" | "wardrobe" | "choreo"; picture: string | null; yours: boolean; owner: string; owner_ready: boolean;
  state: "missing" | "making" | "waiting" | "approved" | "yours"; pending: { job: string; output: string; model: string } | null; error: string | null; prompt: string; prompt_from: string };
export type PictureCards = { cards: PictureCard[]; working: boolean };
export type ScriptPlan = { title: string; format?: string; characters: string[]; warnings: string[];
  totals: { acts: number; numbers: number; scenes: number; lines: number; songs_matched: number; songs_missing: number };
  acts: { name: string; items: { kind: "number" | "scene"; title: string; lines?: unknown[]; song?: string | null }[] }[] };
export type VoiceEntry = { voice_id: string; speed: number; pitch?: number; emotion?: string | null; provider?: "elevenlabs"; voice_name?: string; model?: string;
  stability?: number; similarity?: number; style?: number };
export type ShowStatus = { dir: string; title: string; duration: number; acts: { index: number; name: string; items: ShowItem[]; costumes: Record<string, { file?: string; note?: string }> }[];
  voices: Record<string, VoiceEntry>; characters: string[];
  look?: unknown; aspect_ratio?: string; routing?: unknown; cast_dir: string;
  budget: { cap_usd: number | null; spent_usd: number; rate_per_shot: number | null; remaining_shots: number; estimate_remaining_usd: number | null;
            remaining_usd: number | null; over: boolean; near: boolean; estimate_over: boolean } };

export type LightDesign = { term: string; label: string; kelvin: number; contrast: string; level: number; key: string; accent: string; motion: string; practical: boolean; haze: boolean; wording: string };
export type LightShot = { shot: string; scene: number; start: number; end: number; section: string; mood: string; label: string; valence: number; arousal: number; intensity: number;
  confidence: number; also: string[]; held: boolean; user_set: boolean; director: string; design: LightDesign; why: string };
export type LightingPlan = { shots: LightShot[]; scenes: { scene: number; heading: string; from: string; to: string; arc: string; terms: string[] }[]; count: number; user_set: number };

export type ComfyInstallPlan = { dest: string; source: string; ok: boolean; reason: string; warnings: string[]; installed?: boolean; path?: string; start?: string | null; manual_url?: string;
  gpu?: string; vendor?: string | null; vram_gb?: number | null; tag?: string; asset?: { name: string; size: number; url: string; sha256: string | null }; download_gb?: number; need_gb?: number; free_gb?: number | null };

export type ComposeState = { shot: string; shot_seconds: number; video: string | null; video_seconds: number | null; image: string | null; image_is_start: boolean;
  orientation: "video" | "image"; quality: "std" | "pro"; background: "video" | "image"; note: string; notes: string[]; ready: boolean; missing: string[]; prompt: TakePrompt };
export type TakePrompt = { mode: "auto" | "mine"; text: string; only: boolean };
export type PromptIssue = { level: "problem" | "warn" | "tip"; text: string };
export type PromptRecipe = { id: string; title: string; blurb: string; text: string };
export type PromptWrite = { prompt: string; why: string; tips: string[]; source: "ai" | "template"; issues: PromptIssue[] };
export type PromptPreview = { prompt: string; chars: number; limit: number; left_out: string[] };
export type ComposeModels = { start_end: CatalogItem[]; references: CatalogItem[]; motion: CatalogItem[] };

export type HistoryEntry = { id: string; at: number | null; label: string };
export type ShotHistory = { undo: HistoryEntry[]; redo: HistoryEntry[]; undo_count: number; redo_count: number; label?: string };
export type MotionClip = { id: string; name: string; seconds: number | null; width: number | null; height: number | null; added: number | null; thumb: string | null; tags?: string[]; path?: string; already?: boolean };

// ---------------------------------------------------------------- films (story first)
export type StoryKind = "screenplay" | "idea" | "synopsis" | "treatment" | "outline";
export type FilmScene = { number: number; heading: string; int_ext: string; location: string; time: string; characters: string[]; dialogue_lines: number; action_lines: number; words: number; seconds: number; line?: number; implied?: boolean };
export type FilmFound = { kind: StoryKind; words: number; pages: number; rung: string; scenes: FilmScene[]; seconds: number; has_headings: boolean;
  characters: { name: string; scenes: number[]; scene_count: number; first_scene: number }[]; locations: { name: string; scenes: number[] }[] };
export type FilmAdvice = { id: string; topic: string; text: string; scene: number | null; status: "open" | "noted" | "dismissed" };
export type FilmVersion = { version: number; kind: StoryKind; note: string; parent: number | null; origin: string; created: number; fingerprint: string; locked: boolean; words: number };
export type FilmStatus = { dir?: string; title: string; aspect_ratio: string; mode: string; stage: string; created: number;
  story: { kind: StoryKind; current: number; locked: number | null; lock_history: { version: number; at: number }[]; as_is: number | null; original: string };
  version: number; text: string; kind: StoryKind; note: string; locked_here: boolean; found: FilmFound; advice: FilmAdvice[]; versions: FilmVersion[]; looks_broken?: boolean; original?: string | null };
export type StoryPreview = { kind: StoryKind; words: number; scenes: number; characters: number; locations: number; seconds: number; has_headings: boolean };

// ---------------------------------------------------------------- the Production Bible, Cast and World
export type BibleMedia = { path: string; kind: string; label: string };
export type BibleState = { id: string; label: string; notes: string; wardrobe?: string; age?: string };
export type VoiceProfile = { description: string; age_range: string; accent: string; timbre: string; pace: string; emotional_range: string; delivery: string; notes: string; approved: boolean };
export type BibleCharacter = { id: string; name: string; role: string; age: string; physical: string; relationships: string; arc: string; voice: string; notes: string; voice_profile?: VoiceProfile;
  wardrobe: { id: string; name: string; notes: string }[]; states: BibleState[]; media: BibleMedia[]; scenes: number[]; source: string };
export type BibleEnvironment = { id: string; name: string; description: string; notes: string; spatial: Record<string, string>; states: BibleState[]; media: BibleMedia[]; scenes: number[]; source: string };
export type BibleProp = { id: string; name: string; notes: string; states: BibleState[]; media: BibleMedia[]; scenes: number[]; source: string };
export type SoundStyle = { sound: Record<string, string>; music: Record<string, string> };
export type BibleView = { sound_style: SoundStyle; rev: number; updated: number; rules: Record<string, string>; philosophy: Record<string, string>; style: { lane: string; notes: string; traits: string; references: string[]; principles?: string[]; look?: string; genre?: string };
  characters: BibleCharacter[]; environments: BibleEnvironment[]; props: BibleProp[]; lanes: string[];
  families: { id: string; name: string; blurb: string; lanes: string[]; looks: { id: string; name: string; description: string }[] }[]; family: string;
  genres: { id: string; name: string; description: string }[]; look: string; genre: string;
  principles: { id: string; name: string; plain: string; fits: boolean; default: boolean }[]; principles_on: string[]; principles_custom: boolean; media_kinds: string[]; need: string[];
  counts: { characters: number; environments: number; props: number; characters_with_pictures: number }; added?: { characters: number; environments: number }; id?: string; state?: string };

// ---------------------------------------------------------------- scenes and shots
export type ShotCard = { id: string; scene: number; index: number; title: string; status: string; edited: boolean; story_purpose: string; camera: ShotContract["camera"]; locks: { storyboard: boolean; keyframe: boolean };
  duration: number; characters: string[]; has_dialogue: boolean; environment: string };
export type ShotsView = { title: string; story_version: number | null; shots: ShotCard[]; scenes: { number: number; shots: number; seconds: number }[]; seconds: number;
  enums: { framing: string[]; angle: string[]; lens: string[]; movement: string[]; focus: string[]; dof?: string[] }; cut_max?: number; made?: string[]; id?: string; shot?: ShotContract };
export type ShotBeat = { character: string; what: string; want: string; need: string; fear: string; hiding: string; subtext: string; start: string; turn: string; end: string };
export type ShotContract = { id: string; scene: number; index: number; story_version: number | null; title: string; status: string; edited: boolean; story_purpose: string; action: string;
  dialogue: { speaker: string; line: string; paren: string }[]; characters: { name: string; character_id: string | null; state_id: string | null; wardrobe_id: string | null }[];
  environment: { id: string | null; name: string; state_id: string | null }; props: { name: string; prop_id: string | null; state: string }[]; blocking: string;
  performance: { emotional_intention: string; beats: ShotBeat[]; micro_animation: string };
  camera: { framing: string; angle: string; position: string; lens: string; movement: string; focus: string; dof?: string; why: string }; sound_cut?: { lead: number; tail: number }; lighting: { description: string; time: string; why: string };
  opening_state: string; closing_state: string; continuity: string; reference_assets: string[]; sound: string; generation: { duration: number; aspect: string; notes: string };
  locks: { storyboard: boolean; keyframe: boolean }; plan?: BlockingPlanData | null };
export type BlockingPlanData = { people: { name: string; x: number; y: number; facing: number }[]; props: { name: string; x: number; y: number }[]; camera: { x: number; y: number; aim: number; fov: number } | null };
export type BlockingView = { id: string; scene: number; framing: string; plan: BlockingPlanData | null; suggested: BlockingPlanData | null; has_previous: boolean; text: string; people: string[];
  scene_shots: { id: string; framing: string; plan: BlockingPlanData | null }[]; crossings: { shot: string; previous: string; message: string; fix: string }[]; room: { w: number; h: number } };
export type ShotSuggestion = { camera: ShotContract["camera"]; lighting: { description: string; why: string }; from: string };

// ---------------------------------------------------------------- making the film
export type MakeOption = { job: string; image: string | null; state: string; model: string; provider: string; created: number; error?: string | null; cost?: number | null; ok: boolean };
export type MakeTake = { job: string; video: string | null; state: string; model: string; provider: string; created: number; error?: string | null; cost?: number | null; approved: boolean; ok: boolean };
export type MakeShot = { id: string; scene: number; title: string; duration: number; framing: string;
  storyboard: { options: MakeOption[]; chosen: string | null; locked: boolean }; keyframe: { options: MakeOption[]; chosen: string | null; locked: boolean }; video: { takes: MakeTake[]; approved: string | null } };
export type VoiceRecording = { file: string; name: string; seconds: number; rms_db: number; peak_db: number; source?: "elevenlabs" };
export type VoicePerson = { name: string; key: string; lines: string[]; recording: VoiceRecording | null };
export type VoiceShot = { id: string; scene: number; title: string; seconds: number; people: VoicePerson[]; others: string[]; notes: string[] };
export type VoiceStatus = { shots: VoiceShot[]; people: number; recorded: number; missing: number; problems: number };
export type VoiceMatch = { file: string; name: string; shot: string | null; speaker: string | null; note: string; seconds: number | null;
  status: "ok" | "replace" | "ambiguous" | "no_shot" | "no_speaker" | "not_in_shot" | "duplicate" | "bad_file" };
export type VoiceImport = { attached: { shot: string; speaker: string; seconds: number; notes: string[]; replaced: boolean; lengthened_to?: number }[]; failed: { file: string; shot: string | null; why: string }[]; status: VoiceStatus };
export type MakeStatus = { shots: MakeShot[]; active: number; render_dir: string; aspect_ratio?: string; synced: boolean; soundtrack: { kind: string; file?: string; name?: string };
  counts: { shots: number; storyboard: number; keyframe: number; video: number } };
export type MakeSynced = { render_dir: string; shots: number; seconds: number; references: number; look: string; soundtrack: { kind: string } };

// ---------------------------------------------------------------- continuity
export type ContinuityFinding = { id: string; kind: string; shot: string; other: string; severity: "note" | "look" | "likely"; text: string; suggestion: string; status: "open" | "noted" | "dismissed"; apply?: Record<string, string> };
export type ContinuityView = { findings: ContinuityFinding[]; open: number; shots: number };

export type InterchangeResult = { dir: string; problems?: string[]; stems?: string[]; audio_tracks?: { name: string; clips: number }[]; files: Record<string, string>; shots: number; placed: number; missing: string[]; audio: string | null; seconds: number };

// ---------------------------------------------------------------- optional writing help
export type AssistKind = "character" | "environment" | "prop" | "world" | "story" | "shot";
export type AssistPrice = { calls: number; usd: number; local: boolean; note: string; kind: AssistKind; id?: string | null; sends: string };
export type AssistResult = AssistPrice & { proposal: Record<string, unknown>; model: string; estimate?: AssistPrice };

export type FilmProgress = { story: { kind: StoryKind; locked: boolean; as_is: boolean }; cast: { characters: number; places: number; pictures: number; style: boolean };
  shots: { count: number; edited: number }; make: { shots: number; storyboard: number; keyframe: number; video: number } };

export type CastPlan = { tier: string; used: number; limit: number; left: number; can_clone: boolean; slots_used: number; slots: number };
export type CastVoice = { name: string; voice_id: string; voice_name: string; model: string; stability: number; similarity: number; style: number; speed: number; made: "library" | "design" | "clone" };
export type CastStatus = { key: boolean; models: { id: string; label: string; tagged: boolean }[]; people: Record<string, CastVoice>; plan: CastPlan | null; plan_error: string };
export type ElevenVoice = { voice_id: string; name: string; category: string; description: string; labels: Record<string, string>; preview_url: string };
export type CastEstimate = { rows: ({ shot: string; speaker: string; ok: true; characters: number; credits: number; cached: boolean; text: string } | { shot: string; speaker: string; ok: false; why: string })[]; characters: number; credits: number; basis: string };
export type CastPreview = { id: string; file: string; seconds: number };
export type CastTake = { file: string; text: string; model: string; voice_name: string; at: number; current: boolean; another_take?: boolean };
export type LedgerEntry = { id: string; at: number; updated: number; action: string; person: string | null; shot: string | null; status: "prepared" | "confirmed" | "submitted" | "completed" | "refused" | "failed_before_submission" | "uncertain";
  estimate: { unit: string; amount: number | null; basis: string }; actual: { unit: string; amount: number | null; reported: boolean; source: string | null }; note: string; resolved?: { outcome: "not_charged" | "charged"; at: number } };
export type VoiceUsage = { limits: Record<string, number>; count: number; recent: LedgerEntry[]; unresolved: LedgerEntry[];
  by_unit: Record<string, { operations: number; estimated: number; reported: number; unreported_operations: number; estimated_unreported: number }> };
export type AudioAsset = { id: string; kind: "sfx" | "music"; name: string; description: string; category: string; file: string; original_name: string; sha1: string; bytes: number; seconds: number;
  source: "imported" | "generated"; tags: string[]; places: string[]; props: string[]; characters: string[]; scenes: string[]; shots: string[]; genre: string; mood: string; tempo: string;
  generation: Record<string, unknown>; licence: { source: string; note: string; commercial: "yes" | "no" | "unknown" }; approval: "pending" | "approved" | "rejected"; added: number; updated: number; exists?: boolean };
export type AudioLibrary = { assets: AudioAsset[]; removed: number; removed_items: { id: string; kind: "sfx" | "music"; name: string; removed_at: number }[]; categories: Record<"sfx" | "music", { id: string; name: string }[]>; counts: { sfx: number; music: number };
  added?: string[]; skipped?: { file: string; why: string; id?: string }[] };
export type SpokenVersion = { shot: string; key: string; speaker: string; text: string; note: string; pronunciation: string; written: string; source: "person" | "assistant"; updated: number; written_changed: boolean; line_gone: boolean };
export type NaturalSuggestion = { text: string; why: string; adds_words: string[]; keeps_meaning_check: string };
export type AiPrice = { calls: number; usd: number; local: boolean; note: string; sends: string };
export type VoiceCandidate = { voice: ElevenVoice; score: number; why: string[] };
export type VoiceSuggestion = { character: string; proposal?: Partial<VoiceProfile>; wanted: { gender: string; age: string; accent: string; descriptors: string[] }; matches: VoiceCandidate[]; searched: number; note: string; approved: boolean };
export type ScenePlanLine = { shot: string; speaker: string; key: string; text: string; written: string; spoken_version: boolean; state: "missing" | "recorded" | "spoken" | "no_voice"; seconds: number | null;
  characters?: number; credits?: number; cached?: boolean; why?: string };
export type ScenePlan = { scene: number; speakers: { name: string; key: string; voice: string | null; has_voice: boolean; approved: boolean; lines: number }[]; lines: ScenePlanLine[]; missing: number; no_voice: string[];
  estimate: { characters: number; credits: number; basis: string } };
export type SceneResult = { scene: number; results: { shot: string; speaker: string; ok: boolean; attempted: boolean; credits?: number; take?: string; why?: string }[]; spent_credits: number; cap: number; done: number; failed: number; stopped: string | null; note?: string };
export type TableRead = { scene: number; lines: { shot: string; speaker: string; key: string; text: string; file: string | null; seconds: number | null; source: string | null }[]; seconds: number; silent: number };
export type CueFresh = { code: "asset_removed" | "asset_changed" | "asset_missing" | "shot_gone" | "timing_changed" | "after_shot"; why: string };
export type Cue = { id: string; kind: "dialogue" | "sfx" | "ambience" | "music"; asset_id: string | null; asset_name: string | null; asset_file: string | null; asset_seconds: number | null; plan?: { description: string; search: string };
  scene: number; shot: string | null; start: number; duration: number | null; gain_db: number; fade_in: number; fade_out: number; loop: boolean; ducking: "auto" | "on" | "off";
  approval: "suggested" | "approved" | "rejected"; note: string; source: "manual" | "director" | "quick"; fresh: CueFresh[]; needs_sound: boolean; created: number; updated: number; muted?: boolean };
export type CueDialogue = { id: string; kind: "dialogue"; derived: true; scene: number; shot: string; speaker: string; file: string; duration: number | null; start: number; source: string; text: string };
export type CueList = { cues: Cue[]; dialogue: CueDialogue[]; removed: { id: string; kind: string; scene: number | null }[]; id?: string;
  scenes: Record<string, { shots: { id: string; seconds: number; sound: string }[]; seconds: number }>; counts: { cues: number; needs_sound: number; suggested: number } };
export type SoundIdea = { kind: "ambience" | "sfx" | "music"; what: string; why: string; search: string; shot: string | null; loop: boolean; matches: { asset_id: string; name: string; score: number; why: string[]; approved: boolean; seconds: number }[] };
export type SoundIdeas = { scene: number; ideas: SoundIdea[]; source: "quick" | "director" };
export type GenProvider = { id: "elevenlabs_sfx" | "elevenlabs_music" | "kie_suno"; label: string; kind: "sfx" | "music"; cost_known: boolean; cost_words: string; duration: [number, number] | null; loop: boolean;
  instrumental: boolean; has_key: boolean; rights: string; rights_note: string; checked: string };
export type GenEstimate = { expected?: number | null; provider: string; label: string; kind: "sfx" | "music"; key: string; cached: string | null; unit: string; amount: number | null; basis: string; cost_known: boolean;
  needs_unknown_cost_accepted: boolean; needs_rights_ack: boolean; rights_note: string; has_key: boolean };
export type GenResult = { asset?: AudioAsset; assets?: AudioAsset[]; cached: boolean; cost?: { unit: string; estimate?: number | null; reported?: number | null; amount?: number; basis?: string }; note: string; pending?: { task: string; state: string } };
export type RightsReport = { assets: { id: string; name: string; kind: string; commercial: string; in_plan: boolean; source: string; why: string }[]; blocking: { id: string; name: string; why: string }[]; ok: boolean };
export type MixSettings = { schema: number; ducking_db: number; duck_attack: number; duck_release: number; target_lufs: number | null; peak_db: number; mute_lanes: ("dialogue" | "sfx" | "ambience" | "music")[]; solo: string | null };
export type ActionBeat = { n: number; phase: string; kind: "establish" | "action" | "reaction" | "insert" | "aftermath"; actor: string | null; momentum: "A" | "B" | "even"; text: string; seconds: number; framing: string; movement: string; angle: string; lens: string; sound: string; title: string; carrying: string };
export type ActionPlan = { id: string; type: string; scene: number; place: string; weapon: string; sides: { a: string[]; b: string[] }; intensity: string; outcome: string; geography: string; people: string[]; beats: ActionBeat[]; seconds: number;
  warnings: string[]; after: string; applied: string[]; status: "draft" | "applied" };
export type ActionTypes = { types: { id: string; label: string; blurb: string; needs_b: boolean; good_for: string }[]; outcomes: { id: string; label: string }[]; intensity: { id: string; label: string }[]; limits: { min_beats: number; max_beats: number }; advice: string[] };
export type ActionList = { plans: { id: string; created: number; type: string; scene: number; outcome: string; seconds: number; status: string; applied: string[]; beats: number }[] };
export type ReadinessGo = "story" | "cast" | "shots" | "voice" | "soundplan" | "make" | "export";
export type ReadinessItem = { step: string; level: "fix" | "look" | "note"; what: string; why: string; go: ReadinessGo; shot: string | null;
  fix: { kind: "shot_seconds"; shot: string; seconds: number; was: number; label: string } | null };
export type Readiness = { items: ReadinessItem[]; next: ReadinessItem | null; counts: { fix: number; look: number; note: number }; ready: boolean; shots: number; unread: string[]; note: string };
export type SoundRoute = "none" | "voice_over" | "needs_voice" | "audio_in" | "post_sync" | "native";
export type SoundPlan = { video_cost?: { usd: number | null; usd_known: number | null; unknown: number; shots: number; lipsync_shots: number; model: string } | null; tier: string; model: string; model_known: boolean; model_takes_recording: boolean; model_makes_sound: boolean; native_scene: boolean; counts: Record<string, number>; lines_to_speak: number; tts_credits: number; tts_unpriced: number; keep_rate: number; tries: number; note: string; changed?: string[];
  shots: { shot: string; scene: number; title: string; seconds: number; route: SoundRoute; why: string; warnings: string[]; timing: { lead: number; tail: number; end: number; over: number; segments: { speaker: string; start: number; seconds: number; estimated: boolean; file: string | null }[] }; setting: "auto" | "on" | "off"; recommended_setting: string; differs: boolean; speakers: string[]; lines: { speaker: string; line: string; voice_over: boolean; has_voice: boolean; source: string }[] }[] };
export type PacingReport = { film: { shots: number; seconds: number; asl: number; shortest: number; longest: number }; scenes: { number: number; shots: number; seconds: number; asl: number; shortest: number; longest: number; bars: { id: string; seconds: number }[] }[];
  findings: { level: "fix" | "look" | "note"; shot: string | null; scene: number | null; what: string; why: string; tip: string }[]; counts: { fix: number; look: number; note: number }; note: string };
export type CompositionGuideData = { size: string; shot: string; in_prompt: boolean; lines: { text: string; why: string }[]; points: { name: string; x: number; y: number }[]; horizon: number | null; text: string; grid: number[] };
export type PlacesStatus = { places: { id: string; name: string; scenes: number[]; has_description: boolean; has_layout: boolean; has_picture: boolean; missing: boolean }[]; missing: string[]; filled?: { id: string; name: string; description: string }[]; note?: string };
export type MaterialItem = { id: string; type: "storyboard" | "asset" | "shotrow" | "newshot" | "note" | "unsorted" | "skip"; title: string; rel?: string; on: boolean; blocked: string; notes: string[]; preview?: string; why?: string;
  shot?: string; shot_label?: string; how?: string; replaces?: boolean; kind?: "character" | "environment" | "prop"; name?: string; entry?: string | null; entry_name?: string; create?: boolean; media_kind?: string;
  changes?: { label: string; old: unknown; new: unknown }[]; scene?: number; target?: string; excerpt?: string; length?: number };
export type MaterialsPlan = { token: string; items: MaterialItem[]; problems: string[]; counts: Record<string, number>; shots?: { id: string; scene: number; title: string }[]; note?: string };
export type MaterialsResult = { applied: { id: string; type: string; title: string; what: string }[]; failed: { id: string; title: string; why: string }[]; skipped: { id: string; title: string; why: string }[]; changed_since_scan: string[]; backup?: string; message: string };
export type SpendLine = { step: string; label: string; provider: string; unit: string; unit_name: string; operations: number; reported: number; reported_operations: number; estimated: number; estimated_operations: number };
export type SpendingSummary = { lines: SpendLine[]; totals: { unit: string; unit_name: string; operations: number; reported: number; estimated: number }[]; uncertain: { id: string; provider: string; action: string; at: number; shot?: string | null; person?: string | null }[];
  limits: Record<string, number>; problems: string[]; operations: number; note: string };
export type MixPreview = { file: string; seconds: number; cues: number; skipped: { cue: string; why: string }[]; ducked?: boolean; solo: string | null; voices: boolean; whole?: boolean };
export type OutdatedReport = { takes: { shot: string; take: string; kind: "voice_changed" | "voice_removed" | "voice_added"; why: string; speakers: string[]; kept: boolean; options: string[]; note: string }[];
  cues: { id: string; scene: number; shot: string | null; name: string; why: string; codes: string[] }[]; film: { export: string; changed: string[]; why: string } | null; unchecked_takes: number; clean: boolean };
export type RegistryStatus = { models: number; providers: Record<string, { refreshed: number | null; stale: boolean; last_error: string | null }>; note: string };
export type RegistryRefresh = { results: Record<string, { ok: boolean; models?: number; error?: string }>; kept: string };
export type ModelWarnings = { models: { provider: string; model: string; name: string; used_for: string[]; approved: boolean; deprecation: string; availability: string; known: boolean }[];
  warnings: { provider: string; model: string; name: string; used_for: string[]; approved: boolean; why: string; note: string }[] };
