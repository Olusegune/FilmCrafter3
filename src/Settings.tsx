import { UpdateRow } from "./Updates";
import { Sheet } from "./Sheet";
import { ModelsRow } from "./ModelsRow";
import { useEffect, useState } from "react";
import { open } from "@tauri-apps/plugin-dialog";
import { api, type Diagnosis, errorText, type Brain, type KeyStatus, type ProviderStatus } from "./api";
import { LocalModelsPanel } from "./Routing";
import { ComfyInstallCard } from "./ComfyInstall";
import { savedScale, setScale, UI_SCALES } from "./uiScale";
import { Check, Close } from "./icons";
import { KeyGroups } from "./KeyRows";

const PROVIDERS: { id: keyof KeyStatus; name: string; purpose: string }[] = [
  { id: "kie", name: "Kie.ai", purpose: "Video, images and upscaling" },
  { id: "openai", name: "OpenAI", purpose: "OpenAI's own models" },
  { id: "anthropic", name: "Anthropic Claude", purpose: "Claude models for planning and direction" },
  { id: "openrouter", name: "OpenRouter", purpose: "One key for hundreds of cheaper models (choose it under AI brain)" },
  { id: "fal", name: "fal.ai", purpose: "Video, images and upscaling" },
  { id: "google", name: "Google Gemini", purpose: "Veo video and Nano Banana images, direct from Google" },
  { id: "byteplus", name: "BytePlus (Seedream)", purpose: "Seedream pictures direct from ByteDance, at their published price" },
  { id: "elevenlabs", name: "ElevenLabs", purpose: "Custom voices: choose, design or clone one for each character, and have lines spoken in it" },
];

/** Keys go straight to the Windows Credential Manager / macOS Keychain; they never touch project files. */
export function Settings({ onClose, onHelp }: { onClose: () => void; onHelp?: () => void }) {
  const [status, setStatus] = useState<KeyStatus>({ openai: false, anthropic: false, fal: false, kie: false, google: false, elevenlabs: false, openrouter: false });

  const refresh = () => api.keyStatus().then((k) => { setStatus(k); window.dispatchEvent(new Event("pf-keys-changed")); });
  useEffect(() => { refresh(); }, []);

  return (
    <Sheet label="Settings" onDismiss={onClose}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "start" }}>
          <div>
            <h2>Connections</h2>
            <p className="sub">Keys are stored securely by Windows, never in your projects.</p>
          </div>
          <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
            {onHelp && <button className="btn ghost sm" onClick={onHelp} title="The user guide (F1)">Documentation</button>}
            <button className="icon-btn" onClick={onClose} aria-label="Close"><Close /></button>
          </div>
        </div>
        <KeyGroups providers={PROVIDERS} status={status}
                   onSave={async (id, key) => { await api.setKey(id, key); await refresh(); }}
                   onRemove={async (id) => { await api.deleteKey(id); await refresh(); }} />
        <InterfaceSize />
        <BrainPanel openaiKey={status.openai} anthropicKey={!!status.anthropic} openrouterKey={!!status.openrouter} googleKey={!!status.google} />
        <ComfyPanel />
        <ProviderOverview keys={status} />
        <Diagnostics keys={status} />
        <LocalModelsPanel />
        <UpdateRow />
        <ModelsRow />
    </Sheet>
  );
}

/** Local rendering with your own ComfyUI workflows: no key, no per-render charge. */
type ComfyFound = { running: { url: string; version?: string; device?: string; vram_gb?: number }[];
  installs: { kind: string; path: string; start: string | null }[]; configured_url: string };
type ComfyHealth = { connected: boolean; device?: string; vram_gb?: number; vram_free_gb?: number; version?: string; running: number; waiting: number; advice: string[] };
type ComfyTemplate = { id: string; title: string; kind: string; ready: boolean; uses?: string; missing: string[] };

function ComfyPanel() {
  const [c, setC] = useState<ProviderStatus["comfyui"] | null>(null);
  const [found, setFound] = useState<ComfyFound | null>(null);
  const [templates, setTemplates] = useState<ComfyTemplate[] | null>(null);
  const [url, setUrl] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState("");
  const [dl, setDl] = useState<{ gb: number; free_gb: number | null; files: { name: string; gb: number }[] } | null>(null);
  useEffect(() => {
    const un = api.onEngine((e) => { if (e.task === "comfy" && e.stage) setBusy(`${e.stage[0].toUpperCase()}${e.stage.slice(1)}${typeof e.progress === "number" ? ` · ${Math.round((e.progress as number) * 100)}%` : ""}`); });
    return () => { un.then((f) => f()); };
  }, []);
  const planDownload = async () => {
    const ids = (templates ?? []).filter((t) => !t.ready).map((t) => t.id);
    try { setDl(await api.comfySetup("downloads", { templates: ids, url })); } catch (e) { setErr(errorText(e)); }
  };
  const runDownload = async () => {
    const ids = (templates ?? []).filter((t) => !t.ready).map((t) => t.id);
    setDl(null); setBusy("Starting the download…"); setErr("");
    try { const r = await api.comfySetup<{ templates: ComfyTemplate[] }>("download", { templates: ids, url }); setTemplates(r.templates); await run("status"); }
    catch (e) { setErr(errorText(e)); } finally { setBusy(""); }
  };
  const run = async (action: "status" | "comfy_config" | "comfy_add" | "comfy_remove", data: Record<string, unknown> = {}) => {
    setBusy("…"); setErr("");
    try {
      const r = await api.providers(action, data);
      const next = r && "providers" in r ? r.comfyui : r;
      if (!next || typeof next !== "object") throw new Error("FilmCrafter could not read the local AI status. Try again.");      // never a raw script error on screen
      setC(next); setUrl((u) => u || next.url);
    } catch (e) { setErr(errorText(e)); } finally { setBusy(""); }
  };
  useEffect(() => { run("status"); }, []);
  const find = async () => {
    setBusy("Looking for ComfyUI on this computer…"); setErr("");
    try {
      const f = await api.comfySetup<ComfyFound>("detect");
      setFound(f);
      if (f.running.length) {
        setUrl(f.running[0].url);
        setBusy("Setting up ready-made workflows…");
        const r = await api.comfySetup<{ templates: ComfyTemplate[] }>("setup", { url: f.running[0].url });
        setTemplates(r.templates);
      }
      await run("status");
    } catch (e) { setErr(errorText(e)); } finally { setBusy(""); }
  };
  const start = async (path: string) => {
    setBusy("Starting ComfyUI… (the first start can take a minute)"); setErr("");
    try {
      await api.comfySetup("start", { path });
      for (let i = 0; i < 24; i++) {   // wait up to two minutes for it to answer
        await new Promise((r) => setTimeout(r, 5000));
        const f = await api.comfySetup<ComfyFound>("detect");
        if (f.running.length) { setBusy(""); await find(); return; }
      }
      setErr("ComfyUI didn't answer yet. When its window says it's ready, press Find ComfyUI.");
    } catch (e) { setErr(errorText(e)); } finally { setBusy(""); }
  };
  const [wantInstall, setWantInstall] = useState(false);
  const [health, setHealth] = useState<ComfyHealth | null>(null);
  const [made, setMade] = useState<{ seconds: number; url: string } | null>(null);
  const checkHealth = async () => {
    setBusy("Checking ComfyUI…"); setErr(""); setMade(null);
    try { setHealth(await api.comfySetup<ComfyHealth>("health", { url })); } catch (e) { setErr(errorText(e)); } finally { setBusy(""); }
  };
  const testPicture = async () => {
    setBusy("Making a small test picture…"); setErr(""); setMade(null);
    try { setMade(await api.comfySetup<{ seconds: number; url: string }>("test", { url })); } catch (e) { setErr(errorText(e)); } finally { setBusy(""); }
  };
  const add = async () => {
    const f = await open({ filters: [{ name: "ComfyUI workflow (API format)", extensions: ["json"] }] });
    if (typeof f === "string") run("comfy_add", { path: f });
  };
  return (
    <div className="field comfy-panel">
      <label style={{ display: "flex", justifyContent: "space-between" }}>
        <span>ComfyUI <span className="opt">Free renders on your own graphics card</span></span>
        {c?.connected ? <span className="status-ok"><Check size={14} /> Running{c.device ? ` · ${c.device}` : ""}</span> :
          <span className="status-missing">{c ? "Not running" : "Checking…"}</span>}
      </label>
      <div className="comfy-find">
        <button className="btn primary" onClick={find} disabled={!!busy}>{c?.connected ? "Check ComfyUI and update workflows" : "Find ComfyUI"}</button>
        <span className="dim">{busy || "Looks for a running ComfyUI (Desktop or portable) and installed copies, then sets everything up. No nodes to wire."}</span>
      </div>
      {!c?.connected && !found && !wantInstall && <p className="dim" style={{ margin: "4px 0" }}>No ComfyUI yet? <button className="link" onClick={() => setWantInstall(true)}>Install it for me</button></p>}
      {wantInstall && !found && <ComfyInstallCard onInstalled={(path) => { setWantInstall(false); start(path); }} />}
      {found && !found.running.length && (found.installs.length ? <div className="comfy-installs">
          {found.installs.some((i) => (i as { hint?: string }).hint) && <div className="dim">{(found.installs.find((i) => (i as { hint?: string }).hint) as { hint?: string }).hint}</div>}
          <div className="dim">ComfyUI is installed but not running:</div>
          {found.installs.map((i) => <div key={i.path} className="comfy-flow"><span><b>{i.kind}</b> <span className="dim">{i.path}</span></span>
            {i.start ? <button className="btn small" disabled={!!busy} onClick={() => start(i.start!)}>Start it</button> : <span className="dim">start it yourself</span>}</div>)}
        </div> : <ComfyInstallCard onInstalled={(path) => start(path)} />)}
      {c?.connected && <div className="comfy-find">
        <button className="btn small" disabled={!!busy} onClick={checkHealth}>Check health</button>
        <button className="btn small" disabled={!!busy} onClick={testPicture}>Make a test picture</button>
        <span className="dim">Free. The health check says what's missing in plain words; the test renders one small picture.</span></div>}
      {health?.connected && <div className="comfy-health" role="status">
        <span><b>{health.device ?? "Graphics card"}</b>{health.vram_gb ? ` · ${health.vram_gb} GB, ${health.vram_free_gb} GB free` : ""}{health.version ? ` · ComfyUI ${health.version}` : ""}
          {` · ${health.running} rendering, ${health.waiting} waiting`}</span>
        <ul>{health.advice.map((a) => <li key={a}>{a}</li>)}</ul></div>}
      {made && <div className="status-ok" role="status" style={{ marginTop: 6 }}>It works: a test picture was made in {made.seconds} s on your own computer.</div>}
      {found?.running[0] && <div className="dim" style={{ marginTop: 6 }}>Found at {found.running[0].url}
        {found.running[0].device ? ` · ${found.running[0].device}` : ""}{found.running[0].vram_gb ? ` · ${found.running[0].vram_gb} GB` : ""}
        {found.running[0].version ? ` · ComfyUI ${found.running[0].version}` : ""}</div>}
      {templates && templates.some((t) => !t.ready) && <div className="comfy-dl">
        {!dl ? <button className="btn" disabled={!!busy} onClick={planDownload}>Download the missing models for me…</button> :
          <div className="sup-confirm">
            <span>Download <b>{dl.files.length} files, {dl.gb} GB</b> into ComfyUI's model folders{dl.free_gb ? ` (${dl.free_gb} GB free)` : ""}.
              Free, from Hugging Face; can take a while. You can keep working.</span>
            <button className="btn primary small" onClick={runDownload}>Download</button>
            <button className="btn ghost small" onClick={() => setDl(null)}>Cancel</button></div>}
      </div>}
      {templates && <div className="comfy-templates">{templates.map((t) => (
        <div key={t.id} className={`diag ${t.ready ? "diag-verified" : "diag-blocked"}`}>
          <div className="diag-head"><b>{t.title}</b><span className="diag-pill">{t.ready ? "Ready" : "Needs a download"}</span></div>
          {t.ready ? <div className="dim">Uses {t.uses}. Choose Local First in Plan & budget to render with it.</div>
            : <div className="dim">In ComfyUI open <b>Manager → Model Manager</b> (or the template browser) and download: {t.missing.join("; ")}. Then press the button above again.</div>}
        </div>))}</div>}
      <details className="comfy-advanced">
        <summary>Advanced: address and your own workflows</summary>
        <div className="key-row" style={{ marginTop: 8 }}>
          <input className="text-input" value={url} onChange={(e) => setUrl(e.target.value)} placeholder="http://127.0.0.1:8188" spellCheck={false} />
          <button className="btn" disabled={!!busy} onClick={() => run("comfy_config", { url })}>Connect</button>
        </div>
        <div className="comfy-flows">
          {c?.workflows.map((w) => (
            <div key={w.model} className="comfy-flow">
              <span><b>{w.title}</b> <span className="dim">· {w.kind} · {w.placeholders.length ? w.placeholders.map((p) => `{{${p}}}`).join(" ") : "auto-wired"}</span></span>
              <button className="btn ghost small" onClick={() => run("comfy_remove", { model: w.model })}>Remove</button>
            </div>
          ))}
          <button className="btn small" onClick={add}>Add your own workflow…</button>
          <p className="dim" style={{ marginTop: 6 }}>In ComfyUI, export your workflow with <b>Export (API)</b>. Type <code>{"{{prompt}}"}</code>,{" "}
            <code>{"{{image}}"}</code>, <code>{"{{seed}}"}</code>, <code>{"{{width}}"}</code>, <code>{"{{height}}"}</code> or <code>{"{{frames}}"}</code> into
            any field you want FilmCrafter to fill.</p>
        </div>
      </details>
      {err && <div className="error-text">{err}</div>}
    </div>
  );
}

/** Which model families each provider carries, and which were confirmed with a real render. */
function ProviderOverview({ keys }: { keys: KeyStatus }) {
  const [s, setS] = useState<ProviderStatus | null>(null);
  useEffect(() => { api.providers("status").then((r) => { if (r && "providers" in r) setS(r); }).catch(() => {}); }, [keys]);
  if (!s) return null;
  return (
    <div className="field">
      <label>Models by provider</label>
      <table className="prov-table"><tbody>
        {s.providers.map((p) => (
          <tr key={p.provider}>
            <td><b>{p.name}</b><br /><span className={p.connected ? "status-ok" : "status-missing"}>{p.connected ? "Connected" : "Not connected"}</span></td>
            <td>{p.families.join(" · ") || (p.provider === "comfyui" ? "Your workflows" : "")}
              <div className="dim">{p.verified.length ? `Tested with a real render: ${p.verified.length} model${p.verified.length > 1 ? "s" : ""}` : "Not yet tested with a real render"}</div></td>
          </tr>
        ))}
      </tbody></table>
      <p className="dim">Other models appear in Director Mode. Models not yet tested with a real render are checked against the provider's published inputs only.</p>
    </div>
  );
}

const DIAG_LABEL = { verified: "Working", unverified: "Signed in, no finished render yet", blocked: "Out of credit", unavailable: "Not available" };
const ago = (t: number) => { if (!t) return ""; const s = Date.now() / 1000 - (t > 1e12 ? t / 1000 : t);
  return s < 3600 ? `${Math.max(1, Math.round(s / 60))} min ago` : s < 86400 ? `${Math.round(s / 3600)} h ago` : `${Math.round(s / 86400)} d ago`; };

/** Free health check per provider: sign-in, balance, last real success and failure, and what to do about it. */
function Diagnostics({ keys }: { keys: KeyStatus }) {
  const [d, setD] = useState<Diagnosis[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const run = () => { setBusy(true); setErr(""); api.diagnostics().then((r) => setD(r.providers)).catch((e) => setErr(String(e))).finally(() => setBusy(false)); };
  useEffect(run, [keys]);
  return (
    <div className="field">
      <div className="wiz-row" style={{ justifyContent: "space-between" }}>
        <label>Provider health</label>
        <button className="btn ghost small" onClick={run} disabled={busy}>{busy ? <><span className="spin sm" /> Checking…</> : "Check again"}</button>
      </div>
      {err && <div className="error-text">{err}</div>}
      {d && <div className="diag-list">{d.map((p) => (
        <div key={p.provider} className={`diag diag-${p.status}`}>
          <div className="diag-head"><b>{p.name}</b><span className="diag-pill">{DIAG_LABEL[p.status]}</span></div>
          <div className="dim">{p.message}</div>
          {p.recovery && <div className="diag-fix">{p.explanation} {p.recovery}</div>}
          <div className="dim diag-hist">
            {p.history.ready} finished · {p.history.failed} failed
            {p.history.last_ok && <> · last success {ago(p.history.last_ok.at)} ({p.history.last_ok.shot}, {p.history.last_ok.model.split("/").slice(-1)[0]})</>}
          </div>
          {p.history.last_fail && (!p.history.last_ok || p.history.last_fail.at > p.history.last_ok.at) &&
            <div className="diag-fix">Last failure {ago(p.history.last_fail.at)} ({p.history.last_fail.shot}): {p.history.last_fail.recovery}</div>}
        </div>))}</div>}
      <p className="dim">These checks are free: they sign in and read your balance, and never send a render. “Working” means signed in now and at least one real render has finished.</p>
    </div>
  );
}

const BRAINS: { id: Brain["provider"]; name: string; url: string; blurb: string }[] = [
  { id: "openai", name: "OpenAI", url: "", blurb: "Cloud. Best plans and reviews; uses your OpenAI key and credits." },
  { id: "anthropic", name: "Claude", url: "https://api.anthropic.com/v1", blurb: "Cloud. Uses your Anthropic API key for story analysis, planning and direction." },
  { id: "openrouter", name: "OpenRouter", url: "https://openrouter.ai/api/v1", blurb: "Cloud, one key (set it in Connections above). Hundreds of models, many far cheaper than OpenAI: pick one by price. Plans and reviews are only as good as the model you choose." },
  { id: "gemini", name: "Google Gemini", url: "https://generativelanguage.googleapis.com/v1beta/openai", blurb: "Cloud. Uses your Google Gemini key through Google's official OpenAI-compatible endpoint." },
  { id: "lmstudio", name: "LM Studio", url: "http://127.0.0.1:1234/v1", blurb: "Free, on this PC. An app: download a model in its Discover tab, then turn on the local server (Developer tab)." },
  { id: "ollama", name: "Ollama", url: "http://127.0.0.1:11434/v1", blurb: "Free, on this PC. Pick and download models in the Ollama app, then leave it running." },
];

/** Which AI plans, directs, choreographs and reviews: OpenAI, or a local model via Ollama / LM Studio. */
function BrainPanel({ openaiKey, anthropicKey, openrouterKey, googleKey }: { openaiKey: boolean; anthropicKey: boolean; openrouterKey: boolean; googleKey: boolean }) {
  const [b, setB] = useState<Brain | null>(null);
  const [models, setModels] = useState<string[]>([]);
  const [vision, setVision] = useState<string[]>([]);
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState("");
  const [prices, setPrices] = useState<Record<string, { in: number; out: number }>>({});
  const [structured, setStructured] = useState<string[]>([]);
  const [filter, setFilter] = useState("");
  useEffect(() => { api.aiBrain<Brain>("get").then(setB).catch(() => {}); }, []);
  if (!b) return null;
  const routed = b.provider === "openrouter";
  const local = b.provider !== "openai";
  const pick = (id: Brain["provider"]) => { setB({ ...b, provider: id, base_url: BRAINS.find((x) => x.id === id)!.url, model: id === b.provider ? b.model : "", vision_model: id === b.provider ? b.vision_model : "" });
    setModels([]); setMsg(""); setErr(""); if (id === "openai") save({ ...b, provider: "openai" }); };
  const find = async () => {
    setBusy("Looking…"); setErr(""); setMsg("");
    try {
      const r = await api.aiBrain<{ base_url: string; models: string[]; vision_capable: string[]; prices?: Record<string, { in: number; out: number }>; structured?: string[] }>("models", { provider: b.provider, base_url: b.base_url });
      setModels(r.models); setVision(r.vision_capable); setPrices(r.prices ?? {}); setStructured(r.structured ?? []);
      if (!r.models.length) setErr(routed ? "OpenRouter sent no models. Try again in a minute." : "The server is running but has no models yet. Download one first.");
      setB({ ...b, base_url: r.base_url, model: routed ? routedDefault(b.model, r.models, r.structured ?? []) : planningDefault(b.model, r.models, r.vision_capable),
             vision_model: r.models.includes(b.vision_model) ? b.vision_model : routed ? routedVision(r.vision_capable) : r.vision_capable[0] ?? "" });
    } catch (e) { setErr(errorText(e)); } finally { setBusy(""); }
  };
  const save = async (next: Brain = b) => {
    setErr("");
    try { setB(await api.aiBrain<Brain>("set", next)); window.dispatchEvent(new Event("pf-keys-changed")); setMsg(next.provider === "openai" ? "Using OpenAI." : "Saved."); }
    catch (e) { setErr(errorText(e)); }
  };
  const test = async () => {
    setBusy("Testing…"); setErr(""); setMsg("");
    try {
      await api.aiBrain<Brain>("set", b);
      const r = await api.aiBrain<{ model: string; seconds: number; sample: { shot: string; energy: number } }>("test", {});
      setMsg(`Works: ${r.model} answered in ${r.seconds}s: “${r.sample.shot}” (energy ${r.sample.energy}).`);
    } catch (e) { setErr(errorText(e)); } finally { setBusy(""); }
  };
  return (
    <div className="field brain-panel">
      <label style={{ display: "flex", justifyContent: "space-between" }}>
        <span>AI brain <span className="opt">Writes suggestions and checks pictures · pictures and video still come from Kie / fal / Google</span></span>
        <span className="status-ok">{BRAINS.find((x) => x.id === b.provider)!.name}{local && b.model ? ` · ${b.model}` : ""}</span>
      </label>
      <div className="seg" role="radiogroup" aria-label="AI brain" style={{ marginBottom: 8 }}>
        {BRAINS.map((x) => <button key={x.id} role="radio" aria-checked={b.provider === x.id} className={b.provider === x.id ? "on" : ""} onClick={() => pick(x.id)}>
          {x.name}{x.id === "openai" && !openaiKey && <span className="dim"> · no key</span>}{x.id === "anthropic" && !anthropicKey && <span className="dim"> · no key</span>}{x.id === "openrouter" && !openrouterKey && <span className="dim"> · no key</span>}{x.id === "gemini" && !googleKey && <span className="dim"> · no key</span>}</button>)}
      </div>
      <p className="dim" style={{ margin: "0 0 8px", fontSize: 12.5 }}>{BRAINS.find((x) => x.id === b.provider)!.blurb}</p>
      {local && <>
        <div className="key-row">
          {routed ? <span className="dim" style={{ flex: 1, alignSelf: "center" }}>Models and prices come from openrouter.ai (public list, no key needed to look).</span>
            : <input className="text-input" aria-label="Server address" value={b.base_url} onChange={(e) => setB({ ...b, base_url: e.target.value })} spellCheck={false} />}
          <button className="btn" onClick={find} disabled={!!busy}>{busy === "Looking…" ? busy : routed ? "Find models and prices" : "Find models"}</button>
        </div>
        {routed && !openrouterKey && <p className="mp-warn" role="note">Add your OpenRouter key under Connections above, then press Test.</p>}
        {b.provider === "anthropic" && !anthropicKey && <p className="mp-warn" role="note">Add your Anthropic Claude API key under Connections above, then press Test.</p>}
        {b.provider === "gemini" && !googleKey && <p className="mp-warn" role="note">Add your Google Gemini key under Connections above, then press Test.</p>}
        {routed && models.length > 0 && <input className="text-input" aria-label="Search models" placeholder="Search models, for example gemini, deepseek, qwen" value={filter} onChange={(e) => setFilter(e.target.value)} style={{ marginTop: 8 }} />}
        {(models.length > 0 || b.model) && <div className="brain-models">
          <label className="wiz-label" htmlFor="brain-model">Model for planning and direction</label>
          <select id="brain-model" className="text-input" value={b.model} onChange={(e) => setB({ ...b, model: e.target.value })}>
            {[...new Set([b.model, ...models])].filter(Boolean).filter((m) => m === b.model || !filter || m.toLowerCase().includes(filter.toLowerCase())).map((m) => <option key={m} value={m}>{routed ? `${m}  ·  ${priceLabel(prices[m])}${structured.length && !structured.includes(m) ? "  ·  may not return clean JSON" : ""}` : m}</option>)}
          </select>
          {routed && prices[b.model] && <p className="dim" style={{ fontSize: 12, margin: "4px 0 0" }}>{priceLabel(prices[b.model])}. A whole project plan is roughly 20,000 tokens in and 10,000 out: about {planCost(prices[b.model])}.</p>}
          <label className="wiz-label" htmlFor="brain-vision" style={{ marginTop: 8 }}>Model for reviewing takes (must see images)</label>
          <select id="brain-vision" className="text-input" value={b.vision_model} onChange={(e) => setB({ ...b, vision_model: e.target.value })}>
            <option value="">None: skip the visual review</option>
            {[...new Set([b.vision_model, ...vision, ...(routed ? [] : models)])].filter(Boolean).filter((m) => m === b.vision_model || !filter || m.toLowerCase().includes(filter.toLowerCase())).map((m) => <option key={m} value={m}>{m}{routed && prices[m] ? `  ·  ${priceLabel(prices[m])}` : ""}{vision.includes(m) ? " · sees images" : ""}</option>)}
          </select>
        </div>}
        <div className="wiz-row" style={{ marginTop: 8 }}>
          <button className="btn primary" onClick={() => save()} disabled={!b.model || !!busy}>Use this model</button>
          <button className="btn" onClick={test} disabled={!b.model || !!busy}>{busy === "Testing…" ? busy : "Test"}</button>
        </div>
        {routed ? <p className="dim" style={{ fontSize: 12, marginTop: 6 }}>Good cheap starting points: <b>google/gemini-2.5-flash</b> (sees images too), <b>deepseek/deepseek-chat-v3.1</b> or <b>openai/gpt-4.1-mini</b> for planning. Models marked “may not return clean JSON” can fail on the Director's structured plans; the Test button tells you before you spend anything real.</p> : b.provider === "gemini" ? <p className="dim" style={{ fontSize: 12, marginTop: 6 }}>Choose a Gemini model that supports structured JSON. The Test button makes one small text request before you rely on it.</p> : <p className="dim" style={{ fontSize: 12, marginTop: 6 }}>For a 12 GB graphics card, good choices: <b>qwen2.5 14B</b> or <b>qwen3 14B</b> for planning,
          <b> gemma3 12B</b> (also sees images) or <b>llava</b> for reviews. DeepSeek-R1 14B works but thinks slowly. Local models are free and private,
          but plans are simpler than GPT-5’s; you can switch back any time.</p>}
      </>}
      {msg && <div className="status-ok" style={{ marginTop: 6 }}>{msg}</div>}
      {err && <div className="error-text">{err}</div>}
    </div>
  );
}

/** Planning model: keep a valid choice; else the best text model (vision models are usually weaker planners). */
/** OpenRouter's price of a model as words: "$0.15 in / $0.60 out per million tokens", or "free". */
export function priceLabel(p?: { in: number; out: number }): string {
  if (!p) return "price unknown";
  if (p.in === 0 && p.out === 0) return "free";
  const f = (n: number) => `$${n < 1 ? n.toFixed(2) : n.toFixed(n < 10 ? 2 : 1)}`;
  return `${f(p.in)} in / ${f(p.out)} out per million tokens`;
}

/** What one whole plan costs on a model, in words (20,000 tokens in, 10,000 out). */
export function planCost(p: { in: number; out: number }): string {
  const usd = (20_000 * p.in + 10_000 * p.out) / 1e6;
  return usd === 0 ? "nothing" : usd < 0.01 ? "less than 1 cent" : `${Math.round(usd * 100) / 100 < 1 ? Math.round(usd * 100) + " cents" : "$" + usd.toFixed(2)}`;
}

const ROUTED_FAVOURITES = ["google/gemini-2.5-flash", "openai/gpt-4.1-mini", "deepseek/deepseek-chat-v3.1", "deepseek/deepseek-chat", "qwen/qwen3-235b-a22b", "anthropic/claude-sonnet-4"];

/** The model to start with on OpenRouter: the one already chosen if it is still listed, else a well-liked cheap one that can answer in JSON, else the cheapest that can. */
export function routedDefault(current: string, models: string[], structured: string[]): string {
  if (current && models.includes(current)) return current;
  const ok = structured.length ? structured : models;
  return ROUTED_FAVOURITES.find((m) => ok.includes(m)) ?? ok[0] ?? "";
}

/** The model that looks at pictures for take review on OpenRouter: a well-liked cheap one if it sees images, else the cheapest that does. */
export function routedVision(vision: string[]): string {
  return ROUTED_FAVOURITES.find((m) => vision.includes(m)) ?? vision[0] ?? "";
}

export function planningDefault(current: string, models: string[], vision: string[]): string {
  if (current && models.includes(current) && !vision.includes(current)) return current;
  const text = models.filter((m) => !vision.includes(m) && !/embed|whisper|tts|rerank/i.test(m));
  const rank = (m: string) => {
    const size = Number((m.match(/(\d+(?:\.\d+)?)\s*b/i) ?? [])[1] ?? 7);
    const family = /qwen3|qwen2\.5|llama3\.[13]|mistral-small|gpt-oss|deepseek/i.test(m) ? 100 : 0;
    const reasoning = /deepseek-r1|qwq/i.test(m) ? -20 : 0;   // slow thinkers: fine, but not first choice
    return family + reasoning + Math.min(size, 32);
  };
  return [...text].sort((a, b) => rank(b) - rank(a))[0] ?? (current && models.includes(current) ? current : models[0] ?? "");
}

/** Interface size for large screens and TVs. */
function InterfaceSize() {
  const [v, setV] = useState(savedScale());
  const [now, setNow] = useState<number | null>(null);
  return (
    <div className="field">
      <label htmlFor="ui-scale">Interface size <span className="dim">(for large screens and TVs)</span></label>
      <div className="wiz-row">
        <select id="ui-scale" className="text-input" style={{ maxWidth: 280 }} value={v}
                onChange={async (e) => { setV(e.target.value); setNow(await setScale(e.target.value)); }}>
          {UI_SCALES.map((s) => <option key={s.id} value={s.id}>{s.label}</option>)}
        </select>
        {now !== null && <span className="dim">Now {Math.round(now * 100)}%</span>}
      </div>
    </div>
  );
}
