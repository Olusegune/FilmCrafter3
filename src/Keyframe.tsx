import { useEffect, useRef, useState } from "react";
import { api, AUTO_IMAGE_MODEL, errorText, type CatalogItem, type Job, type KeyStatus, type Manifest, type Shot } from "./api";
import { useRouting } from "./Routing";
import { ModelPicker } from "./ModelPicker";
import { openUpscale } from "./UpscaleSheet";
import { openFidelity } from "./FidelitySheet";
import { ACTIVE_STATES, ConfirmRender, defaultProvider, PROVIDER_NAME } from "./Render";
import { Cta, DockBar, DockSlot, PanelHead, Pill, priceLabel, useEstimate } from "./Dock";
import { FormatRow } from "./FormatRow";
import { saveFrame, sentShape } from "./frame";
import * as I from "./icons";
import { HandFix } from "./HandFix";

/**
 * Keyframe first: a still of the shot (cheap, fast) that the user approves before paying for video.
 * The approved still becomes the video's first frame or lead reference, which keeps characters and
 * composition consistent. The main action lives in the inspector's pinned bar, next to the choices that shape it.
 */
const FIXES = ["No floating or disembodied hands", "Hands hold the prop naturally", "Correct number of fingers", "Keep the exact outfit", "No extra people", "No text or logos"];

export function KeyframePanel({ dir, shot, plan, jobs, keys, director, approved, onJobs, onApproved, onSettings, aspect = "21 / 9", frame = "16:9", quality = "standard", onNext }: {
  dir: string; shot: Shot; plan: string; jobs: Job[]; keys: KeyStatus; director: boolean; aspect?: string; frame?: string; quality?: string;
  approved: string | null; onJobs: (j: Job[]) => void; onApproved: (ref: string | null) => void; onSettings: () => void; onNext?: () => void;
}) {
  const [provider, setProvider] = useState(defaultProvider(keys));
  const [model, setModel] = useState(AUTO_IMAGE_MODEL[defaultProvider(keys)]);
  const { route } = useRouting(dir);
  const routed = useRef(false);
  useEffect(() => {
    const p = route?.image;
    if (!routed.current && p?.provider && p.provider !== "comfyui") { routed.current = true; setProvider(p.provider); setModel(p.model!); }
  }, [route]);
  const [catalog, setCatalog] = useState<CatalogItem[]>([]);
  const [confirm, setConfirm] = useState(false);
  const [fixHand, setFixHand] = useState(false);              // Fix a hand: redraw only the marked part of the approved keyframe
  const [error, setError] = useState("");
  const [manifest, setManifest] = useState<Manifest | null>(null);
  const [auto, setAuto] = useState<Record<string, unknown>>({});
  const [pins, setPins] = useState<Record<string, unknown>>({});
  const [fix, setFix] = useState("");
  const [told, setTold] = useState("");
  const [refs, setRefs] = useState<{ label: string; media: string }[]>([]);
  const fixRef = useRef<HTMLDivElement>(null);
  const stills = jobs.filter((j) => j.shot_id === shot.id && j.kind === "image" && j.state !== "dismissed")
    .sort((a, b) => b.created - a.created);
  const busy = stills.some((j) => ACTIVE_STATES.includes(j.state));
  const [picked, setPicked] = useState<string | null>(null);
  const [lightbox, setLightbox] = useState(false);
  useEffect(() => { setPicked(null); setLightbox(false); setPins({}); setFix(""); }, [shot.id]);
  // show the chosen version; otherwise the approved one; otherwise the newest finished
  const shownJob = stills.find((j) => j.id === picked)
    ?? stills.find((j) => j.output && `project:${j.output}` === approved)
    ?? stills.find((j) => j.state === "ready") ?? stills[0];
  const shownRef = shownJob?.output ? `project:${shownJob.output}` : null;
  const ready = !!shownJob?.output && shownJob.state === "ready";
  const inUse = ready && shownRef === approved;

  useEffect(() => { if (director) api.renderCatalog(provider, "image").then(setCatalog).catch(() => setCatalog([])); }, [director, provider]);
  // What would be asked of the model (free; nothing is uploaded), so the shape and the choices can be shown beside the button.
  const [settled, setSettled] = useState(pins);
  useEffect(() => { const t = setTimeout(() => setSettled(pins), 400); return () => clearTimeout(t); }, [pins]);
  useEffect(() => {
    let live = true;
    api.renderPreview(dir, shot.id, provider, model, settled, "image")
      .then((r) => { if (live) { setManifest(r.manifest); setAuto(r.payload); setTold(String(r.payload[r.manifest.roles.prompt ?? "prompt"] ?? "")); setRefs(r.references ?? []); } })
      .catch(() => { if (live) { setManifest(null); setAuto({}); setTold(""); setRefs([]); } });
    return () => { live = false; };
  }, [dir, shot.id, provider, model, settled, frame, quality]);
  const est = useEstimate(dir, [shot.id], provider, model, "image", [frame, quality]);

  const make = async () => {
    setConfirm(false); setError("");
    try { onJobs(await api.queueRender(dir, [shot.id], provider, model, pins, fix.trim() ? [fix.trim()] : [], "image")); setFix(""); } catch (e) { setError(errorText(e)); }
  };
  const approve = async (ref: string | null) => {
    try { await api.setKeyframe(dir, plan, shot.id, ref); onApproved(ref); } catch (e) { setError(errorText(e)); }
  };
  const hasKey = keys[provider as keyof KeyStatus];
  const shape = sentShape(manifest, { ...auto, ...pins });
  const price = priceLabel(est);
  const again = fix.trim() ? "Fix and remake" : null;
  const modelName = manifest?.title ?? model.split("/").slice(-1)[0];

  return (
    <div className="kf-panel">
      <PanelHead icon={<I.ImageIcon size={18} />} title="Keyframe" tag={inUse ? "In use" : undefined}
                 hint="Step 1: make a still of this shot and approve it. The video then starts from it, so faces and wardrobe stay put." />
      {ready ? (
        <div className={`kf-hero ${inUse ? "approved" : ""}`}>
          <button className="kf-hero-img" onClick={() => setLightbox(true)} title="Open full size" style={{ aspectRatio: aspect }}>
            <img src={api.mediaUrl(`${dir}/${shownJob!.output}`)} alt={`Keyframe for ${shot.id}`}
                 onError={(e) => { const el = e.currentTarget; el.replaceWith(Object.assign(document.createElement("span"),
                   { className: "img-missing", textContent: "Image file missing from the project folder" })); }} />
            {inUse && <span className="kf-badge inuse"><I.Check size={12} /> In use</span>}
            <CheckBadge job={shownJob!} />
          </button>
          {shownJob!.still_check && checkNotes(shownJob!.still_check).details.length > 0 && <div className="kf-check-detail"><I.Alert size={13} />
            <span>{checkNotes(shownJob!.still_check).state === "look" ? "Worth a look before animating: " : ""}{checkNotes(shownJob!.still_check).details.join(" ")}</span></div>}
          <div className="kf-hero-actions">
            <span className="dim num kf-meta">{shownJob!.model.split("/").slice(-2).join("/")}</span>
            {inUse && approved && <button className="link" onClick={() => setFixHand(true)} title="Redraw only a hand, and leave the rest of the picture alone">Fix a hand…</button>}
            {inUse && <button className="link" onClick={() => approve(null)}>Stop using this keyframe</button>}
            {inUse && <button className="link" onClick={() => openFidelity(shot.id)} title="Measure sharpness, noise and compression, and tidy this picture for free (the original is kept)">Check quality…</button>}
            {inUse && <button className="link" onClick={() => openUpscale({ kind: "keyframe", shot: shot.id })} title="Make this keyframe sharper and larger (Topaz, Recraft…)">Upscale…</button>}
          </div>
        </div>
      ) : stills.length ? (
        <div className="kf-hero-wait" style={{ aspectRatio: aspect }}>
          {busy ? <><span className="spin" /> Making still…</> : (stills[0].error ?? "No finished still yet")}</div>
      ) : (
        <div className="kf-empty" style={{ aspectRatio: aspect }}>
          <I.ImageIcon size={30} /><b>No keyframe yet</b>
          <span>Choose your settings below, then press <em>Make keyframe</em>.</span>
        </div>
      )}
      {stills.length > 1 && <div className="kf-strip" role="listbox" aria-label="Versions">
        {stills.map((j, i) => {
          const ref = j.output ? `project:${j.output}` : null;
          return (
            <button key={j.id} role="option" aria-selected={j.id === shownJob?.id} title={`Version ${stills.length - i}`}
                    className={`kf-thumb ${j.id === shownJob?.id ? "sel" : ""}`} onClick={() => setPicked(j.id)} disabled={j.state !== "ready"}>
              {j.state === "ready" && j.output ? <img src={api.mediaUrl(`${dir}/${j.output}`)} alt="" loading="lazy" />
                : <span className="kf-thumb-wait">{ACTIVE_STATES.includes(j.state) ? <span className="spin sm" /> : <I.Alert size={12} />}</span>}
              {ref && ref === approved && <i className="kf-dot inuse" />}
              {j.still_check?.ok === false && <i className="kf-dot bad" />}
            </button>
          );
        })}
      </div>}

      <div className="set-card">
        <div className="set-title"><I.Sliders size={14} /> Settings</div>
        {director ? (
          <>
            <div className="seg" role="group" aria-label="Image provider">
              {(["fal", "kie", "google", "openai", "byteplus"] as const).map((p) => (
                <button key={p} className={provider === p ? "on" : ""} onClick={() => { setProvider(p); setModel(AUTO_IMAGE_MODEL[p]); setPins({}); }}>
                  <i className={`key-dot ${keys[p] ? "on" : ""}`} title={keys[p] ? "Key added" : "No key yet"} />{PROVIDER_NAME[p]}</button>
              ))}
            </div>
            <ModelPicker catalog={catalog} value={model} onChange={(m) => { setModel(m); setPins({}); }} label="Image model" onRefresh={async () => setCatalog(await api.renderCatalog(provider, "image", true))} />
            <div className="hint-row">{catalog.length ? `${catalog.length} image models` : "Loading models…"}</div>
          </>
        ) : (
          <div className="set-line"><I.Sparkle size={14} /> {PROVIDER_NAME[provider]} · {modelName} <span className="dim">· change in Director Mode</span></div>
        )}
        <FormatRow manifest={manifest} auto={auto} pins={pins} setPins={setPins} frame={frame} quality={quality} kind="image"
                   onFrame={(k, v) => saveFrame(dir, k, v).catch((e) => setError(errorText(e)))} />
      </div>

      <div className="set-card kf-fix" ref={fixRef}>
        <div className="set-title"><I.Wand size={14} /> See something wrong?</div>
        <p className="dim kf-fix-hint">Say what to fix and the next keyframe is told to correct it. Writing is free; you see the price before anything is made.</p>
        <textarea className="text-input" rows={2} maxLength={400} value={fix} onChange={(e) => setFix(e.target.value)} aria-label="What should be fixed in this keyframe"
                  placeholder="e.g. the hand holds the staff properly, no floating hands" />
        <div className="pr-ideas">{FIXES.map((t) => <button key={t} className="pr-idea" onClick={() => setFix((f) => (f.includes(t) ? f : (f.trim() ? `${f.trim().replace(/[.,]$/, "")}. ` : "") + t))}>{t}</button>)}</div>
        {fix.trim() && <p className="dim kf-fix-hint">Added to the prompt as: “Corrections from review: {fix.trim().replace(/\.$/, "")}.”</p>}
      </div>
      {told && (
        <details className="set-card kf-prompt">
          <summary><I.Doc size={14} /> What the model is told</summary>
          <pre className="kf-pre">{told}</pre>
          {refs.length > 0 && <><p className="dim kf-fix-hint">Pictures it is shown for consistency:</p>
            <ul className="kf-refs">{refs.map((r, i) => <li key={i}>{r.label}</li>)}</ul></>}
          <p className="dim kf-fix-hint">This is built from the shot, the Production Bible, the library and the camera &amp; lighting choices. To change the shot's wording, edit the shot's details above; to steer this remake, use the box above.</p>
        </details>
      )}
      {error && <div className="error-text">{error}</div>}
      <DockSlot tab="keyframe">
        <DockBar chips={<>
          <Pill icon={<I.Sparkle size={12} />} title="The image model">{PROVIDER_NAME[provider]} · {modelName}</Pill>
          {shape && <Pill icon={<I.FrameSize size={12} />} title="The shape that will be asked for">{shape.label}</Pill>}
        </>}>
          {!hasKey ? <Cta icon={<I.Lock size={16} />} onClick={onSettings}>Add {PROVIDER_NAME[provider]} key</Cta>
            : busy ? <Cta busy onClick={() => {}} disabled>Making still…</Cta>
            : ready && !inUse ? <>
                <Cta icon={<I.Check size={16} />} onClick={() => approve(shownRef)}>Use this keyframe</Cta>
                <Cta tone="quiet" icon={<I.Refresh size={15} />} price={price} onClick={() => setConfirm(true)}>{again ?? "Another"}</Cta></>
            : inUse && onNext ? <>
                <Cta icon={<I.Clapper size={16} />} onClick={onNext}>Next: render the video</Cta>
                <Cta tone="quiet" icon={<I.Refresh size={15} />} price={price} onClick={() => setConfirm(true)}>{again ?? "Another"}</Cta></>
            : <Cta icon={<I.Sparkle size={16} />} price={price} onClick={() => setConfirm(true)}>{again ?? (stills.length ? "Make another keyframe" : "Make keyframe")}</Cta>}
        </DockBar>
      </DockSlot>
      {lightbox && shownJob?.output && (
        <div className="overlay" onClick={() => setLightbox(false)}>
          <div className="kf-lightbox" onClick={(e) => e.stopPropagation()}>
            <img src={api.mediaUrl(`${dir}/${shownJob.output}`)} alt={`Keyframe for ${shot.id}`} />
            <div className="wiz-row" style={{ justifyContent: "space-between", marginTop: 10 }}>
              <span className="num">{shot.id} · version {stills.length - stills.findIndex((j) => j.id === shownJob.id)} of {stills.length}</span>
              <div className="wiz-row">
                <button className="btn" onClick={() => { setLightbox(false); setTimeout(() => fixRef.current?.scrollIntoView({ behavior: "smooth", block: "center" }), 60); }}><I.Wand size={14} /> Fix something…</button>
                {shownRef !== approved && <button className="btn primary" onClick={() => { approve(shownRef); setLightbox(false); }}>Use this keyframe</button>}
                <button className="btn ghost" onClick={() => setLightbox(false)}>Close</button>
              </div>
            </div>
          </div>
        </div>
      )}
      {fixHand && approved && <HandFix dir={dir} shot={shot.id} image={approved.replace(/^project:/, "")} onClose={() => setFixHand(false)} />}
      {confirm && <ConfirmRender count={1} seconds={0} provider={provider} model={model} kind="image"
                                 onCancel={() => setConfirm(false)} onConfirm={make} dir={dir} shots={[shot.id]} modelId={model} />}
    </div>
  );
}

const PROBLEM_NAME: Record<string, string> = { anatomy: "hands and body", collage: "collage", text: "text on the picture", identity: "wrong person", framing: "framing", missing: "missing person", artifact: "artifact", look: "style" };

/** Pure: what the keyframe check says, in words. `look` is a picture that passed but has a minor problem (soft hands) the filmmaker should see. */
export function checkNotes(c: NonNullable<Job["still_check"]>): { state: "pass" | "fail" | "look" | "unchecked"; label: string; details: string[] } {
  const problems = c.problems ?? [];
  if (c.ok === null || c.ok === undefined) return { state: "unchecked", label: "Not checked", details: [] };
  if (c.ok === false) return { state: "fail", label: [...new Set(problems.map((p) => PROBLEM_NAME[p.kind] ?? p.kind))].join(", ") || "Check failed", details: problems.map((p) => p.detail) };
  const minor = problems.filter((p) => p.severity === "minor");
  return minor.length ? { state: "look", label: `Passed · look at the ${[...new Set(minor.map((p) => PROBLEM_NAME[p.kind] ?? p.kind))].join(", ")}`, details: minor.map((p) => p.detail) } : { state: "pass", label: "Check passed", details: [] };
}

/** Keyframe check result on the preview. */
function CheckBadge({ job }: { job: Job }) {
  const c = job.still_check;
  if (!c) return null;
  const n = checkNotes(c);
  if (n.state === "pass") return <span className="kf-badge pass"><I.Check size={11} /> {n.label}</span>;
  if (n.state === "look") return <span className="kf-badge pass"><I.Alert size={11} /> {n.label}</span>;
  if (n.state === "fail") return <span className="kf-badge fail"><I.Alert size={11} /> {n.label}</span>;
  return <span className="kf-badge" title={c.error}>{n.label}</span>;
}
