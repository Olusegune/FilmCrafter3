import { useEffect, useMemo, useRef, useState } from "react";
import { Sheet } from "./Sheet";
import { Takes } from "./Takes";
import { api, AUTO_LIPSYNC_MODEL, AUTO_MODEL, errorText, type CatalogItem, type Estimate, type ChangesSince as ChangesInfo, type TrackStats, type Job, type ModelInput, type KeyStatus, type Manifest, type ManifestInput, type Shot } from "./api";
import { ExtendCard } from "./Extend";
import { useRouting } from "./Routing";
import { ModelPicker } from "./ModelPicker";
import * as I from "./icons";
import { needsAttention } from "./Review";
import { MediaInput, mediaKind } from "./Media";
import { Cta, DockBar, DockSlot, PanelHead, Pill, priceLabel, useEstimate } from "./Dock";
import { FormatRow } from "./FormatRow";
import { PromptBudget } from "./PromptBudget";
import { LipSyncNote, type Timing } from "./LipSyncNote";
import { GivenToModel } from "./GivenToModel";
import { ChangesSince } from "./ChangesSince";
import { TrackRecord } from "./TrackRecord";
import { saveFrame, sentShape } from "./frame";

const ERROR_LABEL: Record<string, string> = {
  auth: "Key rejected", credits: "Out of credits", invalid: "Setting not accepted", unavailable: "Model unavailable",
  rate_limit: "Provider busy", timeout: "Timed out", policy: "Content filter", service: "Provider error",
  download: "Download failed", missing_input: "Missing input",
};

export const PROVIDER_NAME: Record<string, string> = { fal: "fal.ai", kie: "Kie.ai", google: "Google", openai: "OpenAI", byteplus: "BytePlus", comfyui: "ComfyUI" };
export const ACTIVE_STATES = ["queued", "submitting", "submitted"];

/** Latest non-dismissed job for each shot of the current plan. */
export function latestJobs(jobs: Job[], plan: string): Map<string, Job> {
  const m = new Map<string, Job>();
  for (const j of jobs) {
    if (j.plan !== plan || j.state === "dismissed" || j.kind === "image") continue;
    const cur = m.get(j.shot_id);
    if (!cur || j.created >= cur.created) m.set(j.shot_id, j);
  }
  return m;
}

export function JobChip({ job }: { job?: Job }) {
  if (!job) return null;
  switch (job.state) {
    case "queued": return <span className="chip"><I.Circle size={12} /> Queued</span>;
    case "submitting":
    case "submitted": return <span className="chip gen"><span className="spin" /> Generating</span>;
    case "ready": return <span className="chip ready"><I.Check size={12} /> Ready</span>;
    case "uncertain": return <span className="chip review"><I.Alert size={12} /> Check needed</span>;
    case "failed": return <span className="chip failed"><I.Alert size={12} /> Failed</span>;
    default: return null;
  }
}

/** Pick the provider to use by default: whichever has a key, fal first. */
export const defaultProvider = (keys: KeyStatus) => (keys.fal ? "fal" : keys.kie ? "kie" : keys.google ? "google" : "fal");

// ---------------------------------------------------------------- inspector panel

export function RenderPanel({ dir, shot, jobs, director, keys, onQueued, onSettings, lookId, keyframeKey, frame = "16:9", quality = "standard", onBack, approvedTake = null, onTakeChosen }: {
  dir: string; shot: Shot; jobs: Job[]; director: boolean; keys: KeyStatus;
  onQueued: (jobs: Job[]) => void; onSettings: () => void; lookId: string; keyframeKey?: string | null; frame?: string; quality?: string; onBack?: () => void;
  approvedTake?: string | null; onTakeChosen?: () => void;
}) {
  const [provider, setProvider] = useState(defaultProvider(keys));
  const [model, setModel] = useState(AUTO_MODEL[defaultProvider(keys)]);
  const { route } = useRouting(dir);
  const routed = useRef(false);
  useEffect(() => {   // start from what the project's mode picks (once; the user can still change it)
    const p = route?.video;
    if (!routed.current && p?.provider) { routed.current = true; setProvider(p.provider); setModel(p.model!); }   // incl. ComfyUI (Hybrid / Local First)
  }, [route]);
  const [catalog, setCatalog] = useState<CatalogItem[]>([]);
  const [manifest, setManifest] = useState<Manifest | null>(null);
  const [auto, setAuto] = useState<Record<string, unknown>>({});
  const [pins, setPins] = useState<Record<string, unknown>>({});
  const [confirm, setConfirm] = useState(false);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [showRaw, setShowRaw] = useState(false);
  const [lipSync, setLipSync] = useState(false);
  const [audioFirst, setAudioFirst] = useState(false);
  const [kfBlocksAudio, setKfBlocksAudio] = useState(false);
  const [singSetting, setSingSetting] = useState<"auto" | "on" | "off">("auto");
  const [vocalHeard, setVocalHeard] = useState(0);
  const [lipMode, setLipMode] = useState<"first_frame" | "audio_first" | "auto">("first_frame");
  const [inputs, setInputs] = useState<ModelInput[]>([]);
  const [since, setSince] = useState<ChangesInfo | null>(null);
  const [track, setTrack] = useState<TrackStats | null>(null);
  const [sinceBusy, setSinceBusy] = useState(false);
  const [timing, setTiming] = useState<Timing | null>(null);
  const [timingBusy, setTimingBusy] = useState(false);
  const [modeKey, setModeKey] = useState(0);        // changes when the lip-sync mode does, so the preview is read again
  const [singing, setSinging] = useState<{ performer: string; lyrics: string[] } | null>(null);
  const [keyframeRef, setKeyframeRef] = useState<string | null>(null);
  const [lipFor, setLipFor] = useState<Job | null>(null);
  const [problems, setProblems] = useState<string[]>([]);
  const [sentRefs, setSentRefs] = useState<{ label: string; media: string }[]>([]);
  const [droppedRefs, setDroppedRefs] = useState<string[]>([]);
  const [blocks, setBlocks] = useState<{ priority: number; text: string; kept: boolean }[] | null>(null);   // the prompt, block by block (for the budget bar)
  // the provider you have selected, else the one that made the take, else whichever of fal / Kie has a key
  const lipProvider = (["fal", "kie"] as const).find((p) => p === provider && keys[p]) ?? (["fal", "kie"] as const).find((p) => p === lipFor?.provider && keys[p])
    ?? (keys.fal ? "fal" : "kie");
  const lipsync = async () => {
    const src = lipFor!;
    setLipFor(null); setError("");
    try { onQueued(await api.queueRender(dir, [shot.id], lipProvider, AUTO_LIPSYNC_MODEL[lipProvider], {}, [], "lipsync", src.id)); }
    catch (e) { setError(errorText(e)); }
  };

  const history = jobs.filter((j) => j.shot_id === shot.id && j.state !== "dismissed" && j.kind !== "image").sort((a, b) => b.created - a.created);
  const active = history.find((j) => ACTIVE_STATES.includes(j.state));
  const hasKey = provider === "comfyui" || keys[provider as keyof KeyStatus];
  const est = useEstimate(dir, [shot.id], provider, model, "video", [frame, quality]);

  useEffect(() => { setPins({}); setTiming(null); }, [shot.id]);
  // Settle edits before asking the engine for a fresh preview.
  const [settled, setSettled] = useState(pins);
  useEffect(() => { const t = setTimeout(() => setSettled(pins), 500); return () => clearTimeout(t); }, [pins]);
  useEffect(() => { if (director) api.renderCatalog(provider).then(setCatalog).catch(() => setCatalog([])); }, [director, provider]);

  // What FilmCrafter would send (Auto values) — free, uploads nothing.
  useEffect(() => {
    let live = true;
    setBusy("Reading model…"); setError("");
    api.renderPreview(dir, shot.id, provider, model, settled)
      .then((r) => { if (!live) return; setManifest(r.manifest); setAuto(r.payload); setLipSync(!!r.lip_sync); setAudioFirst(!!r.audio_first); setSingSetting(r.sing_setting ?? "auto"); setVocalHeard(r.vocal_heard ?? 0); setLipMode((r.lip_sync_mode as typeof lipMode) ?? "first_frame"); setKfBlocksAudio(!!r.keyframe_blocks_audio); setSinging(r.singing ?? null); setKeyframeRef((r as { keyframe?: string }).keyframe ?? null); setProblems(r.problems ?? []);
        setSentRefs(r.references ?? []); setInputs(r.inputs ?? []); setDroppedRefs(r.dropped_references ?? []); setBlocks(r.prompt_blocks ?? null); })
      .catch((e) => live && setError(errorText(e)))
      .finally(() => live && setBusy(""));
    return () => { live = false; };
  }, [dir, shot.id, provider, model, settled, lookId, keyframeKey, frame, quality, modeKey]);

  // How the models have done in this project so far (free: reads what was recorded, and checks the sound of sung takes on this computer)
  useEffect(() => { let live = true; api.track(dir).then((r) => live && setTrack(r)).catch(() => {}); return () => { live = false; }; }, [dir, history.length]);

  // What would be different from the last take (free): asked again whenever what is sent could have changed.
  useEffect(() => {
    let live = true;
    setSinceBusy(true);
    api.golden<ChangesInfo>(dir, "changes", { shot: shot.id, provider, model, overrides: settled })
      .then((r) => live && setSince(r)).catch(() => live && setSince(null)).finally(() => live && setSinceBusy(false));
    return () => { live = false; };
  }, [dir, shot.id, provider, model, settled, lookId, keyframeKey, frame, quality, modeKey, history.length]);

  const send = async () => {
    setConfirm(false); setBusy("Queuing…"); setError("");
    try { onQueued(await api.queueRender(dir, [shot.id], provider, model, pins)); }
    catch (e) { setError(errorText(e)); }
    finally { setBusy(""); }
  };
  const resolve = async (job: Job, action: "retry" | "dismiss" | "recheck") => {
    try { onQueued([await api.resolveJob(dir, job.id, action)]); } catch (e) { setError(errorText(e)); }
  };

  const modelTitle = manifest?.title ?? model;
  const shape = sentShape(manifest, { ...auto, ...pins });
  const renderedOnce = history.some((j) => j.state === "ready");
  return (
    <div className="vid-panel">
      <PanelHead icon={<I.Clapper size={18} />} title="Video" tag={active ? "Rendering" : renderedOnce ? "Has a take" : undefined} tone="ok"
                 hint="Step 2: render this shot as video. Every render is kept as a version you can compare." />
      {keyframeRef
        ? <div className="note ok"><I.Check size={14} /> Starts from your approved keyframe.</div>
        : <div className="note warn"><I.Info size={14} /> No approved keyframe yet, so faces and wardrobe may drift.
            {onBack && <> <button className="link" onClick={onBack}>Make a keyframe first</button></>}</div>}
      {(singing || vocalHeard >= 0.5) && <LipSyncNote performer={singing?.performer ?? null} lyrics={singing?.lyrics ?? []} sing={singSetting} vocalHeard={vocalHeard}
                               onSing={async (v) => { try { await api.setProjectSettings(dir, { sing_shot: { id: shot.id, value: v } }); setModeKey((k) => k + 1); } catch (e) { setError(errorText(e)); } }} lipSync={lipSync} audioFirst={audioFirst} keyframeBlocksAudio={kfBlocksAudio} model={manifest?.title ?? model} mode={lipMode} timing={timing} timingBusy={timingBusy}
                               onTiming={async () => { setTimingBusy(true); try { const r = await api.lipsyncCheck<{ rows: { shot: string; verdict: string; detail: string; lag_ms?: number; correlation?: number }[] }>(dir, "timing", { shots: [shot.id] }); setTiming(r.rows[0] ?? "none"); } catch (e) { setError(errorText(e)); } finally { setTimingBusy(false); } }}
                               onMode={async (m) => { try { await api.setProjectSettings(dir, { lip_sync_mode: m }); setModeKey((k) => k + 1); } catch (e) { setError(errorText(e)); } }} />}

      <TrackRecord stats={track} model={model} title={manifest?.title} />
      <ChangesSince changes={since} busy={sinceBusy} />
      <GivenToModel dir={dir} inputs={inputs} />
      <PromptBudget blocks={blocks} />

      <div className="set-card">
        <div className="set-title"><I.Sliders size={14} /> Settings</div>
        {!director ? (
          <div className="set-line"><I.Sparkle size={14} /> Auto · {PROVIDER_NAME[provider]} {modelTitle} <span className="dim">· change in Director Mode</span></div>
        ) : (
          <>
            <div className="seg" role="group" aria-label="Provider">
              {(["fal", "kie", "google", "comfyui"] as const).map((p) => (
                <button key={p} className={provider === p ? "on" : ""} onClick={() => { setProvider(p); setModel(AUTO_MODEL[p] ?? ""); setPins({}); }}>
                  <i className={`key-dot ${p === "comfyui" || keys[p] ? "on" : ""}`} title={p === "comfyui" ? "Runs on your computer" : keys[p] ? "Key added" : "No key yet"} />
                  {PROVIDER_NAME[p]}
                </button>
              ))}
            </div>
            <label className="mini-label" htmlFor="model">Model</label>
            <ModelPicker id="model" catalog={catalog} value={model} label="Model" onChange={(m) => { setModel(m); setPins({}); }}
                         onBlur={(v) => { if (!v) setModel(AUTO_MODEL[provider] ?? ""); setPins({}); }}  onRefresh={async () => setCatalog(await api.renderCatalog(provider, "video", true))} />
            <div className="hint-row">{provider === "comfyui" ? (catalog.length ? `${catalog.length} ComfyUI workflow${catalog.length > 1 ? "s" : ""} · runs on your machine, no charge` : "No ComfyUI workflows yet: add them in Settings")
              : <>{catalog.length ? `${catalog.length} ${PROVIDER_NAME[provider]} video models` : "Loading models…"} · Auto = {AUTO_MODEL[provider]}</>}</div>
          </>
        )}
        <FormatRow manifest={manifest} auto={auto} pins={pins} setPins={setPins} frame={frame} quality={quality} kind="video"
                   onFrame={(k, v) => saveFrame(dir, k, v).catch((e) => setError(errorText(e)))} />
      </div>

      {director && (
        <details className="adv">
          <summary><I.Sliders size={14} /> Advanced · every model input <span className="dim">· {sentRefs.length} reference{sentRefs.length === 1 ? "" : "s"} sent</span></summary>
          <div className="render-refs">
            <b>References sent:</b> {sentRefs.length ? sentRefs.map((r) => r.label.split(" — ")[0].split(":")[0]).join(" · ") : "none"}
            {droppedRefs.length > 0 && <div className="dropped">This model takes fewer references; not sent: {droppedRefs.join(" · ")}</div>}
          </div>
          {manifest && <ModelInputs dir={dir} manifest={manifest} auto={auto} pins={pins} setPins={setPins} />}
          <button className="btn ghost small" onClick={() => setShowRaw((v) => !v)}>{showRaw ? "Hide" : "Show"} exact request</button>
          {showRaw && <pre className="raw">{JSON.stringify(auto, null, 1)}</pre>}
        </details>
      )}

      {renderedOnce && <p className="dim" style={{ fontSize: 12 }}>
        A new render is added as another version. The take in the video stays until you choose another in Takes above (press “Use this take in the video”).</p>}
      {problems.length > 0 && <div className="problems" role="alert">
        <b>This model can't render this shot yet</b>
        <ul>{problems.map((p) => <li key={p}>{p.split(":")[0]}</li>)}</ul>
        <span className="dim">Add the missing input in Director Mode, or pick another model.</span></div>}
      {error && <div className="error-text">{error}</div>}
      <DockSlot tab="video">
        <DockBar chips={<>
          <Pill icon={<I.Sparkle size={12} />} title="The video model">{PROVIDER_NAME[provider]} · {modelTitle}</Pill>
          {shape && <Pill icon={<I.FrameSize size={12} />} title="The shape that will be asked for">{shape.label}</Pill>}
          {busy && <Pill>{busy}</Pill>}
        </>}>
          {!hasKey ? <Cta icon={<I.Lock size={16} />} onClick={onSettings}>Add {PROVIDER_NAME[provider]} key</Cta>
            : <Cta icon={<I.Clapper size={16} />} busy={!!active} price={active ? undefined : priceLabel(est)} disabled={!!busy || !manifest || problems.length > 0}
                   onClick={() => setConfirm(true)}>{active ? "Rendering…" : renderedOnce ? "Render a new take" : "Render video"}</Cta>}
        </DockBar>
      </DockSlot>

      <ExtendCard dir={dir} shot={shot} jobs={jobs} onQueued={onQueued} />

      <Takes dir={dir} shotId={shot.id} takes={history.filter((j) => j.state === "ready" && j.output)} approved={approvedTake} onUse={() => onTakeChosen?.()}
             onLipSync={keys[provider as keyof KeyStatus] && (keys.fal || keys.kie) ? setLipFor : undefined} />

      {history.length > 0 && (
        <details className="attempts" open={history.some((j) => j.state !== "ready")}>
        <summary>{history.some((j) => j.state !== "ready") ? `Details and attempts (${history.length})` : `Details of each take (${history.length})`}</summary>
        {history.filter((j) => j.state === "failed" || j.state === "uncertain").length > 1 && (
          <div className="attempts-bar"><button className="btn ghost small" onClick={async () => { for (const j of history.filter((x) => x.state === "failed" || x.state === "uncertain")) await resolve(j, "dismiss"); }}>
            Dismiss all {history.filter((j) => j.state === "failed" || j.state === "uncertain").length} failed attempts</button></div>)}
        <div className="takes">
          {history.map((j) => (
            <div key={j.id} className="take">
              <div className="take-top"><JobChip job={j} /><span className="dim num">{PROVIDER_NAME[j.provider]} · {shortModel(j.model)}</span></div>
              {j.error_kind && <span className={`err-kind ${j.error_kind}`}>{ERROR_LABEL[j.error_kind] ?? j.error_kind}</span>}
              {j.error && <div className="take-err">{j.error}</div>}
              {j.state === "ready" && j.review?.reviewed && (
                <div className={`take-err ${needsAttention(j) ? "warn" : ""}`}>
                  {j.review.accepted ? "Kept by you. " : ""}{j.review.summary}
                  {needsAttention(j) && <ul className="ri-issues">{(j.review.issues ?? []).map((i, k) => <li key={k}>{i.detail}</li>)}</ul>}
                </div>)}
              {j.state === "ready" && shot.revised && j.created < shot.revised && j.kind !== "lipsync" &&
                <div className="take-err" style={{ color: "var(--warning)" }}>Direction changed after this take. Render a new take to see it.</div>}
              {j.state === "ready" && j.look && j.look !== lookId &&
                <div className="take-err" style={{ color: "var(--warning)" }}>Rendered in an earlier look. Render a new take to match.</div>}
              {j.cost != null && <div className="dim num">Cost: {j.cost} {j.cost_unit ?? ""}</div>}
              {j.kind === "lipsync" && <div className="dim">Lip-synced version</div>}
              {j.state === "ready" && j.kind !== "lipsync" && keys[provider as keyof KeyStatus] && (keys.fal || keys.kie) && (
                <div className="take-actions">
                  <button className="btn small ghost" onClick={() => setLipFor(j)}>Lip-sync this take…</button>
                </div>)}
              {(j.state === "failed" || j.state === "uncertain") && (
                <div className="take-actions">
                  {j.provider_job_id && <button className="btn small" title="The provider already has this render: ask for the result again (no charge)"
                                                 onClick={() => resolve(j, "recheck")}>Check again (no charge)</button>}
                  <button className="btn small" onClick={() => resolve(j, "retry")}>{j.state === "uncertain" ? "Send again" : "Retry"}</button>
                  <button className="btn ghost small" onClick={() => resolve(j, "dismiss")}>Dismiss</button>
                </div>
              )}
            </div>
          ))}
        </div>
        </details>
      )}

      {lipFor && <ConfirmRender count={1} seconds={0} provider={lipProvider} kind="lipsync"
                                model={`${AUTO_LIPSYNC_MODEL[lipProvider]} · re-syncs the mouth to your recording of this shot`}
                                onCancel={() => setLipFor(null)} onConfirm={lipsync} />}
      {confirm && <ConfirmRender count={1} seconds={Number(auto[manifest?.roles.duration ?? "duration"] ?? 0)}
                                 provider={provider} model={modelTitle} onCancel={() => setConfirm(false)} onConfirm={send}
                                 dir={dir} shots={[shot.id]} modelId={model} />}
    </div>
  );
}

const shortModel = (m: string) => m.split("/").slice(-2).join("/");

/** Every input the model exposes, generated from its manifest. Auto values come from the Shot Contract. */
const GROUPS: [string, (f: ManifestInput, role?: string) => boolean][] = [
  ["Prompt", (_f, r) => r === "prompt" || r === "negative_prompt"],
  ["References", (f) => mediaKind(f) !== null],
  ["Format & quality", (f, r) => ["duration", "aspect_ratio", "resolution"].includes(r ?? "") || /fps|frame_rate|quality|bitrate|codec|size/.test(f.name)],
  ["Motion & camera", (f) => /camera|motion|movement|strength|dynamic/.test(f.name)],
  ["Everything else", () => true],
];

function ModelInputs({ dir, manifest, auto, pins, setPins }: {
  dir: string; manifest: Manifest; auto: Record<string, unknown>; pins: Record<string, unknown>; setPins: (p: Record<string, unknown>) => void;
}) {
  const roleOf = useMemo(() => Object.fromEntries(Object.entries(manifest.roles).map(([r, f]) => [f, r])), [manifest]);
  const pin = (name: string, v: unknown) => setPins({ ...pins, [name]: v });
  const unpin = (name: string) => { const n = { ...pins }; delete n[name]; setPins(n); };
  const grouped = GROUPS.map(([g]) => [g, [] as ManifestInput[]] as const);
  for (const f of manifest.inputs) grouped[GROUPS.findIndex(([, t]) => t(f, roleOf[f.name]))][1].push(f);
  return (
    <div className="model-inputs">
      {grouped.filter(([, list]) => list.length).map(([g, list]) => <div key={g} className="mi-group"><h5>{g}</h5>
      {list.map((f) => {
        const pinned = f.name in pins;
        const value = pinned ? pins[f.name] : auto[f.name] ?? f.default;
        const origin = pinned ? "Pinned" : f.name in auto ? "Auto" : f.default !== null && f.default !== undefined ? "Default" : "Unset";
        return (
          <div key={f.name} className={`mi ${pinned ? "pinned" : ""}`}>
            <div className="mi-head">
              <span className="mi-name" title={f.description}>{f.name}{f.required && " *"}</span>
              {roleOf[f.name] && <span className="mi-role">{roleOf[f.name].replace("_", " ")}</span>}
              <span className={`mi-origin ${origin.toLowerCase()}`}>{origin}</span>
              {pinned && <button className="link" onClick={() => unpin(f.name)}>Reset</button>}
            </div>
            {mediaKind(f) ? <MediaInput dir={dir} kind={mediaKind(f)!} multiple={f.type === "array"} value={value} max={f.max_items}
                                        onChange={(v) => pin(f.name, v)} />
              : <InputWidget f={f} value={value} onChange={(v) => pin(f.name, v)} />}
            {f.description && <div className="mi-desc">{f.description.length > 160 ? f.description.slice(0, 157) + "…" : f.description}</div>}
          </div>
        );
      })}</div>)}
    </div>
  );
}

function InputWidget({ f, value, onChange }: { f: ManifestInput; value: unknown; onChange: (v: unknown) => void }) {
  if (f.enum?.length) {
    return <select className="text-input" value={String(value ?? "")} onChange={(e) => {
      const raw = f.enum!.find((x) => String(x) === e.target.value);
      onChange(raw);
    }}>{f.enum.map((o) => <option key={String(o)} value={String(o)}>{String(o)}</option>)}</select>;
  }
  if (f.type === "boolean") {
    return <label className="toggle"><input type="checkbox" checked={Boolean(value)} onChange={(e) => onChange(e.target.checked)} />
      <span>{value ? "On" : "Off"}</span></label>;
  }
  if (f.type === "integer" || f.type === "number") {
    return <input className="text-input" type="number" value={value === null || value === undefined ? "" : String(value)}
                  min={f.minimum ?? undefined} max={f.maximum ?? undefined}
                  onChange={(e) => onChange(e.target.value === "" ? null : f.type === "integer" ? parseInt(e.target.value) : parseFloat(e.target.value))} />;
  }
  if (f.type === "array") {
    const list = Array.isArray(value) ? value.map(String) : [];
    return <textarea className="text-input mono" rows={Math.max(2, list.length)} placeholder="One URL per line"
                     value={list.join("\n")} onChange={(e) => onChange(e.target.value.split("\n").map((x) => x.trim()).filter(Boolean))} />;
  }
  const long = f.name.includes("prompt");
  return long
    ? <textarea className="text-input" rows={6} value={String(value ?? "")} onChange={(e) => onChange(e.target.value)} />
    : <input className="text-input" value={String(value ?? "")} onChange={(e) => onChange(e.target.value)} />;
}

// ---------------------------------------------------------------- confirmation

/** Quality Preflight: before video is paid for, measure each shot's keyframe (free, on this computer) and say if a clean-up is worth doing first. Never blocks the render. */
function PicturePreflight({ dir, shots }: { dir: string; shots: string[] }) {
  const [flagged, setFlagged] = useState<{ shot: string; verdict: string }[] | null>(null);
  useEffect(() => {
    let live = true;
    (async () => {
      const out: { shot: string; verdict: string }[] = [];
      for (const shot of shots.slice(0, 12)) {
        try { const r = await api.fidelity<{ report: { verdict: string } }>(dir, "check", { shot }); if (r.report.verdict !== "ok") out.push({ shot, verdict: r.report.verdict }); } catch { /* no keyframe or unreadable: nothing to say */ }
      }
      if (live) setFlagged(out);
    })();
    return () => { live = false; };
  }, [dir, shots]);
  if (!flagged?.length) return null;
  const first = flagged[0];
  return <p className="fr-note warn" role="note">Picture check: {flagged.length === 1 ? `the keyframe of ${first.shot}` : `${flagged.length} keyframes (${flagged.slice(0, 3).map((f) => f.shot).join(", ")}${flagged.length > 3 ? "…" : ""})`}
    {" "}could be cleaner before you pay for video. <button className="link" onClick={() => window.dispatchEvent(new CustomEvent("pf-open-fidelity", { detail: first.shot }))}>Check {first.shot}…</button> You can also render as it is.</p>;
}

export function ConfirmRender({ count, seconds, provider, model, onCancel, onConfirm, dir, shots, modelId, kind = "video" }: {
  count: number; seconds: number; provider: string; model: string; onCancel: () => void; onConfirm: () => void;
  dir?: string; shots?: string[]; modelId?: string | null; kind?: "video" | "image" | "lipsync";
}) {
  const [est, setEst] = useState<Estimate | null>(null);
  const [estErr, setEstErr] = useState(false);
  useEffect(() => {
    if (!dir || !shots?.length || kind === "lipsync") return;
    api.renderEstimate(dir, shots, provider, modelId ?? null, kind).then(setEst).catch(() => setEstErr(true));
  }, [dir, shots, provider, modelId, kind]);
  const big = (est?.usd ?? 0) >= 25;
  return (
    <Sheet label="Confirm render" style={{ width: "min(500px, calc(100vw - 32px))" }} onDismiss={onCancel}>
        <h2>{kind === "lipsync" ? "Lip-sync this take?" : kind === "image" ? "Make a keyframe?" : `Render ${count === 1 ? "this shot" : `${count} shots`}?`}</h2>
        <p className="sub">
          {PROVIDER_NAME[provider]} · {model}<br />
          {count === 1 && seconds ? `${seconds} s of video, trimmed to the beat in the edit.` : ""}
        </p>
        <div className={`cost ${big ? "big" : ""}`}>
          {!dir ? null : est ? (
            est.usd != null ? <>
              <div className="cost-n num">≈ ${est.usd.toFixed(2)}</div>
              <div className="dim">{count > 1 ? `about $${(est.usd / count).toFixed(2)} per shot · ` : ""}{est.basis}</div>
              {est.lipsync_shots ? <div className="dim">Includes a dedicated lip-sync pass for {est.lipsync_shots === 1 && count === 1 ? "this speaking close-up"
                : `${est.lipsync_shots} speaking close-up${est.lipsync_shots > 1 ? "s" : ""}`}.</div> : null}
            </> : <>
              <div className="cost-n">{provider === "kie" ? "Billed in Kie credits" : provider === "google" ? "Billed by Google" : "Price not published"}</div>
              <div className="dim">{est.basis}{est.kie_credits != null ? ` Balance: ${est.kie_credits.toLocaleString()} credits.` : ""}</div>
            </>
          ) : estErr ? <div className="dim">Couldn't fetch the price right now.</div> : <div className="dim">Checking price…</div>}
        </div>
        {kind === "video" && dir && shots?.length ? <PicturePreflight dir={dir} shots={shots} /> : null}
        {est?.native_blocked?.length ? <p className="error-text" role="alert">This model makes no sound, and {est.native_blocked.length === 1 ? "a shot" : `${est.native_blocked.length} shots`} here
          {" "}need{est.native_blocked.length === 1 ? "s" : ""} it: this scene's dialogue is spoken by the video model. Choose a model that makes sound (for example Veo 3.1 or Kling 2.6),
          or turn native dialogue off in the scene's dialogue.</p> : est?.native_note ? <p className="fr-note warn">{est.native_note}</p> : null}
        <p className="dim" style={{ marginTop: 10 }}>{PROVIDER_NAME[provider]} bills your account. FilmCrafter sends each shot once and never
          re-sends a render automatically.</p>
        <div className="sheet-actions">
          <button className="btn ghost" onClick={onCancel}>Cancel</button>
          <button className="btn primary" onClick={onConfirm} autoFocus={!big} disabled={!!est?.native_blocked?.length}>
            {est?.usd != null ? `Render · ≈ $${est.usd.toFixed(2)}` : "Render"}</button>
        </div>
    </Sheet>
  );
}
