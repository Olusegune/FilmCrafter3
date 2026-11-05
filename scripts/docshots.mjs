// Regenerates the screenshots in docs/img from the app's browser preview (sample data, no engine, nothing is sent anywhere).
//
//   npm run dev                      (in another terminal; the preview must be on http://localhost:1420)
//   node scripts/docshots.mjs        (all screenshots)   or   node scripts/docshots.mjs sound shortcuts   (just those)
//
// It drives Chrome (or Edge) in headless mode over the DevTools protocol, so it needs no extra packages. Each shot below is a name and the clicks
// that get the preview to that screen; add one to cover a new screen, then reference it in docs/GETTING_STARTED.md as ![what it shows](img/name.png).
import { spawn } from "node:child_process";
import { existsSync, mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, dirname } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const OUT = process.env.PF_OUT || join(ROOT, "docs", "img");          // PF_OUT=<folder> keeps a run (an audit, say) out of the guide's pictures
const URL = process.env.PF_URL || "http://localhost:1420/?mock";
const PORT = 9333;
const BROWSERS = [
  "C:/Program Files/Google/Chrome/Application/chrome.exe", "C:/Program Files (x86)/Google/Chrome/Application/chrome.exe",
  "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe", "C:/Program Files/Microsoft/Edge/Application/msedge.exe",
  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", "/usr/bin/google-chrome", "/usr/bin/chromium",
];

// ---- what each screenshot needs done first (runs inside the page) -------------------------------------------------------------------------------
const wait = (ms) => `await new Promise((r) => setTimeout(r, ${ms}));`;
const click = (sel, text) => `{ const el = [...document.querySelectorAll(${JSON.stringify(sel)})].find((e) => ${text ? `e.textContent.trim() === ${JSON.stringify(text)}` : "true"}); if (!el) throw new Error("not found: " + ${JSON.stringify(sel + " " + (text || ""))}); el.click(); } ${wait(700)}`;
const openStudio = `${wait(2500)} { const el = [...document.querySelectorAll("*")].find((e) => e.children.length === 0 && e.textContent === "Exit Plan"); if (!el) throw new Error("sample project not found"); el.click(); } ${wait(3500)}
  [...document.querySelectorAll("button")].find((b) => b.textContent === "Skip")?.click(); ${wait(500)}`;
const pickShot = (n) => `{ const c = [...document.querySelectorAll(".shot-card")].find((e) => e.textContent.includes(${JSON.stringify(n)})); if (!c) throw new Error("shot not found"); c.click(); } ${wait(1200)}`;
const rail = (label) => `{ const find = () => [...document.querySelectorAll(".rail button")].find((x) => x.textContent.trim().startsWith(${JSON.stringify(label)})); let b = find(); if (!b) { const more = [...document.querySelectorAll(".rail button")].find((x) => x.textContent.trim() === "More"); if (more) more.click(); } await new Promise((r) => setTimeout(r, 300)); b = find(); if (!b) throw new Error("rail button not found: ${label}"); b.click(); } ${wait(1500)}`;
const home = (text) => `${wait(2500)} { const b = [...document.querySelectorAll("button, a")].find((x) => x.textContent.trim().includes(${JSON.stringify(text)})); if (!b) throw new Error("not found: ${text}"); b.click(); } ${wait(2500)}`;
const tab = (t) => `${click("[role=tab]", t)}`;
const scrollTo = (sel) => `document.querySelector(${JSON.stringify(sel)}).scrollIntoView({ block: "center" }); ${wait(500)}`;

export const SHOTS = {
  // `page` shots use the screenshot harness (docshots.html?scene=...), which carries its own sample data, so they need no private mock-data folder
  fidelity: { page: "docshots.html?scene=fidelity", steps: wait(2800), clip: ".sheet", alt: "Picture quality: what was measured, and the free local choices" },
  finish: { height: 1800, page: "docshots.html?scene=exportsheet", steps: `${wait(2800)} document.querySelector(".fin-panel summary").click(); ${wait(400)} [...document.querySelectorAll("button")].find((b) => b.textContent === "Check for flicker").click(); ${wait(900)} document.querySelector(".fin-panel").scrollIntoView({ block: "start" }); ${wait(300)}`, clip: ".fin-panel", alt: "Finish and deliver: flicker check, a calmer copy, delivery profiles" },
  home: { steps: `${wait(2500)}`, alt: "The Home screen" },
  studio: { steps: `${openStudio} ${pickShot("01-04")}`, alt: "The Studio: player, shots on the song's timeline, and the inspector" },
  shortcuts: { steps: `${openStudio} window.dispatchEvent(new KeyboardEvent("keydown", { key: "?", shiftKey: true })); ${wait(700)}`, alt: "The keyboard shortcuts list (press ?)" },
  // screens that are not in the guide yet; used by the audit (PF_OUT=... node scripts/docshots.mjs export review ...)
  export: { steps: `${openStudio} ${rail("Export")}`, alt: "The Export sheet" },
  review: { steps: `${openStudio} ${rail("Review")}`, alt: "Production review" },
  settings: { steps: `${openStudio} ${rail("Settings")}`, alt: "Settings" },
  library: { steps: `${openStudio} ${rail("Library")}`, alt: "The reference library" },
  supervisor: { steps: `${openStudio} ${rail("Supervisor")}`, alt: "The Supervisor" },
  acting: { steps: `${openStudio} ${rail("Acting")}`, alt: "Acting" },
  continuity: { steps: `${openStudio} ${rail("Continuity")}`, alt: "Continuity" },
  colour: { steps: `${openStudio} ${rail("Colour")}`, alt: "Colour match" },
  clean: { steps: `${openStudio} ${rail("Clean")}`, alt: "Clean up" },
  directions: { steps: `${openStudio} ${rail("Directions")}`, alt: "Directions" },
  select: { steps: `${openStudio} ${click("button", "Select & review")}`, alt: "Select and review" },
  wizard: { steps: home("New Project"), alt: "The new-project wizard" },
  produce: { steps: home("Create from song"), alt: "Create from song" },
  show: { steps: home("New show"), alt: "New show" },
  makesong: { steps: home("Make a song"), alt: "Make a song" },
  docs: { steps: home("Documentation"), alt: "The in-app documentation" },
  ladder: { steps: `${openStudio} ${pickShot("01-04")} ${tab("Video")} document.querySelector("details.upgrade > summary").click(); ${wait(500)} ${scrollTo("details.upgrade")} { const b = [...document.querySelectorAll(".up-list button")].find((x) => x.textContent.includes("Kling")); if (!b) throw new Error("ladder row not found"); b.click(); } ${wait(900)}`, clip: "details.upgrade", alt: "The Quality ladder: prices per typical 5-second shot, and the price of this shot for the model picked" },
  shotacting: { steps: `${openStudio} ${pickShot("01-04")} ${tab("Shot")} ${scrollTo(".perf-dance-label")}`, clip: "section.panel:has(.perf-dance-label)", alt: "A shot's Acting panel: acting style, and dance direction for this shot" },
  beats: { steps: `${openStudio} ${pickShot("01-04")} ${tab("Shot")} ${scrollTo(".beats-panel")}`, clip: ".beats-panel", alt: "A shot's acting beats: what the person does, moment by moment" },
  arcs: { steps: `${openStudio} ${rail("Acting")} ${wait(600)} { const d = document.querySelector(".arc-char"); if (d) d.open = true; document.querySelector(".arc-view").scrollIntoView({ block: "center" }); } ${wait(500)}`, clip: ".perf-sheet", alt: "The Acting sheet: emotional arcs across the song, and signature gestures" },
  directionlib: { steps: `${openStudio} window.dispatchEvent(new Event("pf-open-directions")); ${wait(1800)}`, clip: ".sheet", alt: "The Direction library: each tradition has a picture, a summary, its palette and why it fits the song" },
  queue: { steps: `${openStudio} { const b = document.querySelector(".queue-chip"); if (!b) throw new Error("no queue chip"); b.click(); } ${wait(900)}`, clip: ".queue-sheet", alt: "The render queue: what is rendering, how far along, what is waiting, and what failed" },
  reviewbanner: { steps: `${openStudio} { const b = [...document.querySelectorAll("button")].find((x) => x.textContent.trim().startsWith("Review")); if (!b) throw new Error("no Review button"); b.click(); } ${wait(1200)}`, clip: ".review-sheet", alt: "Review with new versions ready: swap them in one at a time or all at once, with the check result for each" },
  extend: { steps: `${openStudio} ${pickShot("01-04")} ${tab("Video")} ${scrollTo(".extend-card")} ${click(".extend-card button.btn.small")}`, clip: ".extend-card", alt: "Extend this take: what is missing, what extending does, the price first, and advice to set an end frame for a transformation" },
  compose: { steps: `${openStudio} ${pickShot("01-04")} { const b = document.querySelector('[role=tab][data-tab="frames"]'); if (!b) throw new Error("no compose tab"); b.click(); } ${wait(900)} { const m = [...document.querySelectorAll(".cp-modes button")].find((x) => x.textContent.includes("Motion")); if (!m) throw new Error("no motion mode"); m.click(); } ${wait(1200)}`, clip: ".inspector-body", alt: "Compose, Motion: a video of the movement and a picture of your character, with the model, direction and quality choices" },
  frames: { steps: `${openStudio} ${pickShot("01-04")} { const b = document.querySelector('[role=tab][data-tab="frames"]'); if (!b) throw new Error("no frames tab"); b.click(); } ${wait(1500)}`, clip: ".inspector-body", alt: "Compose, Start to End: two big slots, drop a picture from Midjourney on either side, then render start to end" },
  lighting: { steps: `${openStudio} ${rail("Lighting")} ${wait(1200)}`, clip: ".lighting-sheet", alt: "Light the story: the mood read in every shot and the light planned for it, with a strip of the whole film, apply and undo" },
  comfyinstall: { query: "nocomfy", steps: `${openStudio} ${rail("Settings")} { const b = [...document.querySelectorAll("button")].find((x) => x.textContent.includes("Install it for me")); if (!b) throw new Error("no install link"); b.click(); } ${wait(900)} ${scrollTo(".comfy-install")}`, clip: ".comfy-install", alt: "One-click ComfyUI: what is installed, from where, how big, where, and how to remove it, before anything is downloaded" },
  prompt: { steps: `${openStudio} ${pickShot("01-04")} { const b = document.querySelector('[role=tab][data-tab="frames"]'); b.click(); } ${wait(900)} { const m = [...document.querySelectorAll(".pp-choice button")].find((x) => x.textContent.includes("I'll write")); if (!m) throw new Error("no prompt choice"); m.click(); } ${wait(500)} { const h = [...document.querySelectorAll(".pp-tools button")].find((x) => x.textContent.includes("Write it for me")); h.click(); } ${wait(400)} { const ta = document.querySelector("#pp-intent"); const set = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value").set; set.call(ta, "little Sege is hugging older Sege, then a bright light comes out of older Sege's chest and little Sege disappears"); ta.dispatchEvent(new Event("input", { bubbles: true })); } ${wait(300)} { [...document.querySelectorAll(".pp-helper button")].find((x) => x.textContent.includes("Write the prompt")).click(); } ${wait(1500)} { const s = document.querySelector(".pp-sent summary"); s.click(); } ${wait(1200)} ${scrollTo("#pp-intent")}`, clip: ".inspector-body", alt: "The prompt for a take: write it yourself, get it written from plain words, use a recipe, see what could go wrong, and see exactly what will be sent" },
  motionlibrary: { steps: `${openStudio} ${pickShot("01-04")} { document.querySelector('[role=tab][data-tab="frames"]').click(); } ${wait(900)} { [...document.querySelectorAll(".cp-modes button")].find((x) => x.textContent.includes("Motion")).click(); } ${wait(1000)} ${wait(900)} { const l = document.querySelector(".cp-lib"); if (!l.open) l.querySelector("summary").click(); } ${wait(700)} ${scrollTo(".cp-lib")}`, clip: ".inspector-body", alt: "The motion library: saved motions with a picture, a name and a length, used on any shot of any project" },
  notimeline: { steps: `${openStudio} { document.querySelector('[aria-label="Hide the timeline"]').click(); } ${wait(900)}`, alt: "The timeline put away: the video gets the room, and a thin bar brings the timeline back (Ctrl+J)" },
  localai: { steps: `${openStudio} ${rail("Settings")} ${scrollTo(".local-models")}`, clip: ".local-models", alt: "Models on this computer: what your hardware can run, a fit mark on every model, and one-press tests" },
  openrouter: { steps: `${openStudio} ${rail("Settings")} { const r = [...document.querySelectorAll("[role=radio]")].find((x) => x.textContent.includes("OpenRouter")); if (!r) throw new Error("no OpenRouter choice"); r.click(); } ${wait(500)} { const b = [...document.querySelectorAll("button")].find((x) => x.textContent.includes("Find models and prices")); if (!b) throw new Error("no find button"); b.click(); } ${wait(900)} ${scrollTo(".brain-panel")}`, clip: ".brain-panel", alt: "OpenRouter as the AI brain: models with their prices, and what a whole plan costs" },
  upscale: { steps: `${openStudio} window.dispatchEvent(new CustomEvent("pf-open-upscale", { detail: { kind: "keyframe", shot: "S01-04" } })); ${wait(1200)}`, clip: ".up-sheet", alt: "Upscale a keyframe: Topaz or Recraft, 2x or 4x" },
  lanes: { steps: `${openStudio} ${pickShot("01-04")} ${wait(800)}`, clip: ".timeline", alt: "Layers as lanes above the shots on the timeline, with a handle at every cut for its transition" },
  transitions: { steps: `${openStudio} ${wait(800)} { const h = [...document.querySelectorAll(".tr-handle.set")][1]; if (!h) throw new Error("no transition handle"); h.click(); } ${wait(700)}`, clip: ".tr-pop", alt: "Choosing a transition for a cut, and how long it takes" },
  tour: { steps: `${wait(2500)} { const el = [...document.querySelectorAll("*")].find((e) => e.children.length === 0 && e.textContent === "Exit Plan"); if (!el) throw new Error("sample project not found"); el.click(); } ${wait(3500)}`, alt: "The welcome card on the first visit to the Studio" },
  palette: { steps: `${openStudio} window.dispatchEvent(new KeyboardEvent("keydown", { key: "P", ctrlKey: true, shiftKey: true })); ${wait(500)} { const i = document.querySelector(".palette input"); const set = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set; set.call(i, "lay"); i.dispatchEvent(new Event("input", { bubbles: true })); } ${wait(500)}`, alt: "The command palette (Ctrl+Shift+P), searching for an action" },
  layers: { steps: `${openStudio} ${click("button", "Layers")}`, alt: "The Layers panel with a text layer and a line" },
  sound: { steps: `${openStudio} ${pickShot("01-04")} ${tab("Video")} ${scrollTo(".shot-sound")} ${click(".shot-sound input[type=checkbox]:not(:checked)")}`, clip: ".inspector, aside.inspector, .shot-sound", alt: "The Sound section of a take: the song and the model's own sound as layers" },
  "sound-split": { steps: `${openStudio} ${pickShot("01-04")} ${tab("Video")} ${scrollTo(".shot-sound")} ${click(".shot-sound button", "Split voices from effects")}`, clip: ".shot-sound", alt: "After Split: voices and sound effects as separate layers" },
};

// ---- a very small DevTools client ---------------------------------------------------------------------------------------------------------------
export async function connect(port) {
  for (let i = 0; i < 60; i++) {
    try {
      const list = await (await fetch(`http://127.0.0.1:${port}/json`)).json();
      const page = list.find((t) => t.type === "page");
      if (page) return new Promise((res, rej) => {
        const ws = new WebSocket(page.webSocketDebuggerUrl);
        let id = 0; const pending = new Map();
        ws.onmessage = (m) => { const d = JSON.parse(m.data); if (d.id && pending.has(d.id)) { const { ok, bad } = pending.get(d.id); pending.delete(d.id); d.error ? bad(new Error(d.error.message)) : ok(d.result); } };
        ws.onerror = rej;
        ws.onopen = () => res({ send: (method, params = {}) => new Promise((ok, bad) => { const n = ++id; pending.set(n, { ok, bad }); ws.send(JSON.stringify({ id: n, method, params })); }), close: () => ws.close() });
      });
    } catch { /* the browser is still starting */ }
    await new Promise((r) => setTimeout(r, 250));
  }
  throw new Error("Could not reach the browser's debugging port.");
}

async function main() {
  const want = process.argv.slice(2);
  const names = want.length ? want : Object.keys(SHOTS);
  for (const n of names) if (!SHOTS[n]) throw new Error(`No screenshot called "${n}". Known: ${Object.keys(SHOTS).join(", ")}`);
  try { await fetch(URL.split("?")[0]); } catch { throw new Error(`The preview is not running at ${URL.split("?")[0]}. Start it with: npm run dev`); }
  const exe = process.env.PF_BROWSER || BROWSERS.find(existsSync);
  if (!exe) throw new Error("No Chrome or Edge found. Set PF_BROWSER to its path.");
  mkdirSync(OUT, { recursive: true });
  const profile = mkdtempSync(join(tmpdir(), "pf-docshots-"));
  const proc = spawn(exe, ["--headless=new", `--remote-debugging-port=${PORT}`, `--user-data-dir=${profile}`, "--hide-scrollbars", "--no-first-run", "--disable-gpu", "about:blank"], { stdio: "ignore" });
  try {
    const cdp = await connect(PORT);
    await cdp.send("Page.enable");
    for (const name of names) {
      const s = SHOTS[name];
      // a fresh page each time: the sample project, its welcome tour and the in-memory sound layers all start from scratch
      await cdp.send("Emulation.setDeviceMetricsOverride", { width: 1440, height: s.height || 900, deviceScaleFactor: 2, mobile: false });
      await cdp.send("Page.navigate", { url: s.page ? new globalThis.URL(s.page, URL).href : s.query ? `${URL}&${s.query}` : URL });
      await new Promise((r) => setTimeout(r, 1500));
      const hook = "window.__errs = []; { const oe = console.error; console.error = (...a) => { window.__errs.push(a.map(String).join(' ').slice(0, 300)); oe(...a); }; window.addEventListener('error', (e) => window.__errs.push(String(e.message))); }";
      const r = await cdp.send("Runtime.evaluate", { expression: `(async () => { ${hook} ${s.steps} return true; })()`, awaitPromise: true, returnByValue: true });
      if (r.exceptionDetails) throw new Error(`${name}: ${r.exceptionDetails.exception?.description || r.exceptionDetails.text}`);
      let clip;
      if (s.clip) {
        const box = await cdp.send("Runtime.evaluate", { returnByValue: true, expression: `(() => { const sels = ${JSON.stringify(s.clip.split(", "))}; const el = sels.map((q) => document.querySelector(q)).find(Boolean); if (!el) return null; const b = el.getBoundingClientRect(); return { x: b.x, y: b.y, width: b.width, height: b.height }; })()` });
        const b = box.result.value;
        if (b) { const pad = 12; clip = { x: Math.max(0, b.x - pad), y: Math.max(0, b.y - pad), width: Math.min(1440, b.width + pad * 2), height: Math.min(s.height || 900, b.height + pad * 2), scale: 1 }; }
      }
      const shot = await cdp.send("Page.captureScreenshot", { format: "png", ...(clip ? { clip } : {}) });
      writeFileSync(join(OUT, `${name}.png`), Buffer.from(shot.data, "base64"));
      const errs = (await cdp.send("Runtime.evaluate", { expression: "window.__errs", returnByValue: true })).result.value || [];
      for (const e of errs.slice(0, 3)) console.log(`  ! ${name}: the page logged an error: ${e.split(/\r?\n/)[0]}`);
      console.log(`wrote docs/img/${name}.png  (${s.alt})`);
    }
    cdp.close();
  } finally {
    proc.kill();
    setTimeout(() => { try { rmSync(profile, { recursive: true, force: true }); } catch { /* still in use: the temp folder is cleaned up later */ } }, 1500);
  }
}

// run directly, not when another script imports the helpers above
if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) main().catch((e) => { console.error(e.message); process.exit(1); });
