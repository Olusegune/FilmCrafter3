import { SHORTCUTS, GROUPS, find as findShortcut, isTypingKey } from "./shortcuts";
import { Sheet } from "./Sheet";
import { KeyframeTools } from "./KeyframeTools";
import { Fragment, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { toggleShotSound } from "./ShotSound";
import { Palette, type Command } from "./Palette";
import { PlayerOverlays } from "./PlayerOverlays";
import { api, errorText, fmtTime, type BoardShot, type FilmProgress, type LoadedProject, type Plan, type Scene, type Shot, type SongMap } from "./api";
import * as I from "./icons";
import { ACTIVE_STATES, ConfirmRender, defaultProvider, JobChip, latestJobs, RenderPanel } from "./Render";
import { AUTO_MODEL, type Job, type KeyStatus, type Overlay, type ShotHistory, type StyleBibleRead } from "./api";
import { ExportSheet } from "./Export";
import { ShotCamera } from "./Camera";
import { LookPicker, lookName, normalizeLook, useStyles } from "./Looks";
import { effectiveLook, shotLookToSave, styleChangedSince } from "./styleStale";
import { sameAsLabel, saveShotLook, ShotLook } from "./ShotLook";
import { needsAttention, ReviewSheet } from "./Review";
import { ComposeTab } from "./Compose";
import { LightingSheet } from "./Lighting";
import { readFlag, writeFlag } from "./panelState";
import { attentionStarts, COMPACT_HEIGHT, HEIGHT_MAX, HEIGHT_MIN, PPS_MAX, PPS_MIN, readLayout, STRIP_CARD_H, stepAttention, writeLayout } from "./timelineView";
import { QueueChip, RenderQueueSheet, useQueue } from "./RenderQueue";
import { batchOutcome } from "./queueMath";
import { KeyframePanel } from "./Keyframe";
import { addMediaToTimeline, OwnMediaPanel, StillPreview } from "./OwnMedia";
import { ContinuitySheet, ShotContinuity } from "./Continuity";
import { PerformanceSheet, ShotPerformance } from "./Performance";
import { RouteChip, RoutingSheet, useRouting } from "./Routing";
import { ShotRefs } from "./ShotRefs";
import { SupervisorSheet } from "./Supervisor";
import { CleanupSheet } from "./Cleanup";
import { InsertFrameSheet } from "./InsertFrame";
import { LayersPanel } from "./Layers";
import { LayerStrip } from "./LayerStrip";
import { LayerLanes, LANE_H } from "./LayerLanes";
import { UpscaleSheet, type UpscaleRequest } from "./UpscaleSheet";
import { FidelitySheet } from "./FidelitySheet";
import { TransitionHandles } from "./TransitionHandles";
import { snapPoints } from "./laneMath";
import { open as openDialog } from "@tauri-apps/plugin-dialog";
import { PreviewSheet } from "./PreviewSheet";
import { FilmGuide } from "./FilmGuide";
import { ColourMatchSheet } from "./ColourMatch";
import { ColorStudioSheet } from "./ColorStudio";
import { SmartEditorSheet } from "./SmartEditor";
import { PresetsSheet } from "./PresetLibrary";
import { MotionGraphicsSheet } from "./MotionGraphics";
import type { StudioSheet } from "./guideSteps";
import { CUT_H, CutLane, useCut, type CutKey, type CutState } from "./CutLane";
import { applyCut } from "./cutMath";
import { beatGrid } from "./overlayMotion";
import { UpgradePanel } from "./Upgrade";
import { DirectionLibrarySheet } from "./DirectionLibrary";
import { DirectorStyleSheet } from "./DirectorStyle";
import { CommandToast, DirectorCommand, type CommandResult } from "./Command";
import { ApproveKeyframes, LibrarySheet, ShotViewer, StoryCards, useBoard } from "./Board";
import { SelectReview } from "./SelectReview";
import { ScriptSheet } from "./ScriptSheet";
import { DockCtx } from "./Dock";
import { ASPECTS, aspectCss, PROJECT_EVENT, QUALITY, saveFrame } from "./frame";
import { filmDirOfRender } from "./filmPaths";
import { FilmRail, railSteps, type ToolId } from "./FilmRail";
import { CutoutStudio } from "./CutoutStudio";
import { VoiceoverSheet } from "./VoiceoverSheet";
import { speakers, VHEAD_H, VLANE_H, VOICE_ROWS, VOICE_ROWS_MAX, VoiceLanes } from "./VoiceLanes";
import { CHEAD_H, CLANE_H, CueLanes, cueLaneKinds, useCues } from "./CueLanes";
import { ShotVoice, VoicePointer } from "./ShotVoice";
import { useVoiceDrop } from "./VoiceDrop";
import { useVoiceStatus } from "./voiceHooks";
import { isRenderDir } from "./filmPaths";
import { ask } from "./ask";
import { needsSeek, seekForSelection, shotToShow } from "./playerMath";
import { AgentStudio } from "./AgentStudio";

type Selection = { kind: "shot"; id: string } | { kind: "section"; index: number } | null;

export function Studio({ project, onHome, onFilm, onSettings, onReload, startSheet, onStartSheetShown }: {
  project: LoadedProject; onHome: () => void; onFilm?: (stage: string) => void; onSettings: () => void; onReload: () => void;
  startSheet?: StudioSheet | null; onStartSheetShown?: () => void;           // the guide sends you straight to a sheet: it opens once, on arrival
}) {
  const [workspace, setWorkspace] = useState<"agent" | "manual">(() => {
    try { return localStorage.getItem(`fc-workspace:${project.dir}`) === "agent" ? "agent" : "manual"; } catch { return "manual"; }
  });
  const chooseWorkspace = (next: "agent" | "manual") => { setWorkspace(next); try { localStorage.setItem(`fc-workspace:${project.dir}`, next); } catch { /* private storage */ } };
  const map = project.song_map;
  const plan: Plan | null = project.directed ?? project.production;
  const scenes = plan?.scenes ?? [];
  const planShots = useMemo(() => scenes.flatMap((s) => s.shots), [scenes]);
  // The project's shape and quality, kept live so every panel (and the preview boxes) follow a change the moment it is made.
  const [frame, setFrame] = useState({ aspect_ratio: project.project.aspect_ratio ?? "16:9", quality: project.project.quality ?? "standard" });
  useEffect(() => { setFrame({ aspect_ratio: project.project.aspect_ratio ?? "16:9", quality: project.project.quality ?? "standard" }); }, [project.dir]);   // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    const h = (e: Event) => setFrame((f) => ({ ...f, ...(e as CustomEvent).detail }));
    window.addEventListener(PROJECT_EVENT, h);
    return () => window.removeEventListener(PROJECT_EVENT, h);
  }, []);

  const audio = useRef<HTMLAudioElement | null>(null);
  const clock = useRef<{ from: number; base: number } | null>(null);       // the film's clock when there is no sound file to follow (so Play still plays)
  const lengthRef = useRef(0);
  const timeRef = useRef(0);
  const [time, setTime] = useState(0);
  timeRef.current = time;
  const cutState = useCut(project.dir, !!(project.project as { film?: boolean }).film && !!plan, time);         // the film's own cut: where each shot really sits once it has been edited
  const shots = useMemo(() => applyCut(planShots, cutState.cut), [planShots, cutState.cut]);                       // a film that was never edited reads as the plan, exactly as before
  const [playing, setPlaying] = useState(false);
  const [volume, setVolume] = useState(() => { try { const v = Number(localStorage.getItem("pf-volume")); return Number.isFinite(v) && localStorage.getItem("pf-volume") !== null ? v : 0.9; } catch { return 0.9; } });
  const [muted, setMuted] = useState(false);
  const [songError, setSongError] = useState("");
  const [sel, setSel] = useState<Selection>(null);
  // Production Review's "Open Director Mode" (read once for this project)
  const [director, setDirector] = useState(() => {
    try { const k = `pf-open-director:${project.dir}`; const v = localStorage.getItem(k) === "1"; localStorage.removeItem(k); return v; } catch { return false; }
  });
  const [inspector, setInspector] = useState(true);
  const [timelineOpen, setTimelineOpenState] = useState(() => readFlag("pf-timeline", true));     // the timeline can be put away to give the video the room; remembered
  const setTimelineOpen = (v: boolean | ((x: boolean) => boolean)) => setTimelineOpenState((cur) => { const n = typeof v === "function" ? v(cur) : v; writeFlag("pf-timeline", n); return n; });
  const needsRef = useRef<ReadonlySet<string>>(new Set());                                  // the shots that need a look, for the key handler
  const [tlCompact, setTlCompactState] = useState(() => !!readLayout(project.dir).compact);     // compact timeline, remembered for this project
  const setTlCompact = (v: boolean | ((x: boolean) => boolean)) => setTlCompactState((cur) => { const n = typeof v === "function" ? v(cur) : v; writeLayout(project.dir, { compact: n }); return n; });
  const [tlEdit, setTlEditState] = useState(() => !!readLayout(project.dir).edit);               // the full, flexible timeline (Edit) or the calm Film strip (the default), remembered for this project
  const setTlEdit = (v: boolean) => { setTlEditState(v); writeLayout(project.dir, { edit: v }); };
  const [error, setError] = useState("");
  const [jobs, setJobs] = useState<Job[]>(project.jobs ?? []);
  const [keys, setKeys] = useState<KeyStatus>({ openai: false, fal: false, kie: false, google: false, elevenlabs: false });
  const [confirmAll, setConfirmAll] = useState(false);
  const [selecting, setSelecting] = useState(false);
  const [voiceOpen, setVoiceOpen] = useState(false);                     // a film's own recorded voices
  const [voiceShot, setVoiceShot] = useState<string | undefined>(undefined);
  useEffect(() => { const h = (e: Event) => { setVoiceShot((e as CustomEvent).detail as string | undefined); setVoiceOpen(true); }; window.addEventListener("fc-open-voice", h); return () => window.removeEventListener("fc-open-voice", h); }, []);
  const dropped = useVoiceDrop((project.project as { film?: boolean }).film ? filmDirOfRender(project.dir) : null, !voiceOpen);          // drop a recording on a shot on the timeline
  const [exporting, setExporting] = useState(false);
  const [lookOpen, setLookOpen] = useState(false);
  const [reviewing, setReviewing] = useState(false);
  const [queueOpen, setQueueOpen] = useState(false);
  const [lightOpen, setLightOpen] = useState(false);
  useEffect(() => { const h = () => setLightOpen(true); window.addEventListener("pf-open-lighting", h); return () => window.removeEventListener("pf-open-lighting", h); }, []);
  const [batch, setBatch] = useState<{ text: string; failed: number } | null>(null);
  const [commanding, setCommanding] = useState(false);
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [cmdResult, setCmdResult] = useState<CommandResult | null>(null);
  const [keyframes, setKeyframes] = useState<Record<string, Record<string, string>>>(project.keyframes ?? {});
  const [look, setLook] = useState(normalizeLook(project.project.look));
  const [viewing, setViewing] = useState<string | null>(null);
  // right after a production is built, "Make the pictures" opens the Library on the picture maker (once)
  const openMake = useMemo(() => { try { const k = `pf-open-refgen:${project.dir}`; const on = localStorage.getItem(k) === "1"; if (on) localStorage.removeItem(k); return on; } catch { return false; } }, [project.dir]);
  const [libraryOpen, setLibraryOpen] = useState(openMake);
  const [scriptOpen, setScriptOpen] = useState(false);
  const [inspW, setInspW] = useState(() => { try { return Math.min(720, Math.max(320, Number(localStorage.getItem("pf-insp-w")) || 400)); } catch { return 400; } });
  const inspRef = useRef(inspW); inspRef.current = inspW;
  const dragInspector = (e: React.PointerEvent) => {
    const x0 = e.clientX, w0 = inspW;
    const move = (ev: PointerEvent) => setInspW(Math.min(720, Math.max(320, w0 + (x0 - ev.clientX))));
    const up = () => { window.removeEventListener("pointermove", move); window.removeEventListener("pointerup", up);
      try { localStorage.setItem("pf-insp-w", String(Math.round(inspRef.current))); } catch { /* optional */ } };
    window.addEventListener("pointermove", move); window.addEventListener("pointerup", up);
  };
  const [contOpen, setContOpen] = useState(false);
  const [perfOpen, setPerfOpen] = useState(false);
  const [routeOpen, setRouteOpen] = useState(false);
  const [kfTools, setKfTools] = useState(false);                       // Keyframe tools: check hands in every keyframe, redo on one picture model
  useEffect(() => {                                                    // a panel asks to be shown where a layer is: open the timeline and go there
    const show = () => setTimelineOpen(true);
    const go = (e: Event) => { const t = Number((e as CustomEvent<number>).detail); if (Number.isFinite(t)) seek(t); };
    window.addEventListener("pf-show-timeline", show); window.addEventListener("pf-seek", go);
    return () => { window.removeEventListener("pf-show-timeline", show); window.removeEventListener("pf-seek", go); };
  });   // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { const on = () => setKfTools(true); window.addEventListener("pf-open-keyframe-tools", on); return () => window.removeEventListener("pf-open-keyframe-tools", on); }, []);
  const [supOpen, setSupOpen] = useState(false);
  const [cleanOpen, setCleanOpen] = useState(false);
  const [frameOpen, setFrameOpen] = useState(false);
  const [upscaling, setUpscaling] = useState<UpscaleRequest | null>(null);
  const [fidelityShot, setFidelityShot] = useState<string | null>(null);
  useEffect(() => { const on = (e: Event) => setFidelityShot((e as CustomEvent<string>).detail); window.addEventListener("pf-open-fidelity", on); return () => window.removeEventListener("pf-open-fidelity", on); }, []);
  useEffect(() => { const on = (e: Event) => setUpscaling((e as CustomEvent<UpscaleRequest>).detail); window.addEventListener("pf-open-upscale", on); return () => window.removeEventListener("pf-open-upscale", on); }, []);
  const barRef = useRef<HTMLElement | null>(null);
  const narrowWindow = useNarrow(1320);
  const [moreOpen, setMoreOpen] = useState(false);
  const [layersOpen, setLayersOpen] = useState(false);
  const [cutoutsOpen, setCutoutsOpen] = useState(false);
  useEffect(() => { if (layersOpen) setInspector(true); }, [layersOpen]);   // the panel lives in the inspector column, so open it
  const [previewOpen, setPreviewOpen] = useState(false);
  const [colourOpen, setColourOpen] = useState(false);
  const [colorOpen, setColorOpen] = useState(false);
  const [smartOpen, setSmartOpen] = useState(false);
  const [presetsOpen, setPresetsOpen] = useState(false);
  const [motionOpen, setMotionOpen] = useState(false);
  const [polishLeft, setPolishLeft] = useState<("smart" | "color" | "motion")[]>([]);          // "Polish my film": the finishing sheets still to come, in order; closing one opens the next, Stop ends it
  const polishNext = (left: ("smart" | "color" | "motion")[]) => {
    setPolishLeft(left.slice(1));
    const n = left[0];
    if (n) ({ smart: setSmartOpen, color: setColorOpen, motion: setMotionOpen })[n](true);
  };
  useEffect(() => {
    if (!startSheet) return;
    if (startSheet === "polish") polishNext(["smart", "color", "motion"]);
    else if (startSheet === "smart" || startSheet === "motion") ({ smart: setSmartOpen, motion: setMotionOpen })[startSheet](true);
    else openTool(startSheet);
    onStartSheetShown?.();
  }, [startSheet]);                                                              // eslint-disable-line react-hooks/exhaustive-deps
  const closeThen = (set: (v: boolean) => void) => () => { set(false); if (polishLeft.length) polishNext(polishLeft); };
  const [layerSel, setLayerSel] = useState<string | null>(null);
  const [focusLayer, setFocusLayer] = useState<Overlay | null>(null);
  const [focus, setFocus] = useState(false);
  const [keysHelp, setKeysHelp] = useState(false);
  const [rerender, setRerender] = useState<string | null>(null);
  const [night, setNight] = useState<{ active?: boolean; ready?: boolean; shots?: number; with_video?: number; export?: string | null; finished?: number | null; comfy_video?: string } | null>(null);
  const [toastMsg, setToastMsg] = useState("");
  const say = (t: string) => { setToastMsg(t); window.setTimeout(() => setToastMsg(""), 2600); };
  // Undo for changes to a shot (approve, keyframe, end frame, motion, lock): the engine keeps the journal; this offers it
  const [hist, setHist] = useState<ShotHistory | null>(null);
  const [undoOffer, setUndoOffer] = useState<string | null>(null);
  const [histTick, setHistTick] = useState(0);
  const seenHist = useRef<Set<string> | null>(null);                                                  // changes already seen, so only a new one is offered
  const offerTimer = useRef<number | undefined>(undefined);
  const quickApprove = async (id: string) => {   // A: approve this shot's waiting keyframe, or its newest take
    try {
      if (pendingKf[id]) { await api.library(project.dir, "approve_keyframes", { shots: [id] }); say(`Keyframe approved for ${id}`); }
      else { const t = latest.get(id); if (t?.state === "ready") { await api.library(project.dir, "approve", { shot: id, job: t.id }); say(`Take approved for ${id}`); } else say(`${id} has nothing new to approve`); }
      mediaChanged();
    } catch (e) { say(errorText(e)); }
  };
  useEffect(() => {   // automatic backups: on open, then every 10 minutes (skipped when nothing changed)
    const film = (project.project as { film?: boolean }).film ? filmDirOfRender(project.dir) : null;
    const snap = () => { api.backups(project.dir, "backup", "auto").catch(() => {}); if (film) api.filmBackup(film, "make", "auto").catch(() => {}); };
    snap();
    const t = setInterval(snap, 10 * 60_000);
    return () => clearInterval(t);
  }, [project.dir]);
  useEffect(() => {   // overnight status: poll while it runs
    let alive = true;
    const pull = () => api.overnight<typeof night>(project.dir, "status").then((s) => alive && setNight(s)).catch(() => {});
    pull(); const t = window.setInterval(pull, 20000);
    return () => { alive = false; window.clearInterval(t); };
  }, [project.dir]);   // eslint-disable-line react-hooks/exhaustive-deps
  const setFocusMode = useCallback(async (on: boolean) => {
    setFocus(on);
    try { const { getCurrentWindow } = await import("@tauri-apps/api/window"); await getCurrentWindow().setFullscreen(on); } catch { /* browser preview */ }
  }, []);
  const [dlOpen, setDlOpen] = useState(false);
  const [directorStyleOpen, setDirectorStyleOpen] = useState(false);
  useEffect(() => { const f = () => setDlOpen(true); window.addEventListener("pf-open-directions", f); return () => window.removeEventListener("pf-open-directions", f); }, []);
  useEffect(() => { const f = () => setSupOpen(true); window.addEventListener("pf-open-supervisor", f); return () => window.removeEventListener("pf-open-supervisor", f); }, []);
  const { route } = useRouting(project.dir);
  useEffect(() => {
    const on = () => setScriptOpen(true);
    window.addEventListener("pf-open-script", on);
    return () => window.removeEventListener("pf-open-script", on);
  }, []);
  const [pendingKf, setPendingKf] = useState<Record<string, string>>({});
  const [approvingKf, setApprovingKf] = useState(false);
  const styles = useStyles();
  // the rail shows the path (Studio, Review, Export) and keeps the other tools behind "More" until Director Mode, which always shows them; the choice is remembered
  // the shots and scenes that are played in a look of their own (stylebible.py); a read, never a render
  const [ownLooks, setOwnLooks] = useState<StyleBibleRead | null>(null);
  const [shotLookFor, setShotLookFor] = useState<string | null>(null);
  useEffect(() => { let live = true; api.stylebible(project.dir, "read").then((r) => live && setOwnLooks(r)).catch(() => {}); return () => { live = false; }; }, [project.dir, look.style]);
  const pickShotLook = async (style: string) => {
    const id = shotLookFor;
    setShotLookFor(null);
    if (!id) return;
    const inherited = effectiveLook(ownLooks ? { scenes: ownLooks.scenes } : null, id, shots.find((x) => x.id === id)?.scene, look.style);
    try { setOwnLooks(await saveShotLook(project.dir, id, shotLookToSave(style, inherited))); } catch (e) { setError(errorText(e)); }
  };
  // Studio-level File/View menu items.
  useEffect(() => {
    const on = (e: Event) => {
      const id = (e as CustomEvent<string>).detail;
      if (id === "export" && plan) setExporting(true);
      if (id === "mode_simple") setDirector(false);
      if (id === "mode_director") setDirector(true);
      if (id === "inspector") setInspector((v) => !v);
      if (id === "command" && plan) setCommanding(true);
    };
    window.addEventListener("pf-menu", on);
    return () => window.removeEventListener("pf-menu", on);
  }, [plan]);
  const saveLook = async (l: typeof look) => {
    setLookOpen(false);
    try { await api.setLook(project.dir, l); setLook(l); } catch (e) { setError(errorText(e)); }
  };
  const planName = project.directed ? "directed" : "production";
  const isFilm = !!(project.project as { film?: boolean }).film;                       // a film's render project: no song to plan from, so the song-first guides and the Director are not offered
  const goCards = (to?: string) => { if (to && onFilm) onFilm(to); else onHome(); };                  // back to the film workspace (optionally straight to a step of it)
  const filmSwitch = isFilm ? (
    <>
      <div className="mode-toggle film-view" role="group" aria-label="How to see the film" title="The same film two ways. Cards: a wall of pictures and takes, one card per shot. Timeline: this editing studio.">
        <button aria-pressed="false" onClick={() => goCards("studio")}>Cards</button><button className="on" aria-pressed="true">Timeline</button></div>
      <button className="btn" onClick={onHome} title="Back to the film: story, cast and shots">‹ Film</button>
    </>) : null;
  const latest = useMemo(() => latestJobs(jobs, planName), [jobs, planName]);
  // Review judges the newest finished take of each shot (a newer failed attempt doesn't hide it).
  const takes = useMemo(() => latestJobs(jobs.filter((j) => j.state === "ready"), planName), [jobs, planName]);
  const { board, reload: reloadBoard, thumbs, want } = useBoard(project.dir, jobs);
  const refreshPendingKf = useCallback(() => {  // new keyframes waiting for approval
    api.library<Record<string, string>>(project.dir, "pending_keyframes").then((r) => setPendingKf(r ?? {})).catch(() => {});
  }, [project.dir]);
  useEffect(() => { refreshPendingKf(); }, [refreshPendingKf, board]);
  const mediaChanged = useCallback(() => {
    api.loadProject(project.dir).then((p) => { if (p.jobs) mergeJobs(p.jobs); if (p.keyframes) setKeyframes(p.keyframes); }).catch(() => {});
    reloadBoard(); refreshPendingKf();
  }, [project.dir, reloadBoard, refreshPendingKf]);   // eslint-disable-line react-hooks/exhaustive-deps
  const afterHistory = useCallback(() => {
    reloadBoard(); mediaChanged(); setHistTick((t) => t + 1);
    api.loadProject(project.dir).then((p) => { if (p.keyframes) setKeyframes(p.keyframes); }).catch(() => {});
    window.dispatchEvent(new Event("pf-media-changed"));
  }, [project.dir, reloadBoard, mediaChanged]);   // eslint-disable-line react-hooks/exhaustive-deps
  const loadHist = useCallback((offer: boolean) => {
    api.shotHistory(project.dir, "list").then((h) => {
      setHist(h);
      const seen = seenHist.current;
      const fresh = seen ? h.undo.filter((e) => !seen.has(e.id)) : [];
      seenHist.current = new Set([...(seen ?? []), ...h.undo.map((e) => e.id)]);
      if (offer && fresh.length) {
        setUndoOffer(fresh[0].label);
        window.clearTimeout(offerTimer.current);
        offerTimer.current = window.setTimeout(() => setUndoOffer(null), 8000);
      }
    }).catch(() => {});
  }, [project.dir]);
  useEffect(() => { seenHist.current = null; loadHist(false); const on = () => loadHist(true); window.addEventListener("pf-shot-changed", on); return () => window.removeEventListener("pf-shot-changed", on); }, [loadHist]);
  const stepHist = (which: "undo" | "redo") => {
    setUndoOffer(null);
    api.shotHistory(project.dir, which).then((h) => { setHist(h); seenHist.current = new Set([...(seenHist.current ?? []), ...h.undo.map((e) => e.id)]); say(`${which === "undo" ? "Undone" : "Redone"}: ${h.label ?? "change"}`); afterHistory(); }).catch((err) => say(errorText(err)));
  };
  const [mediaNote, setMediaNote] = useState("");
  const [mediaMenu, setMediaMenu] = useState(false);
  const stillable = (board?.shots ?? []).filter((b) => b.keyframe && !b.preview && !b.locked).length;
  const boardShot = useMemo(() => new Map((board?.shots ?? []).map((b) => [b.id, b])), [board]);
  const cutLane = !!(project.project as { film?: boolean }).film && tlEdit && !tlCompact && timelineOpen;          // the cut lane is on screen, so the cut's keys are live
  const cutBoard = useMemo(() => applyCut(board?.shots ?? [], cutState.cut), [board, cutState.cut]);                 // the shot cards, transitions and the rest of the timeline sit where the cut puts each shot
  const cutBoardOrigin = useMemo(() => applyCut(board?.shots ?? [], cutState.cut, true), [board, cutState.cut]);      // voices and planned sound sit where each shot's own time starts

  const queue = useQueue(jobs);
  const prevActive = useRef(0), batchSince = useRef(0);
  useEffect(() => {   // when a run of renders settles, say so and say what came out (also if the window was in the background)
    if (queue.active > 0 && prevActive.current === 0) batchSince.current = Math.floor(Date.now() / 1000) - 5;
    if (queue.active === 0 && prevActive.current > 0 && batchSince.current) {
      const o = batchOutcome(jobs, batchSince.current);
      setBatch({ text: o.text, failed: o.failed });
      batchSince.current = 0;
    }
    prevActive.current = queue.active;
  }, [queue.active]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { if (!batch) return; const t = setTimeout(() => setBatch(null), 25000); return () => clearTimeout(t); }, [batch]);

  const mergeJobs = useCallback((incoming: Job[]) => setJobs((cur) => {
    const byId = new Map(cur.map((j) => [j.id, j]));
    for (const j of incoming) byId.set(j.id, { ...byId.get(j.id), ...j });
    return [...byId.values()];
  }), []);

  useEffect(() => {
    let alive = true;
    const pull = () => { if (document.visibilityState === "visible") api.loadProject(project.dir).then((p) => alive && p.jobs && mergeJobs(p.jobs)).catch(() => {}); };
    const t = window.setInterval(pull, 8000);
    window.addEventListener("focus", pull);
    return () => { alive = false; window.clearInterval(t); window.removeEventListener("focus", pull); };
  }, [project.dir, mergeJobs]);

  useEffect(() => {
    const refresh = () => api.keyStatus().then(setKeys).catch(() => {});
    refresh();
    window.addEventListener("pf-keys-changed", refresh);
    // Reconnect to renders that were running when the app closed (PRD §29).
    if ((project.jobs ?? []).some((j) => ACTIVE_STATES.includes(j.state))) api.ensureRenderer(project.dir);
    const un = api.onEngine((e) => { if (e.event === "job" && e.job) mergeJobs([e.job as Job]); });
    return () => { window.removeEventListener("pf-keys-changed", refresh); un.then((f) => f()); };
  }, [project.dir, project.jobs, mergeJobs]);

  useEffect(() => {
    if (!project.song_path) return;
    const a = new Audio(api.mediaUrl(project.song_path));
    a.preload = "auto";
    audio.current = a;
    a.onended = () => setPlaying(false);
    a.onerror = () => setSongError((isFilm ? "The soundtrack can't be played. It may have been moved or deleted from the film's folder." : "The song file can't be played. It may have been moved or deleted from the project folder."));
    a.oncanplay = () => setSongError("");
    return () => { a.pause(); audio.current = null; };
  }, [project.song_path]);

  useEffect(() => {
    if (audio.current) audio.current.volume = muted ? 0 : volume;
    try { localStorage.setItem("pf-volume", String(volume)); } catch { /* optional */ }
  }, [volume, muted, project.song_path]);

  useEffect(() => {
    let raf = 0;
    const tick = () => {
      if (audio.current) setTime(audio.current.currentTime);
      else if (clock.current) {
        const t = clock.current.base + (performance.now() - clock.current.from) / 1000;
        if (t >= lengthRef.current) { clock.current = null; setTime(lengthRef.current); setPlaying(false); return; }
        setTime(t);
      }
      raf = requestAnimationFrame(tick);
    };
    if (playing) raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [playing]);

  const toggle = useCallback(() => {
    const a = audio.current;
    if (!a) {                                                             // no sound file: the picture plays on its own clock
      if (clock.current) { clock.current = null; setPlaying(false); return; }
      if (!lengthRef.current) return;
      const from = timeRef.current >= lengthRef.current - 0.05 ? 0 : timeRef.current;
      clock.current = { from: performance.now(), base: from };
      setTime(from);
      setPlaying(true);
      return;
    }
    if (a.paused) {
      a.play().then(() => setPlaying(true)).catch((e) => {
        setPlaying(false);
        setSongError(a.error ? (isFilm ? "The soundtrack can't be played. It may have been moved or deleted from the film's folder." : "The song file can't be played. It may have been moved or deleted from the project folder.") : `Couldn't start playback: ${e?.message ?? e}`);
      });
    } else { a.pause(); setPlaying(false); }
  }, []);
  const seek = useCallback((t: number) => {
    const a = audio.current;
    const c = Math.max(0, Math.min(t, map?.duration ?? 0));
    if (a) a.currentTime = c;
    if (clock.current) clock.current = { from: performance.now(), base: c };      // scrubbing while it plays carries on from there
    setTime(c);
  }, [map]);
  lengthRef.current = map?.duration ?? 0;

  useEffect(() => {
    const k = (e: KeyboardEvent) => {
      const typing = isTypingKey(e);
      const el = e.target as HTMLElement;
      const hit = findShortcut(e, { typing });
      if (e.key === "Escape" && focus) { setFocusMode(false); return; }
      if (!hit) return;
      // Space (and Enter) on a focused button or link belongs to that control, so keyboard users can press it
      if (e.code === "Space" && /^(BUTTON|A|SUMMARY)$/.test(el.tagName)) return;
      e.preventDefault();
      const starts = shots.map((s) => s.start).sort((a, b) => a - b);
      const cur = shots.find((s) => time >= s.start && time < s.end);
      switch (hit.id) {
        case "command": if (plan) setCommanding(true); break;
        case "play": case "play_k": toggle(); break;
        case "mute": setMuted((m) => !m); break;
        case "focus": setFocusMode(!focus); break;
        case "back5": case "back5s": seek(time - 5); break;
        case "fwd5": case "fwd5s": seek(time + 5); break;
        case "start": seek(0); break;
        case "end": seek(map?.duration ?? 0); break;
        case "prev": { const prev = [...starts].reverse().find((t) => t < time - 0.25); seek(prev ?? 0); break; }
        case "next": { const next = starts.find((t) => t > time + 0.05); if (next !== undefined) seek(next); break; }
        case "prev_flag": case "next_flag": {
          const t = stepAttention(attentionStarts(shots, needsRef.current), time, hit.id === "next_flag" ? 1 : -1);
          if (t === null) say(hit.id === "next_flag" ? "No later shot needs attention." : "No earlier shot needs attention."); else seek(t);
          break;
        }
        case "undo_shot": case "redo_shot": stepHist(hit.id === "undo_shot" ? "undo" : "redo"); break;
        case "approve": if (cur) quickApprove(cur.id); break;
        case "frames": if (cur) { setSel({ kind: "shot", id: cur.id }); setInspector(true); setTimeout(() => window.dispatchEvent(new CustomEvent("pf-open-tab", { detail: "frames" })), 50); } break;
        case "rerender": if (cur) { setSel({ kind: "shot", id: cur.id }); setInspector(true); setRerender(cur.id); } break;
        case "layers": if (plan) setLayersOpen((v) => !v); break;
        case "add_text": if (plan) api.overlays(project.dir, "add", { kind: "text", text: "Your text", y: 0.5, anim: "rise", start: Math.max(0, Math.floor(time * 10) / 10), end: Math.min(map?.duration ?? time + 4, Math.max(0, Math.floor(time * 10) / 10) + 4) })
          .then((r) => { window.dispatchEvent(new Event("pf-overlays-changed")); setLayerSel(r[r.length - 1]?.id ?? null); setLayersOpen(true); }).catch((err) => say(errorText(err))); break;
        case "hide_layer": if (layerSel) api.overlays<Overlay[]>(project.dir, "list").then((all) => { const o = all.find((x) => x.id === layerSel); return o ? api.overlays(project.dir, "update", { id: o.id, enabled: !o.enabled }) : null; })
          .then(() => window.dispatchEvent(new Event("pf-overlays-changed"))).catch((err) => say(errorText(err))); break;
        case "keys": setKeysHelp((v) => !v); break;
        case "timeline": setTimelineOpen((v) => !v); break;
        case "timeline_compact": if (timelineOpen) setTlCompact((v) => !v); break;
        case "palette": setPaletteOpen((v) => !v); break;
        case "undo": case "redo": case "redo_y": if (layersOpen) window.dispatchEvent(new CustomEvent("pf-layers-history", { detail: hit.id === "undo" ? "undo" : "redo" })); else if (cutLane) window.dispatchEvent(new CustomEvent<CutKey>("pf-cut-key", { detail: hit.id === "undo" ? "undo" : "redo" })); break;      // the cut (and the grades, which share its history) when the layers are not the thing being edited
        case "cut_split": case "cut_delete": case "cut_ripple_delete": case "cut_trim_in": case "cut_trim_out": case "cut_marker":
          if (cutLane) window.dispatchEvent(new CustomEvent<CutKey>("pf-cut-key", { detail: hit.id.slice(4) as CutKey })); break;
        case "shot_sound": if (cur) toggleShotSound(project.dir, cur.id).then((m) => { say(m); window.dispatchEvent(new Event("pf-media-changed")); }).catch((err) => say(errorText(err))); break;
      }
    };
    window.addEventListener("keydown", k);
    return () => window.removeEventListener("keydown", k);
  }, [toggle, seek, time, focus, setFocusMode, shots, map, plan, layersOpen, layerSel, cutLane]);   // eslint-disable-line react-hooks/exhaustive-deps

  const current = shots.find((s) => time >= s.start && time < s.end) ?? null;
  const shown = shotToShow(shots, sel?.kind === "shot" ? sel.id : null, time) ?? current;       // the shot under the playhead: a selection must never hold the picture while you scrub
  const selShotId = sel?.kind === "shot" ? sel.id : null;
  useEffect(() => {                                                    // choosing a shot elsewhere (the inspector, a list) puts the playhead on it, so the picture and the time agree
    if (!selShotId) return;
    const t = seekForSelection(shots, selShotId, timeRef.current);
    if (t !== null) seek(t);
  }, [selShotId]);   // eslint-disable-line react-hooks/exhaustive-deps
  // the player's caption follows your edits (Export > Lyric captions): changed wording, hidden lines
  const [capLines, setCapLines] = useState<{ text: string; start: number; end: number; hidden: boolean }[]>([]);
  useEffect(() => {
    const pull = () => api.captions(project.dir, "get").then((c) => setCapLines(c.lines)).catch(() => setCapLines([]));
    pull();
    window.addEventListener("pf-captions-changed", pull);
    return () => window.removeEventListener("pf-captions-changed", pull);
  }, [project.dir, map]);
  const lyric = capLines.length
    ? capLines.find((l) => !l.hidden && time >= l.start && time <= l.end)
    : map?.lyrics.find((l) => l.start != null && l.end != null && time >= l.start && time <= l.end + 0.3);

  const needsLook = new Set(shots.filter((s) => (s.flags?.length ?? 0) > 0 || needsAttention(latest.get(s.id)) || boardShot.get(s.id)?.keyframe_check === "fail").map((s) => s.id));
  needsRef.current = needsLook;
  const flagged = needsLook.size;
  // shots cut from the song alone have nothing described to render yet
  const described = (s: Shot) => !!((s as { visual_prompt?: string }).visual_prompt || s.beats?.length || (s as { description?: string }).description);
  const toRender = shots.filter((s) => { const j = latest.get(s.id); return (!j || j.state === "failed") && described(s); });
  const folded = useBarFold(barRef, [director, !!night?.active, Object.keys(pendingKf).length, shots.length, !!plan, project.directed, keys.fal, keys.kie, inspector, toRender.length]);
  const narrowBar = narrowWindow || folded;
  const renderAll = async () => {
    setConfirmAll(false);
    // the project's mode decides Auto (Local First: ComfyUI; Balanced: cheapest; Premium: best)
    const provider = route?.video.provider ?? defaultProvider(keys);
    const model = route?.video.provider ? route.video.model! : AUTO_MODEL[provider];
    if (route?.mode === "local" && !route.video.provider) { setError(route.video.reason ?? "Local First: nothing to render with."); return; }
    try { mergeJobs(await api.queueRender(project.dir, toRender.map((s) => s.id), provider, model, {})); }
    catch (e) { setError(errorText(e)); }
  };

  const openTool = (id: ToolId) => {                                    // a tool of the rail, opened here; the same tools open from every other screen of the film by coming here with the tool already open
    switch (id) {
      case "project": setWorkspace("manual"); setSel(null); setInspector(true); break;
      case "library": setLibraryOpen(true); break;
      case "looks": setDlOpen(true); break;
      case "review": setReviewing(true); break;
      case "agent": chooseWorkspace("agent"); break;
      case "supervisor": setSupOpen(true); break;
      case "acting": setPerfOpen(true); break;
      case "continuity": setContOpen(true); break;
      case "layers": setLayersOpen((v) => !v); break;
      case "lighting": setLightOpen(true); break;
      case "presets": setPresetsOpen(true); break;
      case "color": setColorOpen(true); break;
      case "colourmatch": setColourOpen(true); break;
      case "clean": setCleanOpen(true); break;
      case "cutouts": setCutoutsOpen(true); break;
    }
  };
  const railProgress = useRailProgress(isFilm ? filmDirOfRender(project.dir) : null);
  const rail = <FilmRail hasShots={!!plan} onHome={onHome} onSettings={onSettings} onTool={openTool} alwaysMore={director || layersOpen} activeTool={layersOpen ? "layers" : workspace === "agent" ? "agent" : null}
                         badges={{ review: shots.filter((s) => needsAttention(takes.get(s.id))).length }}
                         steps={railSteps({ pro: director, progress: railProgress, active: "make", disabled: plan ? undefined : { export: "Needs a shot plan first: press Direct My Video." },
                                            go: (id) => { if (id === "export") setExporting(true); else if (id === "make") { if (workspace === "agent") chooseWorkspace("manual"); } else if (onFilm) onFilm(id); } })} />;
  if (workspace === "agent") return <AgentStudio project={{ ...project, jobs }} onHome={onHome} onSettings={onSettings} rail={rail} onManual={() => chooseWorkspace("manual")} />;

  return (
    <div className={`studio ${focus ? "focus" : ""}`}>
      {focus && <button className="btn ghost focus-exit" onClick={() => setFocusMode(false)}>Exit full screen (Esc)</button>}
      {rail}

      <main className="center">
        <header className="topbar" ref={barRef}>
          <div>
            <div className="title">{project.project.title}</div>
            {map && <div className="meta num">{isFilm ? "" : `${Math.round(map.bpm)} BPM · `}{fmtTime(map.duration)} · {shots.length} shots
              {isFilm ? " · Film" : project.directed ? " · Directed" : plan ? " · Planned from script" : ""}</div>}
          </div>
          {filmSwitch}
          <button className="btn ghost" onClick={() => chooseWorkspace("agent")} title="Guided production with milestone approvals">Agent Studio</button>
          <button className="btn ghost" onClick={() => setDirectorStyleOpen(true)} title="Optional camera, lens, light and pace traits from a worldwide filmmaker">Director style</button>
          <div className="grow" />
          {!(isFilm && narrowBar) && <div className="mode-toggle" role="group" aria-label="Mode">
            <button className={!director ? "on" : ""} onClick={() => setDirector(false)}>Simple</button>
            <button className={director ? "on" : ""} onClick={() => setDirector(true)}>Director Mode</button>
          </div>}
          {night?.active && <button className="spend-chip route-chip" title="Stop the overnight render" onClick={async () => setNight(await api.overnight(project.dir, "stop"))}>
            <span className="spin sm" /> Overnight · {night.with_video}/{night.shots}</button>}
          <QueueChip q={queue} onOpen={() => setQueueOpen(true)} />
          <RouteChip dir={project.dir} onOpen={() => setRouteOpen(true)} sig={jobs.filter((j) => j.state === "ready").length + ":" + jobs.length} />
          {plan && <div className="menu-wrap">
            <button className="btn ghost" onClick={() => setMediaMenu((v) => !v)} aria-expanded={mediaMenu}>My media ▾</button>
            {mediaMenu && <div className="menu glass" role="menu" onMouseLeave={() => setMediaMenu(false)}>
              <button role="menuitem" onClick={async () => { setMediaMenu(false);
                try { const r = await addMediaToTimeline(project.dir, sel?.kind === "shot" ? sel.id : undefined); if (r) { mediaChanged();
                  setMediaNote(`Placed ${r.placed.length} file${r.placed.length === 1 ? "" : "s"}${r.skipped.length ? `; ${r.skipped.length} not placed (${r.skipped[0].reason})` : ""}.`); } }
                catch (e) { setMediaNote(errorText(e)); } }}>
                <b>Add images and clips…</b><span>One per empty shot, in order{sel?.kind === "shot" ? `, from ${sel.id}` : ""}. Free.</span></button>
              <button role="menuitem" onClick={() => { setMediaMenu(false); setFrameOpen(true); }}>
                <b>Insert a frame…</b><span>A card, picture, clip or generated shot of your own length{sel?.kind === "shot" ? `, next to ${sel.id}` : ""}.</span></button>
              <button role="menuitem" disabled={!night?.ready || !!night?.active} onClick={async () => { setMediaMenu(false);
                try {
                  let r = await api.overnight<{ keyframes_queued?: number; needs_confirm?: boolean; keyframes?: number; label?: string; provider?: string; usd?: number }>(project.dir, "start");
                  if (r.needs_confirm) {
                    if (!await ask(`Hybrid overnight: ${r.keyframes} keyframes on ${r.label} (${r.provider}) for about $${(r.usd ?? 0).toFixed(2)}, then every video free on your ComfyUI, then the export. Start?`)) return;
                    r = await api.overnight(project.dir, "start", true);
                  }
                  setNight(await api.overnight(project.dir, "status"));
                  setMediaNote(`Overnight started: ${r.keyframes_queued ?? 0} keyframes first, then videos on ComfyUI, then an export. Leave FilmCrafter and ComfyUI running.`); }
                catch (e) { setMediaNote(errorText(e)); } }}>
                <b>Render overnight on ComfyUI</b><span>{!night?.ready ? "Needs ComfyUI with a video workflow (Settings → Find ComfyUI)."
                  : (night as { keyframes_from?: string }).keyframes_from === "comfyui" ? "Keyframes, videos and the final cut on your own computer, while you sleep. Free."
                  : "Hybrid: keyframes on Kie (price shown first), videos free on ComfyUI, then the final cut."}</span></button>
              <button role="menuitem" disabled={stillable === 0} onClick={async () => { setMediaMenu(false);
                try { const r = await api.media<{ made: string[] }>(project.dir, "stills"); mediaChanged();
                  setMediaNote(`${r.made.length} moving stills made. Export any time; render video later only where you want it.`); } catch (e) { setMediaNote(errorText(e)); } }}>
                <b>Moving stills from keyframes ({stillable})</b><span>Shots with a keyframe but no video get a slow camera move. Free.</span></button>
            </div>}
          </div>}
          {plan && !narrowBar && <button className="btn ghost cmd-btn" onClick={() => setCommanding(true)} title="Tell the Director what to change, in plain words (Ctrl+K)">Ask the Director <kbd>Ctrl K</kbd></button>}
          {narrowBar ? <div className="menu-wrap"><button className="btn ghost" onClick={() => setMoreOpen((v) => !v)} aria-expanded={moreOpen} aria-haspopup="menu">More ▾</button>
            {moreOpen && <div className="menu glass tb-more" role="menu" onClick={() => setMoreOpen(false)} onMouseLeave={() => setMoreOpen(false)}>
          {plan && <button className="btn" role="menuitem" onClick={() => setCommanding(true)} title="Tell the Director what to change, in plain words (Ctrl+K)">Ask the Director <kbd>Ctrl K</kbd></button>}
          {isFilm && <button className="btn" role="menuitem" aria-pressed={director} onClick={() => setDirector(!director)} title="Show the set, wardrobe, continuity and every scene note in the inspector">{director ? "Director Mode: on" : "Director Mode: off"}</button>}
          {Object.keys(pendingKf).length > 0 && <button className="btn" onClick={() => setApprovingKf(true)}
                      title="Approve the newest keyframe for every shot without one">Approve {Object.keys(pendingKf).length} keyframes</button>}
          {plan && board && <button className="btn" onClick={() => setSelecting(true)}
                  title="Choose shots, approve their keyframes, then pay for video only where the still is right">Select &amp; review</button>}
          {isFilm && <button className="btn" onClick={() => setVoiceOpen(true)} title="Attach your own recorded voices to the people in the shots">Voiceover</button>}
          {plan && (keys.fal || keys.kie) && toRender.length > 0 && <button className={`btn ${project.directed ? "hero" : ""}`} onClick={() => setConfirmAll(true)}
                                   disabled={toRender.length === 0}>Render {toRender.length === shots.length ? "all" : toRender.length} shots</button>}
            </div>}</div>
            : <>
          {Object.keys(pendingKf).length > 0 && <button className="btn" onClick={() => setApprovingKf(true)}
                      title="Approve the newest keyframe for every shot without one">Approve {Object.keys(pendingKf).length} keyframes</button>}
          {plan && board && <button className="btn" onClick={() => setSelecting(true)}
                  title="Choose shots, approve their keyframes, then pay for video only where the still is right">Select &amp; review</button>}
          {isFilm && <button className="btn" onClick={() => setVoiceOpen(true)} title="Attach your own recorded voices to the people in the shots">Voiceover</button>}
          {plan && (keys.fal || keys.kie) && toRender.length > 0 && <button className={`btn ${project.directed ? "hero" : ""}`} onClick={() => setConfirmAll(true)}
                                   disabled={toRender.length === 0}>Render {toRender.length === shots.length ? "all" : toRender.length} shots</button>}
            </>}
          <button className="icon-btn" onClick={() => setFocusMode(true)} title="Full screen: just the video (F)" aria-label="Full screen">⛶</button>
          <button className="icon-btn" onClick={() => setTimelineOpen((v) => !v)} title={timelineOpen ? "Hide the timeline (Ctrl+J)" : "Show the timeline (Ctrl+J)"} aria-label={timelineOpen ? "Hide the timeline" : "Show the timeline"} aria-pressed={timelineOpen}><I.PanelBottom /></button>
          <button className="icon-btn" onClick={() => setInspector((v) => !v)} title="Inspector" aria-label="Toggle inspector"><I.Panel /></button>
        </header>
        {!plan && <div className="empty" style={{ padding: 40 }}>This film has no shots yet. Make them in the film's Shots step, then open the Studio again.</div>}
        <div className="viewer-wrap" style={plan ? undefined : { display: "none" }}>
          <div className="stage">
          <div className="viewer" style={{ ["--ar" as string]: aspectNum(project.project.aspect_ratio) }}>
            {shown && boardShot.get(shown.id)?.preview && boardShot.get(shown.id)!.preview_kind === "image" ?
              <StillPreview src={api.mediaUrl(`${project.dir}/${boardShot.get(shown.id)!.preview}`)} motion={boardShot.get(shown.id)!.preview_motion} drift={boardShot.get(shown.id)!.preview_drift} playing={playing}
                            duration={shown.end - shown.start} offset={time - shown.start} /> :
             shown && boardShot.get(shown.id)?.preview && /\.(mp4|mov|webm|m4v)$/i.test(boardShot.get(shown.id)!.preview!) ?
              <Clip src={api.mediaUrl(`${project.dir}/${boardShot.get(shown.id)!.preview_proxy ?? boardShot.get(shown.id)!.preview}`)} offset={time - shown.start + ((shown as { src_in?: number }).src_in ?? 0)} playing={playing} /> :
              shown && boardShot.get(shown.id)?.keyframe ? <img className="clip" alt="" src={api.mediaUrl(`${project.dir}/${boardShot.get(shown.id)!.keyframe}`)} /> : null}
            {shown ? <Storyboard shot={shown} scene={scenes.find((s) => s.number === shown.scene)} job={latest.get(shown.id)}
                                 hidden={!!boardShot.get(shown.id)?.preview || !!boardShot.get(shown.id)?.keyframe} /> :
              <div className="empty">{isFilm ? "Press play to preview the film" : plan ? "Press play to preview the song map" : "Add a script or press Direct My Video to plan shots"}</div>}
            <PlayerOverlays dir={project.dir} time={time} playing={playing} beat={beatGrid(map)} accents={map?.accents} selected={layersOpen ? layerSel : null} onSelect={layersOpen ? setLayerSel : undefined} />
            <div className="subtitle" style={{ opacity: lyric ? 1 : 0 }}>{lyric?.text ?? ""}</div>
          </div>
          </div>
          {layersOpen && focusLayer && <LayerStrip layer={focusLayer} duration={map?.duration ?? 0} time={time} onSeek={seek} />}
          <div className="transport glass">
            <button className="icon-btn" onClick={() => { const starts = shots.map((s) => s.start).sort((a, b) => a - b); const prev = [...starts].reverse().find((t) => t < time - 0.75); seek(prev ?? 0); }} aria-label="Previous shot" title="Previous shot (press again to go further back)"><I.SkipBack size={18} /></button>
            <button className="play-btn" onClick={toggle} aria-label={playing ? "Pause" : "Play"}>{playing ? <I.Pause /> : <I.Play />}</button>
            <button className="icon-btn" onClick={() => { const next = shots.map((s) => s.start).sort((a, b) => a - b).find((t) => t > time + 0.05); seek(next ?? (map?.duration ?? 0)); }} aria-label="Next shot" title="Next shot"><I.SkipFwd size={18} /></button>
            <div className="time num">{fmtTime(time)} / {fmtTime(map?.duration ?? 0)}</div>
            <button className="btn small ghost" onClick={() => { if (playing) toggle(); setPreviewOpen(true); }} title="A quick small version of the next few seconds, with layers and sound" disabled={!plan}>Preview</button>
            <input className="scrub" type="range" min={0} max={map?.duration ?? 0} step={0.04} value={Math.min(time, map?.duration ?? 0)}
                   aria-label="Scrub through the video" onChange={(e) => seek(Number(e.target.value))}
                   style={{ ["--v" as string]: `${map?.duration ? (time / map.duration) * 100 : 0}%` }} />
            <div className="volume">
              <button className="icon-btn" onClick={() => setMuted((m) => !m)} aria-label={muted ? "Unmute" : "Mute"} title={muted ? "Unmute" : "Mute"}>
                {muted || volume === 0 ? <I.Mute size={18} /> : <I.Volume size={18} />}</button>
              <input type="range" min={0} max={1} step={0.01} value={muted ? 0 : volume} aria-label="Volume"
                     onChange={(e) => { setVolume(Number(e.target.value)); setMuted(false); }}
                     style={{ ["--v" as string]: `${(muted ? 0 : volume) * 100}%` }} />
            </div>
          </div>
        </div>
      </main>

      <aside className={`inspector ${inspector ? "" : "collapsed"}`} aria-label="Inspector" style={inspector ? { width: narrowBar ? Math.min(inspW, Math.max(300, Math.round(window.innerWidth * 0.31))) : inspW } : undefined}>
        {inspector && <div className="insp-resize" onPointerDown={dragInspector} title="Drag to resize" role="separator" aria-orientation="vertical" />}
        {layersOpen && <LayersPanel docked dir={project.dir} time={time} selected={layerSel} onSelect={setLayerSel} onFocus={setFocusLayer} onClose={() => { setLayersOpen(false); setLayerSel(null); setFocusLayer(null); }} />}
        <div className="insp-host" style={layersOpen ? { display: "none" } : { display: "contents" }}>
        <Inspector key={histTick} sel={sel} shots={shots} scenes={scenes} map={map} plan={plan} director={director} project={project}
                   onClose={() => setSel(null)} lookLabel={lookName(styles, look)} onLook={() => setLookOpen(true)}
                   renderPanel={(s: Shot): ShotTabs => {
                     const pj = jobs.filter((j) => j.plan === planName && j.shot_id === s.id && j.state !== "dismissed");
                     const vid = pj.filter((j) => j.kind !== "image");
                     const kfRef = keyframes[planName]?.[s.id] ?? null;
                     const shotLook = effectiveLook(ownLooks, s.id, s.scene, look.style);
                     return {
                       styleChanged: styleChangedSince(pj, shotLook),
                       look: { name: styles.find((x) => x.id === shotLook)?.name ?? lookName(styles, look), own: !!ownLooks?.shots[s.id], onOpen: () => setShotLookFor(s.id) },
                       badges: {
                         keyframe: pj.some((j) => j.kind === "image" && ACTIVE_STATES.includes(j.state)) ? "busy" : kfRef ? "ok" : "",
                         frames: boardShot.get(s.id)?.end_mode && boardShot.get(s.id)?.end_mode !== "none" ? "ok" : "",
                         video: vid.some((j) => ACTIVE_STATES.includes(j.state)) ? "busy" : vid.some((j) => j.state === "ready") ? "ok" : vid.some((j) => j.state === "failed") ? "bad" : "",
                         media: boardShot.get(s.id)?.versions.some((v) => v.provider === "own") ? "ok" : "",
                       },
                       shot: <>
                         {board && <ShotRefs dir={project.dir} shot={boardShot.get(s.id)} library={board.library} thumbs={thumbs} want={want} onChanged={reloadBoard} />}
                         <ShotCamera dir={project.dir} shotId={s.id} sceneShotIds={shots.filter((x) => x.scene === s.scene).map((x) => x.id)} onChanged={mediaChanged} />
                         <ShotPerformance dir={project.dir} shotId={s.id} onChanged={reloadBoard} />
                         <ShotContinuity dir={project.dir} shotId={s.id} onChanged={mediaChanged} />
                       </>,
                       keyframe: (go) => <><ShotLook dir={project.dir} shotId={s.id} own={ownLooks} filmLook={look.style} sceneLook={effectiveLook(ownLooks ? { scenes: ownLooks.scenes } : null, s.id, s.scene, look.style)} onChanged={setOwnLooks} />
                                      <KeyframePanel dir={project.dir} shot={s} plan={planName} aspect={aspectCss(frame.aspect_ratio)} frame={frame.aspect_ratio} quality={frame.quality}
                                      jobs={jobs.filter((j) => j.plan === planName)} keys={keys} director={director} approved={kfRef} onJobs={mergeJobs} onSettings={onSettings}
                                      onNext={() => go("video")}
                                      onApproved={(ref) => { setKeyframes((k) => ({ ...k, [planName]: { ...(k[planName] ?? {}), [s.id]: ref ?? "" } })); reloadBoard(); }} /></>,
                       frames: (go) => <ComposeTab dir={project.dir} shot={s.id} keys={keys} onOpenKeyframe={() => go("keyframe")}
                                      refsPanel={board ? <ShotRefs dir={project.dir} shot={boardShot.get(s.id)} library={board.library} thumbs={thumbs} want={want} onChanged={reloadBoard} /> : null}
                                      onChanged={() => { reloadBoard(); api.loadProject(project.dir).then((p) => { if (p.keyframes) setKeyframes(p.keyframes); }).catch(() => {}); }}
                                      onQueued={(j) => { mergeJobs(j); go("video"); }} />,
                       video: (go) => <>
                         {(project.project as { film?: boolean }).film && <ShotVoice dir={filmDirOfRender(project.dir)} shotId={s.id} />}
                         <RenderPanel dir={project.dir} shot={s} jobs={jobs.filter((j) => j.plan === planName)}
                                      director={director} keys={keys} onQueued={mergeJobs} onSettings={onSettings} frame={frame.aspect_ratio} quality={frame.quality}
                                      onBack={() => go("keyframe")} lookId={look.style} keyframeKey={kfRef}
                                      approvedTake={boardShot.get(s.id)?.approved ?? null} onTakeChosen={mediaChanged} />
                         <UpgradePanel dir={project.dir} shot={boardShot.get(s.id)} open={rerender === s.id} onDone={() => { setRerender(null); mediaChanged(); }} />
                       </>,
                       media: <OwnMediaPanel dir={project.dir} shot={boardShot.get(s.id)} onChanged={mediaChanged} />,
                     };
                   }} />
        </div>
      </aside>

      {!timelineOpen && <button className="tl-restore" onClick={() => setTimelineOpen(true)} aria-label="Show the timeline" title="Show the timeline (Ctrl+J)"><I.PanelBottom size={14} /> Show the timeline <span className="dim num">{fmtTime(time)}{map ? ` / ${fmtTime(map.duration)}` : ""}</span></button>}
      {timelineOpen && <Timeline key={project.dir} edit={tlEdit} onEdit={setTlEdit} compact={tlCompact} onCompact={() => setTlCompact((v) => !v)} map={map} time={time} sel={sel} flagged={flagged} dir={project.dir} board={cutBoard} boardOrigin={cutBoardOrigin} cut={cutState} onSuggest={() => setSmartOpen(true)} onMotion={() => setMotionOpen(true)} thumbs={thumbs} want={want}
                layerSel={layerSel} onLayerSelect={(id) => { setLayerSel(id); if (id) setLayersOpen(true); }} onBoardChanged={reloadBoard}
                onOpen={(id) => setViewing(id)}
                onSeek={seek} onSelect={(s) => { setSel(s); if (s?.kind === "shot") { const sh = shots.find((x) => x.id === s.id); if (sh) seek(sh.start); } }} />}
      {viewing && boardShot.get(viewing) && board && <ShotViewer dir={project.dir} shot={boardShot.get(viewing)!} library={board.library}
                                    onClose={() => setViewing(null)} onChanged={reloadBoard}
                                    onRegenerate={() => { setSel({ kind: "shot", id: viewing }); setInspector(true); setViewing(null); }} />}
      {approvingKf && <ApproveKeyframes dir={project.dir} pending={pendingKf} onClose={() => setApprovingKf(false)}
                                        onDone={() => { setApprovingKf(false); refreshPendingKf(); reloadBoard(); onReload(); }} />}
      {perfOpen && <PerformanceSheet dir={project.dir} scenes={scenes.map((s) => ({ number: s.number, heading: s.heading }))}
                                     characters={[...new Set(shots.flatMap((s) => s.performers ?? []))]}
                                     onClose={() => setPerfOpen(false)} onChanged={reloadBoard} />}
      {contOpen && <ContinuitySheet dir={project.dir} onClose={() => setContOpen(false)} onSelectShot={(id) => setSel({ kind: "shot", id })} />}
      {scriptOpen && <ScriptSheet project={project} onClose={() => setScriptOpen(false)} onDone={() => { setScriptOpen(false); onReload(); }} />}
      {cutoutsOpen && isFilm && <CutoutStudio dir={filmDirOfRender(project.dir)} onClose={() => setCutoutsOpen(false)} />}
      {libraryOpen && <LibrarySheet filmDir={isRenderDir(project.dir) ? filmDirOfRender(project.dir) : undefined} dir={project.dir} scenes={scenes.map((s) => ({ number: s.number, heading: s.heading }))}
                                    onClose={() => setLibraryOpen(false)} onChanged={reloadBoard} autoMake={openMake} />}

      {commanding && <DirectorCommand dir={project.dir} selected={sel?.kind === "shot" ? sel.id : null} playhead={time}
                                      onJobs={mergeJobs} onChanged={() => { reloadBoard(); refreshPendingKf(); onReload(); }}
                                      onClose={() => setCommanding(false)} onSettings={onSettings}
                                      onApplied={(r) => { setCommanding(false); setCmdResult(r); if (r.changed.length) onReload(); }} />}
      {cmdResult && <CommandToast result={cmdResult} onDismiss={() => setCmdResult(null)}
                                  onSelect={(id) => { setSel({ kind: "shot", id }); const sh = shots.find((x) => x.id === id); if (sh) seek(sh.start); }}
                                  onUndo={async () => { try { await api.undoCommand(project.dir, cmdResult.id!); setCmdResult(null); onReload(); } catch (e) { setError(errorText(e)); } }} />}
      {fidelityShot && <FidelitySheet dir={project.dir} shot={fidelityShot} onClose={() => setFidelityShot(null)} onChanged={() => { reloadBoard(); onReload(); window.dispatchEvent(new Event("pf-media-changed")); }} />}
      {upscaling && <UpscaleSheet dir={project.dir} req={upscaling} onClose={() => setUpscaling(null)} onChanged={() => { reloadBoard(); onReload(); window.dispatchEvent(new Event("pf-media-changed")); }} />}
      {lightOpen && <LightingSheet dir={project.dir} onClose={() => setLightOpen(false)} onChanged={mediaChanged}
                                   onSelect={(id) => { setSel({ kind: "shot", id }); const sh = shots.find((x) => x.id === id); if (sh) seek(sh.start); }} />}
      {queueOpen && <RenderQueueSheet dir={project.dir} jobs={jobs} shots={shots} onJob={(j) => mergeJobs([j])} onClose={() => setQueueOpen(false)} onReview={() => setReviewing(true)}
                                      onShow={(id) => { setSel({ kind: "shot", id }); const sh = shots.find((x) => x.id === id); if (sh) seek(sh.start); }} />}
      {batch && !reviewing && !queueOpen && <div className="toast glass batch-toast" role="status">
        <div className="t">{batch.failed ? "Renders finished, with problems" : "Renders finished"}</div>
        <div className="s">{batch.text}{batch.failed ? " The failed ones are listed in the queue with the reason." : " Each take is being checked; Review shows what needs a second look."}</div>
        <div className="cmd-changed"><button className="btn small primary" onClick={() => { setBatch(null); setReviewing(true); }}>Open Review</button>
          <button className="btn small ghost" onClick={() => { setBatch(null); setQueueOpen(true); }}>See the queue</button>
          <button className="btn small ghost" onClick={() => setBatch(null)}>Dismiss</button></div>
      </div>}
      {reviewing && <ReviewSheet dir={project.dir} shots={shots} jobs={jobs.filter((j) => j.plan === planName)} inUse={Object.fromEntries((board?.shots ?? []).map((b) => [b.id, b.approved]))} keys={keys} onJobs={mergeJobs} onQueue={() => setQueueOpen(true)}
                                 onChanged={() => { reloadBoard(); mediaChanged(); }}
                                 onOpen={(id) => { setReviewing(false); setViewing(id); }}
                                 onSelect={(id) => { setSel({ kind: "shot", id }); const sh = shots.find((x) => x.id === id); if (sh) seek(sh.start); }}
                                 onClose={() => setReviewing(false)} />}
      {lookOpen && <LookPicker value={look} director={director} onCancel={() => setLookOpen(false)} onSave={saveLook} />}
      {shotLookFor && ownLooks && (() => {
        const sh = shots.find((x) => x.id === shotLookFor);
        const inherited = effectiveLook(ownLooks ? { scenes: ownLooks.scenes } : null, shotLookFor, sh?.scene, look.style);
        return <LookPicker value={{ style: effectiveLook(ownLooks, shotLookFor, sh?.scene, look.style) }} director={false} onCancel={() => setShotLookFor(null)} onSave={(l) => pickShotLook(l.style)}
                           shot={{ id: shotLookFor, own: !!ownLooks.shots[shotLookFor], sameAs: sameAsLabel(ownLooks, look.style, inherited), onClear: () => pickShotLook("") }} />;
      })()}
      {exporting && <ExportSheet dir={project.dir} projectAspect={project.project.aspect_ratio} shots={shots.length}
                                 rendered={shots.filter((s) => latest.get(s.id)?.state === "ready").length}
                                 onClose={() => setExporting(false)} />}
      {dropped}
      {voiceOpen && isFilm && <VoiceoverSheet dir={filmDirOfRender(project.dir)} only={voiceShot} onClose={() => { setVoiceOpen(false); setVoiceShot(undefined); }} onChanged={() => onReload()} />}
      {selecting && board && <SelectReview dir={project.dir} shots={board.shots} sections={map?.sections ?? []}
                                           aspect={frame.aspect_ratio}
                                           initial={sel?.kind === "shot" ? [sel.id] : []} onClose={() => { setSelecting(false); reloadBoard(); refreshPendingKf(); }}
                                           onQueued={(js) => { mergeJobs(js); reloadBoard(); }} />}
      {confirmAll && <ConfirmRender count={toRender.length} seconds={0} provider={route?.video.provider ?? defaultProvider(keys)}
                                    model={route?.video.provider ? route.video.label! : AUTO_MODEL[defaultProvider(keys)]} onCancel={() => setConfirmAll(false)} onConfirm={renderAll}
                                    dir={project.dir} shots={toRender.map((s) => s.id)} modelId={route?.video.provider ? route.video.model! : AUTO_MODEL[defaultProvider(keys)]} />}
      {colourOpen && <ColourMatchSheet dir={project.dir} onClose={() => setColourOpen(false)} />}
      {(motionOpen || smartOpen || colorOpen) && polishLeft.length > 0 && <div className="pl-bar" role="status">Polishing: {polishLeft.length === 1 ? "one more step" : `${polishLeft.length} more steps`} after this one ({polishLeft.map((x) => ({ smart: "the cut", color: "colour", motion: "titles" })[x]).join(", then ")}). Close this to go on.{" "}
        <button type="button" className="link" onClick={() => setPolishLeft([])}>Stop here</button></div>}
      {motionOpen && <MotionGraphicsSheet dir={project.dir} time={time} onClose={closeThen(setMotionOpen)} onChanged={reloadBoard} />}
      {presetsOpen && <PresetsSheet dir={project.dir} onClose={() => setPresetsOpen(false)} onChanged={() => { reloadBoard(); onReload(); }} />}
      {smartOpen && <SmartEditorSheet dir={project.dir} onClose={closeThen(setSmartOpen)} onChanged={reloadBoard} />}
      {colorOpen && <ColorStudioSheet dir={project.dir} onClose={closeThen(setColorOpen)} onChanged={() => { reloadBoard(); window.dispatchEvent(new Event("pf-cut-changed")); }} />}
      {previewOpen && <PreviewSheet dir={project.dir} from={time} duration={map?.duration ?? 0} onClose={() => setPreviewOpen(false)} />}
      {frameOpen && <InsertFrameSheet dir={project.dir} shot={sel?.kind === "shot" ? sel.id : undefined} onClose={() => setFrameOpen(false)}
                                      onDone={(id) => { setFrameOpen(false); onReload(); if (id) setSel({ kind: "shot", id }); }} />}
      {cleanOpen && <CleanupSheet dir={project.dir} onClose={() => setCleanOpen(false)} onChanged={mediaChanged} />}
      {dlOpen && <DirectionLibrarySheet dir={project.dir} onClose={() => setDlOpen(false)} onApplied={onReload} />}
      {directorStyleOpen && <DirectorStyleSheet dir={project.dir} onClose={() => setDirectorStyleOpen(false)} onChanged={onReload} />}
      {supOpen && <SupervisorSheet dir={project.dir} onClose={() => setSupOpen(false)} onChanged={mediaChanged}
                                   onReview={(id) => { setSel({ kind: "shot", id }); setViewing(id); }} />}
      {paletteOpen && <Palette onClose={() => setPaletteOpen(false)}
        shots={shots.map((s) => ({ id: s.id, start: s.start }))}
        onShot={(id) => { const sh = shots.find((x) => x.id === id); setSel({ kind: "shot", id }); setInspector(true); if (sh) seek(sh.start); }}
        commands={([
          plan && { id: "director", label: "Ask the Director", hint: "Change the video in plain words", keys: "Ctrl+K", run: () => setCommanding(true) },
          plan && (keys.fal || keys.kie) && toRender.length > 0 && { id: "render", label: `Render ${toRender.length === shots.length ? "all" : toRender.length} shots`, hint: "Shows the price first", run: () => setConfirmAll(true) },
          plan && board && { id: "select", label: "Select & review", hint: "Choose shots, approve keyframes, pay for video where it is right", run: () => setSelecting(true) },
          plan && { id: "preview", label: "Preview the next seconds", hint: "A small quick version with layers and sound", run: () => { if (playing) toggle(); setPreviewOpen(true); } },
          plan && { id: "export", label: "Export the film", keys: "Ctrl+E", run: () => setExporting(true) },
          plan && { id: "layers", label: layersOpen ? "Close the Layers panel" : "Open the Layers panel", hint: "Text, pictures, shapes drawn over the film", keys: "Y", run: () => setLayersOpen((v) => !v) },
          plan && { id: "motion", label: "Motion graphics", hint: "Titles, lower thirds, callouts and cards, added at the playhead", run: () => setMotionOpen(true) },
          plan && { id: "presets", label: "Presets", hint: "Stack a style, acting, editing, colour and delivery in one go; make a vertical version", run: () => setPresetsOpen(true) },
          plan && isFilm && { id: "smart", label: "Smart Editor", hint: "Suggestions for the cut, explained and previewable", run: () => setSmartOpen(true) },
          plan && { id: "color", label: "Color Studio", hint: "Grade a shot, a scene or the film; LUTs", run: () => setColorOpen(true) },
          plan && { id: "colour", label: "Colour match", hint: "Even out brightness and colour between shots", run: () => setColourOpen(true) },
          plan && { id: "clean", label: "Clean up unused videos and pictures", run: () => setCleanOpen(true) },
          plan && { id: "frame", label: "Insert a frame", hint: "A card, picture, clip or generated shot", run: () => setFrameOpen(true) },
          plan && { id: "supervisor", label: "Supervisor", hint: "Checks of the whole film", run: () => setSupOpen(true) },
          plan && { id: "acting", label: "Acting", run: () => setPerfOpen(true) },
          plan && { id: "continuity", label: "Continuity", run: () => setContOpen(true) },
          plan && { id: "review", label: "Review", run: () => setReviewing(true) },
          plan && { id: "lighting", label: "Light the story", hint: "Read each shot's mood and plan the light to match (free)", run: () => setLightOpen(true) },
          { id: "library", label: "Reference library", hint: "Characters, places, props", run: () => setLibraryOpen(true) },
          { id: "directions", label: "Directions", run: () => setDlOpen(true) },
          { id: "director-style", label: "Director style", hint: "Optional camera, lens, light, pace and performance traits", run: () => setDirectorStyleOpen(true) },
          { id: "project", label: "Project page", hint: "Title, tempo, cast, look", run: () => { setSel(null); setInspector(true); } },
          { id: "play", label: playing ? "Pause" : "Play", keys: "Space", run: toggle },
          { id: "mute", label: muted ? "Unmute the player" : "Mute the player", keys: "M", run: () => setMuted((m) => !m) },
          { id: "focus", label: "Full screen: just the video", keys: "F", run: () => setFocusMode(true) },
          { id: "inspector", label: inspector ? "Hide the inspector" : "Show the inspector", keys: "Ctrl+I", run: () => setInspector((v) => !v) },
          { id: "timeline", label: timelineOpen ? "Hide the timeline" : "Show the timeline", keys: "Ctrl+J", run: () => setTimelineOpen((v) => !v) },
          ...(timelineOpen ? [{ id: "timeline-compact", label: tlCompact ? "Full-height timeline" : "Compact timeline", keys: "Ctrl+Shift+J", run: () => setTlCompact((v) => !v) }] : []),
          ...(hist?.undo_count ? [{ id: "undo-shot", label: `Undo: ${hist.undo[0].label}`, keys: "Ctrl+Shift+U", run: () => stepHist("undo") }] : []),
          ...(hist?.redo_count ? [{ id: "redo-shot", label: `Redo: ${hist.redo[0].label}`, keys: "Ctrl+Shift+Y", run: () => stepHist("redo") }] : []),
          { id: "check-hands", label: "Check hands in all keyframes…", hint: "Look at every keyframe's hands before any video is made", run: () => setKfTools(true) },
          { id: "one-model", label: "Redo keyframes on one picture model…", hint: "Keep one look across the cast", run: () => setKfTools(true) },
          { id: "next-flag", label: "Next shot that needs attention", keys: ".", run: () => { const t = stepAttention(attentionStarts(shots, needsLook), time, 1); if (t !== null) seek(t); else say("No later shot needs attention."); } },
          { id: "simple", label: "Simple mode", keys: "Ctrl+1", run: () => setDirector(false) },
          { id: "director-mode", label: "Director Mode", keys: "Ctrl+2", run: () => setDirector(true) },
          { id: "shortcuts", label: "Keyboard shortcuts", keys: "?", run: () => setKeysHelp(true) },
          { id: "settings", label: "Settings", keys: "Ctrl+,", run: onSettings },
          { id: "home", label: "Back to Home", run: onHome },
        ].filter(Boolean)) as Command[]} />}
      {keysHelp && <Sheet label="Keyboard shortcuts" className="keys-help" onDismiss={() => setKeysHelp(false)}>
        <h2>Keyboard shortcuts</h2>
        <div className="kh-cols">{GROUPS.map((g) => <section key={g}><h3>{g}</h3>
          <dl>{SHORTCUTS.filter((x) => x.group === g).map((x) => <div key={x.id}><dt><kbd>{x.keys}</kbd></dt><dd>{x.label}</dd></div>)}</dl></section>)}</div>
        <div className="sheet-actions"><button className="btn" onClick={() => setKeysHelp(false)}>Close</button></div></Sheet>}
      {toastMsg && <div className="toast glass mini" role="status">{toastMsg}</div>}
      {undoOffer && !toastMsg && <div className="toast glass mini undo-toast" role="status">{undoOffer} <button className="btn small" onClick={() => stepHist("undo")}>Undo</button> <span className="dim">Ctrl+Shift+U</span></div>}
      {night && !night.active && night.finished && night.export && (Date.now() / 1000 - night.finished < 86400) &&
        <div className="toast glass" role="status"><div className="t">Overnight render finished</div><div className="s">{night.export.split(/[\\/]/).pop()}</div>
          <div style={{ display: "flex", justifyContent: "flex-end", marginTop: 8 }}><button className="btn" onClick={() => setNight({ ...night, finished: null })}>OK</button></div></div>}
      {routeOpen && <RoutingSheet dir={project.dir} onClose={() => setRouteOpen(false)} />}
      {kfTools && <KeyframeTools dir={project.dir} onClose={() => setKfTools(false)} onChanged={() => { reloadBoard(); api.loadProject(project.dir).then((p) => { if (p.keyframes) setKeyframes(p.keyframes); }).catch(() => {}); window.dispatchEvent(new Event("pf-shot-changed")); }} />}
      {route && !route.online && <div className="offline-banner" role="status">Offline: cloud renders wait until you are back online. Your own media,
        moving stills, continuity, acting and export all keep working{route.brain.local ? ", and so does the local AI brain" : ""}.</div>}
      {songError && <div className="toast glass" role="alert" style={{ borderColor: "rgba(239,107,115,0.4)" }}>
        <div className="t" style={{ color: "var(--error)" }}>Can't play</div><div className="s">{songError}</div>
        <div style={{ display: "flex", justifyContent: "flex-end", marginTop: 10 }}><button className="btn" onClick={() => setSongError("")}>OK</button></div>
      </div>}
      {mediaNote && <div className="toast glass" role="status">
        <div className="t">Your media</div><div className="s">{mediaNote}</div>
        <div style={{ display: "flex", justifyContent: "flex-end", marginTop: 10 }}><button className="btn" onClick={() => setMediaNote("")}>OK</button></div>
      </div>}
      {error && (
        <div className="toast glass" role="alert" style={{ borderColor: "rgba(239,107,115,0.4)" }}>
          <div className="t" style={{ color: "var(--error)" }}>Direction stopped</div>
          <div className="s">{error}</div>
          <div style={{ display: "flex", justifyContent: "flex-end", marginTop: 10 }}>
            <button className="btn" onClick={() => setError("")}>OK</button></div>
        </div>
      )}
      {!focus && <FilmGuide project={{ ...project, jobs }} onOpen={() => chooseWorkspace("agent")} />}
    </div>
  );
}

const aspectNum = (r?: string) => {
  const m = r?.match(/^([\d.]+):([\d.]+)$/);
  return m ? String(Number(m[1]) / Number(m[2])) : String(16 / 9);
};


export function StateChip({ shot }: { shot: Shot }) {
  if (shot.flags?.length) return <span className="chip review"><I.Alert size={12} /> Needs review</span>;
  const s = shot.state ?? "planned";
  if (s === "ready") return <span className="chip ready"><I.Check size={12} /> Ready</span>;
  if (s === "locked") return <span className="chip"><I.Lock size={12} /> Locked</span>;
  if (s === "failed") return <span className="chip failed"><I.Alert size={12} /> Failed</span>;
  return <span className="chip planned"><I.Circle size={12} /> Planned</span>;
}

/** A rendered take, kept in step with the master audio (the song is the clock). */
export function Clip({ src, offset, playing }: { src: string; offset: number; playing: boolean }) {
  const v = useRef<HTMLVideoElement>(null);
  const want = useRef(offset);
  want.current = offset;
  useEffect(() => {
    const el = v.current;
    if (!el) return;
    if (needsSeek(el.currentTime, offset, playing)) el.currentTime = Math.max(0, offset);       // paused: every scrub step shows its own frame; playing: only when it has drifted
    if (playing && el.paused) el.play().catch(() => {});
    if (!playing && !el.paused) el.pause();
  }, [offset, playing, src]);
  // a new file loads at its start: once it knows its length, go to where the playhead is now (the position asked for while it was loading can be lost)
  return <video ref={v} className="clip" src={src} muted playsInline preload="auto"
                onLoadedMetadata={(e) => { const el = e.currentTarget; if (needsSeek(el.currentTime, want.current, true)) el.currentTime = Math.max(0, want.current); }} />;
}

function Storyboard({ shot, scene, job, hidden }: { shot: Shot; scene?: Scene; job?: Job; hidden?: boolean }) {
  const text = shot.visual_prompt ?? shot.beats.join(" ");
  return (
    <>
      <div className="frame-info">
        <span className="chip num">{shot.id}</span>
        {job ? <JobChip job={job} /> : <StateChip shot={shot} />}
        <span className="chip num">{(shot.end - shot.start).toFixed(1)}s</span>
      </div>
      {!hidden && <div className="board">
        {scene && <div className="scene-head">{scene.heading}</div>}
        <div className="desc">{text}</div>
        <div className="framing">{[shot.framing, shot.camera_movement ?? shot.camera_moves?.join(", ")].filter(Boolean).join(" · ")}</div>
      </div>}
    </>
  );
}

// ---------------- inspector ----------------

function Inspector({ sel, shots, scenes, map, plan, director, project, onClose, renderPanel, lookLabel, onLook }: {
  sel: Selection; shots: Shot[]; scenes: Scene[]; map: SongMap | null; plan: Plan | null; director: boolean;
  project: LoadedProject; onClose: () => void; renderPanel: (s: Shot) => ShotTabs; lookLabel: string; onLook: () => void;
}) {
  if (sel?.kind === "shot") {
    const s = shots.find((x) => x.id === sel.id);
    if (s) return <ShotInspector shot={s} scene={scenes.find((c) => c.number === s.scene)} director={director} onClose={onClose} project={project}
                                 tabs={renderPanel(s)} />;
  }
  if (sel?.kind === "section" && map) {
    const sec = map.sections[sel.index];
    const lines = map.lyrics.filter((l) => l.start != null && l.start >= sec.start && l.start < sec.end);
    return (
      <>
        <div className="inspector-head"><span className="t">{sec.group || sec.label}</span>
          <button className="icon-btn" onClick={onClose} aria-label="Close"><I.Close size={18} /></button></div>
        <div className="inspector-body">
          <div className="insp-section"><div className="kv">
            <span className="k">Time</span><span className="v num">{fmtTime(sec.start)} – {fmtTime(sec.end)}</span>
            <span className="k">Mood</span><span className="v">{sec.mood}</span>
            <span className="k">Energy</span><span className="v"><Meter v={sec.energy} /></span>
          </div></div>
          {lines.length > 0 && <div className="insp-section"><h4>{(project.project as { film?: boolean }).film ? "Dialogue" : "Lyrics"}</h4>{lines.map((l, i) => <p key={i} className="lyric-q">{l.text}</p>)}</div>}
        </div>
      </>
    );
  }
  return (
    <>
      <div className="inspector-head"><span className="t">Project</span></div>
      <div className="inspector-body">
        <div className="insp-section"><div className="kv">
          <span className="k">Title</span><span className="v">{project.project.title}</span>
          {map && <><span className="k">Length</span><span className="v num">{fmtTime(map.duration)}</span>
            <span className="k">{(project.project as { film?: boolean }).film ? "Scenes" : "Sections"}</span><span className="v num">{map.sections.length}</span>
            {map.lyric_match != null && <><span className="k">Lyrics heard</span><span className="v num">{Math.round(map.lyric_match * 100)}%</span></>}</>}
          <span className="k">Shots</span><span className="v num">{shots.length}</span>
          <span className="k">Renderer</span><span className="v">Auto</span>
        </div></div>
        <ProjectSettingsRow project={project} />
        <div className="insp-section look-row">
          <h4>Look</h4>
          <div className="file-row"><span className="name">{lookLabel}</span><button className="btn ghost small" onClick={onLook}>Change</button></div>
        </div>
        {plan?.meta?.LOGLINE && <div className="insp-section"><h4>Story</h4><p className="prose">{plan.meta.LOGLINE}</p></div>}
        {plan?.meta?.["VISUAL STYLE"] && <div className="insp-section"><h4>Look</h4><p className="prose">{plan.meta["VISUAL STYLE"]}</p></div>}
        {plan?.characters?.length ? <div className="insp-section"><h4>Cast</h4>
          {plan.characters.map((c) => <p key={c.name} className="prose"><b style={{ color: "var(--frost)" }}>{c.name}</b> — {c.archetype}</p>)}</div> : null}
        {director && scenes.some((s) => s.director_note) && <div className="insp-section"><h4>Director notes</h4>
          {scenes.filter((s) => s.director_note).map((s) => <p key={s.number} className="prose" style={{ marginBottom: 8 }}>
            <b style={{ color: "var(--frost)" }}>Scene {s.number}.</b> {s.director_note}</p>)}</div>}
      </div>
    </>
  );
}

type Tab = "shot" | "keyframe" | "frames" | "video" | "media";
type Badge = "" | "ok" | "busy" | "bad";
export type ShotTabs = {
  styleChanged: boolean;                                   // a take of this shot was made in another look than the one it has now
  look: { name: string; own: boolean; onOpen: () => void };  // the look the shot is played in, for the chip in its header
  badges: { keyframe: Badge; frames: Badge; video: Badge; media: Badge };
  shot: React.ReactNode; media: React.ReactNode;
  keyframe: (go: (t: Tab) => void) => React.ReactNode; frames: (go: (t: Tab) => void) => React.ReactNode; video: (go: (t: Tab) => void) => React.ReactNode;
};
const TABS: { id: Tab; label: string; icon: React.ReactNode }[] = [
  { id: "shot", label: "Shot", icon: <I.Camera size={16} /> },
  { id: "keyframe", label: "Keyframe", icon: <I.ImageIcon size={16} /> },
  { id: "frames", label: "Compose", icon: <I.Wand size={16} /> },
  { id: "video", label: "Video", icon: <I.Clapper size={16} /> },
  { id: "media", label: "Media", icon: <I.Upload size={16} /> },
];
const ADVANCED: Tab[] = ["frames", "media"];
const TAB_KEY = "pf-inspector-tab";
const storedTab = (): Tab => { try { const t = localStorage.getItem(TAB_KEY); return TABS.some((x) => x.id === t) ? (t as Tab) : "keyframe"; } catch { return "keyframe"; } };

export function ShotInspector({ shot: s, scene, director, onClose, tabs, project }: {
  shot: Shot; scene?: Scene; director: boolean; onClose: () => void; tabs: ShotTabs; project: LoadedProject;
}) {
  const [tab, setTabState] = useState<Tab>(storedTab);
  const [dockEl, setDockEl] = useState<HTMLElement | null>(null);
  const [adv, setAdv] = useState(() => { try { return localStorage.getItem("pf-inspector-adv") === "1"; } catch { return false; } });          // Compose and Media (prompt, references, start and end frames, your own media) are Advanced
  const toggleAdv = () => setAdv((v) => { try { localStorage.setItem("pf-inspector-adv", v ? "0" : "1"); } catch { /* a convenience only */ } return !v; });
  const setTab = (t: Tab) => { setTabState(t); try { localStorage.setItem(TAB_KEY, t); } catch { /* remembering the tab is a convenience only */ } };
  useEffect(() => {   // the Golden Path strip can open a tab for you
    const h = (e: Event) => { const t = (e as CustomEvent).detail as Tab; if (TABS.some((x) => x.id === t)) setTab(t); };
    window.addEventListener("pf-open-tab", h);
    return () => window.removeEventListener("pf-open-tab", h);
  }, []);   // eslint-disable-line react-hooks/exhaustive-deps
  const row = (k: string, v?: string | number | null) => (v === undefined || v === null || v === "" ? null :
    <><span className="k">{k}</span><span className="v">{v}</span></>);
  return (
    <DockCtx.Provider value={{ el: dockEl, tab }}>
      <div className="inspector-head"><div className="insp-title"><span className="t num">Shot {s.id}</span>
        <button className={`chip look-chip ${tabs.look.own ? "gold" : ""}`} onClick={tabs.look.onOpen} title="Choose a look for this shot" aria-label={`Look: ${tabs.look.name}. Choose a look for this shot`}><I.Eye size={12} />{tabs.look.name}</button></div>
        <button className="icon-btn" onClick={onClose} aria-label="Close"><I.Close size={18} /></button></div>
      <div className="insp-tabrow">
      <div className="insp-tabs" role="tablist" aria-label="Shot sections">
        {TABS.filter((t) => adv || !ADVANCED.includes(t.id) || t.id === tab).map((t) => {
          const b = t.id === "shot" ? "" : tabs.badges[t.id as "keyframe" | "frames" | "video" | "media"];
          return (
            <button key={t.id} role="tab" data-tab={t.id} aria-selected={tab === t.id} className={`insp-tab ${tab === t.id ? "on" : ""}`} onClick={() => setTab(t.id)}>
              {t.icon}<span>{t.label}</span>{b ? <i className={`tab-dot ${b}`} title={b === "ok" ? "Done" : b === "busy" ? "Working" : "Needs a look"} /> : null}
            </button>);
        })}
      </div>
      <button className="insp-adv" aria-expanded={adv} onClick={toggleAdv} title="Prompt, references, start and end frames, and your own media. Most shots never need them.">{adv ? "Fewer" : "Advanced"}</button>
      </div>
      <div className="inspector-body">
        <div hidden={tab !== "shot"}>
          <div className="insp-section" style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
            <StateChip shot={s} /><span className="chip">Renderer: Auto</span>
          </div>
          {tabs.styleChanged && <div className="flag"><I.Alert size={14} /><span>The video's look changed after this shot was made. Nothing is re-rendered for you: <button className="link" onClick={() => setTab("video")}>make a new take</button> (the price is shown first) or leave it.</span></div>}
          {s.flags?.map((f) => <div key={f} className="flag"><I.Alert size={14} /> {f}</div>)}
          <div className="insp-section"><div className="kv">
            {row("Time", `${fmtTime(s.start)} → ${fmtTime(s.end)}`)}
            {row("Duration", `${(s.end - s.start).toFixed(2)} s`)}
            {row("Section", s.section)}
            {row("Performers", s.performers.join(", ") || "—")}
            {row("Emotion", s.emotion)}
            {s.performance_intensity != null && <><span className="k">Intensity</span><span className="v"><Meter v={s.performance_intensity} /></span></>}
          </div></div>
          {s.purpose && <div className="insp-section"><h4>Purpose</h4><p className="prose">{s.purpose}</p></div>}
          <div className="insp-section"><h4>{s.beats.length > 1 ? `Story beats (${s.beats.length})` : "Action"}</h4>
            {s.beats.length > 1 ? <ol className="beats">{s.beats.map((b, i) => <li key={i}>{b}</li>)}</ol> : <p className="prose">{s.beats[0]}</p>}</div>
          {s.lyrics?.length ? <div className="insp-section"><h4>{project?.project && (project.project as { film?: boolean }).film ? "Dialogue in this shot" : "Lyrics under this shot"}</h4>{s.lyrics.map((l, i) => <p key={i} className="lyric-q">{l}</p>)}</div> : null}
          {(project.project as { film?: boolean }).film && <VoicePointer dir={filmDirOfRender(project.dir)} shotId={s.id} />}
          {tabs.shot}
          {(s.performance || s.expression || s.movement) && <div className="insp-section"><h4>Performance</h4><div className="kv">
            {row("Acting", s.performance)}{row("Expression", s.expression)}{row("Movement", s.movement)}</div></div>}
          {director && <>
            {(s.environment || s.wardrobe || s.continuity) && <div className="insp-section"><h4>Set & continuity</h4><div className="kv">
              {row("Set", s.environment)}{row("Wardrobe", s.wardrobe)}{row("Continuity", s.continuity)}{row("Sync", s.sync_event)}</div></div>}
            {s.visual_prompt && <div className="insp-section"><h4>Visual description</h4><p className="prose">{s.visual_prompt}</p></div>}
            {s.dropped_beats?.length ? <div className="insp-section"><h4>Dropped beats</h4><ul className="beats">{s.dropped_beats.map((b, i) => <li key={i}>{b}</li>)}</ul></div> : null}
            <div className="insp-section"><h4>Script source</h4><p className="prose num">{s.source_shots.join(", ")}</p></div>
            {scene && <div className="insp-section"><h4>Scene notes</h4><div className="kv">
              {Object.entries(scene.notes).map(([k, v]) => <Fragment key={k}><span className="k">{k.split("/")[0].toLowerCase().replace(/^\w/, (c) => c.toUpperCase())}</span><span className="v">{v}</span></Fragment>)}</div></div>}
          </>}
          {!director && <p className="prose" style={{ fontSize: 12.5, color: "var(--smoke)" }}>Switch to Director Mode to see the set, wardrobe, continuity and every scene note.</p>}
        </div>
        <div hidden={tab !== "keyframe"}>{tabs.keyframe(setTab)}</div>
        <div hidden={tab !== "frames"}>{tabs.frames(setTab)}</div>
        <div hidden={tab !== "video"}>{tabs.video(setTab)}</div>
        <div hidden={tab !== "media"}>{tabs.media}</div>
      </div>
      <div className="insp-dock" ref={setDockEl} />
    </DockCtx.Provider>
  );
}

const Meter = ({ v }: { v: number }) => <span className="meter" aria-label={`${v} of 10`}>{Array.from({ length: 10 }, (_, i) => <i key={i} className={i < v ? "on" : ""} />)}</span>;

// ---------------- timeline ----------------

/**
 * Whether the top bar has run out of room, measured rather than guessed: the bar's buttons change with the project (an Overnight chip, "Approve 1 keyframes", Director Mode's extras), so a fixed
 * window width cannot say. When the buttons overflow, fold the secondary ones into a menu; unfold again once the bar is wide enough for what it needed. `deps` are what can change the buttons.
 */
function useBarFold(ref: React.RefObject<HTMLElement | null>, deps: unknown[]): boolean {
  const [fold, setFold] = useState(false);
  const need = useRef(0);                                              // how wide the bar needed to be when it was last unfolded and full
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const check = () => {
      if (el.clientWidth < 100) return;                                  // hidden or not laid out yet: nothing to measure
      if (!fold && el.scrollWidth > el.clientWidth + 1) { need.current = el.scrollWidth; setFold(true); }
      else if (fold && el.clientWidth >= need.current + 8) setFold(false);
      // what the bar still spills over the inspector's header (its last icons): the header leaves exactly that much room, so a title is never covered
      (el.closest(".studio") as HTMLElement | null)?.style.setProperty("--bar-over", `${Math.max(0, el.scrollWidth - el.clientWidth)}px`);
    };
    check();
    const ro = new ResizeObserver(check);
    ro.observe(el);
    window.addEventListener("resize", check);                          // also on the window's own resize: a hidden or throttled view may not report the bar's size
    return () => { ro.disconnect(); window.removeEventListener("resize", check); };
  }, [ref, fold, ...deps]);                                            // eslint-disable-line react-hooks/exhaustive-deps
  return fold;
}

/** True while the window is narrower than `px`: the Studio folds its secondary buttons into a menu then, instead of letting the top bar run under the inspector. */
function useNarrow(px: number): boolean {
  const q = `(max-width: ${px}px)`;
  const [n, setN] = useState(() => !!window.matchMedia?.(q).matches);
  useEffect(() => {
    const m = window.matchMedia?.(q);
    if (!m) return;
    const on = () => setN(m.matches);
    on();
    m.addEventListener("change", on);
    return () => m.removeEventListener("change", on);
  }, [q]);
  return n;
}

/** How tall a shot's picture is on the timeline at the least, and the height the timeline opens at: tall enough to see what each shot is. */
const CARD_MIN = 96;
const TL_MIN_SAVED = 300;                                   // an older, shorter saved height gave pictures too small to read, so it is not kept
const defaultTimelineHeight = () => Math.max(340, Math.min(480, Math.round(window.innerHeight * 0.42)));

function Timeline({ edit, onEdit, compact: compactProp, onCompact, map, time, sel, flagged, dir, board, boardOrigin, cut: cutState, onSuggest, onMotion, thumbs, want, layerSel, onLayerSelect, onBoardChanged, onSeek, onSelect, onOpen }: {
  edit: boolean; onEdit: (v: boolean) => void; compact: boolean; onCompact: () => void;
  map: SongMap | null; time: number; sel: Selection; flagged: number; dir: string; board: BoardShot[];
  boardOrigin: BoardShot[]; cut: CutState; onSuggest: () => void; onMotion: () => void;
  thumbs: Record<string, string | null>; want: (srcs: string[]) => void;
  layerSel: string | null; onLayerSelect: (id: string | null) => void; onBoardChanged: () => void;
  onSeek: (t: number) => void; onSelect: (s: Selection) => void; onOpen: (id: string) => void;
}) {
  const compact = edit && compactProp;                                      // the Film strip has one calm size; Compact belongs to Edit
  const voiceFilm = isRenderDir(dir) ? filmDirOfRender(dir) : null;
  const { byShot: voiceByShot, st: voiceSt } = useVoiceStatus(voiceFilm);          // a film's recorded voices, shown on the shots
  const cueData = useCues(edit ? voiceFilm : null);                                 // the film's planned sound, shown under the voices in Edit mode
  const cutOn = edit && !compact && !!voiceFilm;                                    // the cut lane: the film's own cut, edited here (Edit mode of a film)
  const [freeLayers, setFreeLayers] = useState<{ start: number }[]>([]);                // layers sit on the film's clock, so the cut says when one now starts after its end
  useEffect(() => {
    if (!cutOn) return;
    const pull = () => api.overlays<{ start: number }[]>(dir, "list").then((l) => setFreeLayers(Array.isArray(l) ? l.map((o) => ({ start: o.start })) : [])).catch(() => setFreeLayers([]));
    void pull();
    window.addEventListener("pf-overlays-changed", pull);
    return () => window.removeEventListener("pf-overlays-changed", pull);
  }, [cutOn, dir]);
  const [laneN, setLaneN] = useState(0);
  const [voicesOpen, setVoicesOpenState] = useState(() => !!readLayout(dir).voices);          // the Voices band shows everyone (or the first three), remembered for this film
  const setVoicesOpen = (v: boolean) => { setVoicesOpenState(v); writeLayout(dir, { voices: v }); };
  const [addMenu, setAddMenu] = useState(false);
  const [addErr, setAddErr] = useState("");
  const scroll = useRef<HTMLDivElement>(null);
  const wave = useRef<HTMLCanvasElement>(null);
  const [width, setWidth] = useState(1200);
  const [left, setLeft] = useState(0);
  const dur = map?.duration ?? 0;
  // zoom: pixels per second; capped so the waveform canvas stays within browser limits
  const maxPps = Math.max(12, Math.floor(30000 / Math.max(1, dur * (window.devicePixelRatio || 1))));
  const [pps, setPpsState] = useState(() => readLayout(dir).pps ?? 24);                 // zoom and height are remembered for this project
  const setPps = (n: number) => { const v = Math.max(PPS_MIN, Math.min(PPS_MAX, n)); setPpsState(v); writeLayout(dir, { pps: v }); };
  const zoom = (f: number, anchorPx?: number) => {
    const s = scroll.current;
    const next = Math.max(6, Math.min(maxPps, Math.round(pps * f)));
    if (next === pps) return;
    const ax = anchorPx ?? (s ? s.clientWidth / 2 : 0);
    const t = ((s?.scrollLeft ?? 0) + ax) / pps;
    setPps(next);
    requestAnimationFrame(() => { if (s) s.scrollLeft = Math.max(0, t * next - ax); });
  };
  const [sized, setSized] = useState(() => !!readLayout(dir).sized);                 // a height the person chose is kept, however short
  const [fullHeight, setHeight] = useState(() => { const l = readLayout(dir); return l.height && (l.sized || l.height >= TL_MIN_SAVED) ? l.height : defaultTimelineHeight(); });
  const height = compact ? COMPACT_HEIGHT : fullHeight;
  // Ctrl + wheel zooms around the pointer (native listener: React's wheel handler can't stop page zoom); plain wheel scrolls sideways
  const zoomRef = useRef(zoom);
  zoomRef.current = zoom;
  useEffect(() => {
    const el = scroll.current;
    if (!el) return;
    const on = (e: WheelEvent) => {
      if (e.ctrlKey) { e.preventDefault(); zoomRef.current(e.deltaY < 0 ? 1.25 : 0.8, e.clientX - el.getBoundingClientRect().left); }
      else if (Math.abs(e.deltaY) > Math.abs(e.deltaX)) {
        const vs = (e.target as Element | null)?.closest?.(".vl-scroll") as HTMLElement | null;
        if (vs && vs.scrollHeight > vs.clientHeight + 1 && ((e.deltaY > 0 && vs.scrollTop + vs.clientHeight < vs.scrollHeight - 1) || (e.deltaY < 0 && vs.scrollTop > 0))) return;          // over the Voices band, with more people below (or above) than fit: the wheel scrolls them
        e.preventDefault(); el.scrollLeft += e.deltaY;
      }
    };
    el.addEventListener("wheel", on, { passive: false });
    return () => el.removeEventListener("wheel", on);
  }, [map]);
  const heightRef = useRef(fullHeight);
  heightRef.current = fullHeight;
  const drag = (e: React.PointerEvent) => {
    const y0 = e.clientY, h0 = height;
    if (compact) onCompact();                                                 // dragging the edge leaves compact mode
    setSized(true);
    const move = (ev: PointerEvent) => setHeight(Math.max(HEIGHT_MIN, Math.min(window.innerHeight * 0.6, h0 + (y0 - ev.clientY))));
    const up = () => {
      window.removeEventListener("pointermove", move); window.removeEventListener("pointerup", up);
      writeLayout(dir, { height: Math.max(HEIGHT_MIN, Math.min(HEIGHT_MAX, Math.round(heightRef.current))), sized: true });
    };
    window.addEventListener("pointermove", move); window.addEventListener("pointerup", up);
  };
  const inner = Math.max(width, dur * pps, (cutState.cut?.sequence.length_s ?? 0) * pps);                    // a cut made longer than the soundtrack can still be reached
  const x = (t: number) => t * pps;
  const addLayer = async (data: Record<string, unknown>) => {
    setAddMenu(false); setAddErr("");
    const at = Math.max(0, Math.floor(time * 10) / 10);
    try {
      const r = await api.overlays(dir, "add", { start: at, end: Math.min(dur || at + 4, at + 4), ...data });
      window.dispatchEvent(new Event("pf-overlays-changed"));
      onLayerSelect(r[r.length - 1]?.id ?? null);
    } catch (e) { setAddErr(errorText(e)); }
  };
  const addPicture = async () => {
    setAddMenu(false);
    const f = await openDialog({ filters: [{ name: "Picture or text sign", extensions: ["png", "jpg", "jpeg", "webp", "svg"] }] });
    if (typeof f === "string") await addLayer({ image: f, y: 0.5, width: 0.3, anim: "zoom_in" });
  };
  const room = Math.round(window.innerHeight * 0.45);                          // the timeline never takes more than this, so the player keeps its room on a small window
  useEffect(() => { if (!compact && !sized && laneN > 0 && fullHeight < Math.min(400, room)) setHeight(Math.min(400, room)); }, [laneN > 0]);   // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    const ro = new ResizeObserver(([e]) => setWidth(e.contentRect.width));
    if (scroll.current) ro.observe(scroll.current);
    return () => ro.disconnect();
  }, []);

  useEffect(() => {
    const c = wave.current;
    if (!c || !map) return;
    const dpr = window.devicePixelRatio || 1;
    const W = dur * pps, H = 54;
    c.width = W * dpr; c.height = H * dpr; c.style.width = `${W}px`; c.style.height = `${H}px`;
    const g = c.getContext("2d")!;
    g.scale(dpr, dpr);
    const p = map.peaks ?? [];
    const bw = W / Math.max(1, p.length);
    g.fillStyle = "rgba(232,180,92,0.5)";
    p.forEach((v, i) => { const h = Math.max(0.5, v * (H / 2 - 2)); g.fillRect(i * bw, H / 2 - h, Math.max(1, bw - 0.3), h * 2); });
    g.fillStyle = "rgba(244,247,250,0.10)";
    for (const d of map.downbeats) g.fillRect(x(d), 0, 1, H);
    g.fillStyle = "#E8B45C";
    for (const a of map.accents) g.fillRect(x(a) - 1, H - 5, 3, 3);
  }, [map, dur, pps]);

  // keep the playhead in view while playing
  useEffect(() => {
    const s = scroll.current;
    if (!s) return;
    const px = x(time);
    if (px < s.scrollLeft + 40 || px > s.scrollLeft + s.clientWidth - 80) s.scrollLeft = Math.max(0, px - s.clientWidth * 0.3);
  }, [time]);

  const clickSeek = (e: React.MouseEvent) => {
    const r = (e.currentTarget as HTMLElement).getBoundingClientRect();
    onSeek((e.clientX - r.left) / pps);
  };

  if (!map) return <section className="timeline"><div className="tl-head">No timeline yet.</div></section>;
  const voiceN = !edit || compact || !voiceFilm ? 0 : speakers(voiceSt).length;                        // one lane for each person who speaks (not in the compact timeline)
  const cueKinds = !edit || compact || !voiceFilm ? [] : cueLaneKinds(cueData.list);                   // the planned sound: one lane each for effects, ambience and music, only the ones with something in them
  const cueH = cueKinds.length ? CHEAD_H + cueKinds.length * CLANE_H + 10 : 0;
  const voiceRows = voiceN ? Math.min(voiceN, voicesOpen ? VOICE_ROWS_MAX : VOICE_ROWS) : 0;
  const voiceH = voiceN ? VHEAD_H + voiceRows * VLANE_H + 10 : 0;
  const cutH = cutOn ? CUT_H + 8 : 0;
  const reserve = edit ? cutH + 28 + Math.min(Math.max(1, laneN), 3) * LANE_H + 18 + (voiceN ? VHEAD_H + voiceRows * VLANE_H + 10 : 0) + cueH : 28 + 18;      // the transition row and up to three layer lanes fit without scrolling; more lanes scroll
  const shown = !edit ? 34 + 136 + reserve + STRIP_CARD_H : Math.max(Math.min(height, Math.round(window.innerHeight * 0.6)), compact || sized ? 0 : 34 + 136 + reserve + CARD_MIN);      // unless the person chose a height, never so short that the shot pictures are slivers
  const cardH = !edit ? STRIP_CARD_H : Math.max(compact || sized ? 40 : CARD_MIN, shown - 34 - 136 - reserve);
  // top to bottom: sections, waveform, lyrics, the layer lanes (overlay tracks sit above the video, as in an editor), the shots, the transition handles
  const laneTop = 118 + cutH, lanesH = edit ? Math.max(1, laneN) * LANE_H + 10 : 6, shotsTop = laneTop + lanesH, transTop = shotsTop + cardH + 6, voiceTop = transTop + 28;
  return (
    <section className="timeline" aria-label="Timeline" style={{ height: shown, ["--card-h" as string]: `${cardH}px` }}>
      {edit && <div className="tl-resize" onPointerDown={drag} title="Drag to resize" />}
      <div className="tl-head">
        <span>{map.analyzer === "film" ? "Timeline" : "Song Map"}</span>
        <div className="legend">
          <span><i className="dot" style={{ background: "var(--gold)" }} /> {map.analyzer === "film" ? "Soundtrack" : "Music"}</span>
          <span><i className="dot" style={{ background: "var(--signal)" }} /> Playhead</span>
        </div>
        <div style={{ flex: 1 }} />
        {flagged > 0 && <span style={{ color: "var(--warning)", display: "flex", gap: 6, alignItems: "center" }}><I.Alert size={14} /> {flagged} shots may need attention</span>}
        {edit && <div className="tl-add">
          <button className="btn small" onClick={() => setAddMenu((v) => !v)} aria-expanded={addMenu} aria-haspopup="menu" title="Add text, a picture, a shape or an icon at the playhead">+ Layer</button>
          {addMenu && <div className="tl-add-menu" role="menu">
            <button role="menuitem" onClick={() => { setAddMenu(false); onMotion(); }}>Motion graphics…</button>
            <button role="menuitem" onClick={() => addLayer({ kind: "text", text: "Your text", y: 0.5, anim: "rise" })}>Text</button>
            <button role="menuitem" onClick={addPicture}>Picture…</button>
            <button role="menuitem" onClick={() => addLayer({ kind: "icon", icon: "star", x: 0.5, y: 0.5, width: 0.12, color: "#ffd166", anim: "zoom_in" })}>Icon</button>
            <button role="menuitem" onClick={() => addLayer({ kind: "shape", shape: "rounded", x: 0.5, y: 0.5, width: 0.25, height: 0.25, color: "#ffd166", anim: "fade" })}>Shape</button>
            <button role="menuitem" onClick={() => addLayer({ kind: "fill", color: "#000000", opacity: 0.4, anim: "fade" })}>Colour tint</button>
          </div>}
          {addErr && <span role="alert" style={{ color: "var(--warning)", marginLeft: 8 }}>{addErr}</span>}
        </div>}
        <div className="zoom" role="group" aria-label="Zoom">
          <button className="icon-btn" onClick={() => zoom(1 / 1.5)} aria-label="Zoom out" title="Zoom out (Ctrl + scroll)">−</button>
          <button className="btn ghost small" onClick={() => { const s = scroll.current; if (s && dur) setPps(Math.floor(s.clientWidth / dur)); }}>Fit</button>
          <button className="icon-btn" onClick={() => zoom(1.5)} aria-label="Zoom in" title="Zoom in (Ctrl + scroll)">+</button>
          {edit && <button className={`btn ghost small ${compact ? "on" : ""}`} onClick={onCompact} aria-pressed={compact} title="Compact timeline: just the shots (Ctrl+Shift+J)">Compact</button>}
        </div>
        <div className="tl-mode" role="group" aria-label="Timeline mode">
          <button className={!edit ? "on" : ""} aria-pressed={!edit} onClick={() => onEdit(false)} title="A calm, fixed view: every shot at one size. Nothing to drag, nothing to squash.">Film strip</button>
          <button className={edit ? "on" : ""} aria-pressed={edit} onClick={() => onEdit(true)} title="The full timeline: drag its height, add layers, see each person's voice lane">Edit</button>
        </div>
      </div>
      <div className="tl-scroll" ref={scroll} onScroll={(e) => setLeft((e.currentTarget as HTMLElement).scrollLeft)}>
        <div className="tl-inner" style={{ width: inner, height: Math.max(transTop + 28 + voiceH + cueH, 0) }} onClick={clickSeek}>
          <div className="tl-sections">
            {map.sections.map((s, i) => (
              <div key={i} className="tl-section" style={{ left: x(s.start), width: x(s.end - s.start) - 2 }}
                   onClick={(e) => { e.stopPropagation(); onSelect({ kind: "section", index: i }); onSeek(s.start); }}>
                {(s.group && s.group.length > 2 ? s.group : s.label).toUpperCase()}</div>
            ))}
          </div>
          <canvas className="tl-wave" ref={wave} />
          {cutOn && <CutLane s={cutState} pps={pps} top={118} time={time} width={width} onSeek={onSeek} free={freeLayers} onSuggest={onSuggest} />}
          <div className="tl-lyrics">
            {map.lyrics.filter((l) => l.start != null && x(l.end ?? l.start!) >= left - 200 && x(l.start!) <= left + width + 200).map((l, i) => (
              <div key={i} className="tl-lyric" title={l.text} style={{ left: x(l.start!), width: Math.max(18, x((l.end ?? l.start!) - l.start!)) }}>{l.text}</div>
            ))}
          </div>
          <div className="tl-shots" style={{ top: shotsTop }}>
            <StoryCards dir={dir} shots={board} pps={pps} view={[left, left + width]} selected={sel?.kind === "shot" ? sel.id : null} voices={voiceByShot} onVoice={(id) => window.dispatchEvent(new CustomEvent("fc-open-voice", { detail: id }))}
                        thumbs={thumbs} want={want} onOpen={onOpen} onSelect={(id) => onSelect({ kind: "shot", id })} />
          </div>
          <TransitionHandles dir={dir} shots={board} pps={pps} top={transTop} onChanged={onBoardChanged} />
          {voiceN > 0 && voiceFilm && <VoiceLanes dir={voiceFilm} st={voiceSt} shots={boardOrigin} pps={pps} top={voiceTop} view={[left, left + width]} rows={voiceRows} open={voicesOpen} onToggle={() => setVoicesOpen(!voicesOpen)} />}
          {cueKinds.length > 0 && voiceFilm && cueData.list && <CueLanes dir={voiceFilm} list={cueData.list} mix={cueData.mix} shots={boardOrigin} pps={pps} top={voiceTop + voiceH} view={[left, left + width]} onChanged={cueData.reload} />}
          {edit && <LayerLanes dir={dir} pps={pps} duration={dur} selected={layerSel} onSelect={onLayerSelect} top={laneTop} onCount={setLaneN} time={time} onSeek={onSeek}
                      snap={snapPoints({ downbeats: map.downbeats, lyrics: map.lyrics, shots: board, playhead: time })} />}
          <div className="playhead" style={{ left: x(time) }} />
        </div>
      </div>
    </section>
  );
}

/** Aspect, quality and lip-sync for every render in the project. Changes apply to new takes. */
function ProjectSettingsRow({ project }: { project: LoadedProject }) {
  const [s, setS] = useState({
    aspect_ratio: project.project.aspect_ratio ?? "16:9", quality: project.project.quality ?? "standard",
    lip_sync: project.project.lip_sync ?? "auto",
    vocalist: (project.project as { vocalist?: string }).vocalist ?? "onscreen",
  });
  const [err, setErr] = useState("");
  const change = async (k: keyof typeof s, v: string) => {
    const next = { ...s, [k]: v };
    setS(next); setErr("");
    try { if (k === "aspect_ratio" || k === "quality") { await saveFrame(project.dir, k, v); }       // a film keeps its shape in the film too, or the next sync would put the old one back
       else if (k === "vocalist") await api.setProjectSettings(project.dir, { vocalist: v as "onscreen" | "offscreen" }); else await api.setProjectSettings(project.dir, { lip_sync: v as "auto" | "closeups" | "off" }); } catch (e) { setErr(errorText(e)); }
  };
  return (
    <div className="insp-section">
      <h4>Frame & quality</h4>
      <div className="kv settings-kv">
        <span className="k">Aspect</span>
        <select className="text-input" value={s.aspect_ratio} onChange={(e) => change("aspect_ratio", e.target.value)} aria-label="Aspect ratio">
          {ASPECTS.map(([v, l]) => <option key={v} value={v}>{v} · {l}</option>)}
        </select>
        <span className="k">Quality</span>
        <select className="text-input" value={s.quality} onChange={(e) => change("quality", e.target.value)} aria-label="Quality">
          {QUALITY.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
        </select>
        <span className="k">Lip-sync</span>
        <select className="text-input" value={s.lip_sync} onChange={(e) => change("lip_sync", e.target.value)} aria-label="Lip-sync">
          <option value="auto">{(project.project as { film?: boolean }).film ? "Auto · speaking shots follow the voice" : "Auto · singing shots follow the vocal"}</option>
          <option value="closeups">Close-ups get a dedicated lip-sync pass</option>
          <option value="off">Off</option>
        </select>
      </div>
      <p className="dim" style={{ marginTop: 6 }}>Applies to new takes. Each model uses its closest supported option.</p>
      {err && <div className="error-text">{err}</div>}
    </div>
  );
}

/** How far the film is (what the rail's ticks and dot are drawn from). Missing or failing quietly: the rail then shows no ticks. */
function useRailProgress(filmDir: string | null): FilmProgress | null {
  const [p, setP] = useState<FilmProgress | null>(null);
  useEffect(() => { if (filmDir) api.make<FilmProgress>("progress", filmDir).then(setP).catch(() => {}); }, [filmDir]);
  return p;
}
