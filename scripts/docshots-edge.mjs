// Regenerates screenshots of the screens built since the old preview data (mock-data) went missing, from the screenshot harness (src/docshots, docshots.html).
// It needs only Edge or Chrome and Node 22 or newer (it talks to the browser over the DevTools protocol; no packages). Nothing is sent anywhere and no real project is read.
//
//   npm run dev                                  (the preview must be on http://localhost:1420)
//   node scripts/docshots-edge.mjs               (every scene)       node scripts/docshots-edge.mjs review kt   (just those)
//   PF_OUT=<folder> node scripts/docshots-edge.mjs ...              (keep a run out of docs/img)
//
// Each scene is opened in a tall window; the harness writes "width,height" of what it drew into the page title; the window is then set to exactly that size and photographed.
// Add a scene to src/docshots/main.tsx, add a line below, and reference docs/img/<file> in docs/GETTING_STARTED.md.
import { spawn } from "node:child_process";
import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const OUT = process.env.PF_OUT || join(ROOT, "docs", "img");
const BASE = process.env.PF_URL || "http://localhost:1420/docshots.html";
const PORT = 9344;
const BROWSERS = [
  "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe", "C:/Program Files/Microsoft/Edge/Application/msedge.exe",
  "C:/Program Files/Google/Chrome/Application/chrome.exe", "C:/Program Files (x86)/Google/Chrome/Application/chrome.exe",
  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", "/usr/bin/google-chrome", "/usr/bin/chromium",
];

// name: [file, query]
const SCENES = {
  review: ["review.png", "scene=review"],
  placeset: ["place-set.png", "scene=cast&h=1100&clickcss=.cw-tabs button:nth-child(3)"],
  placesetmade: ["place-set-made.png", "scene=cast&h=1100&placestate=made&clickcss=.cw-tabs button:nth-child(3)&click=Look from the camera"],
  sets: ["sets.png", "scene=sets3d&select=ws-13f194cb"],
  directorcam: ["directorcam.png", "scene=directorcam&select=" + "ws-98967489"],
  cutouts: ["cutouts.png", "scene=cutouts"],
  sets3d: ["sets-3d.png", "scene=sets3d&select=ws-13f194cb&click=zzz&click=3D"],
  sets3dviews: ["sets-3d-views.png", "scene=sets3d&select=ws-13f194cb&click=zzz&click=3D&click=See it from four sides&click=Check for collisions"],
  queue: ["queue.png", "scene=queue"],
  retry: ["queue-retry.png", "scene=retry&click=Try a cheaper model"],
  kt: ["keyframetools.png", "scene=keyframetools"],
  handfix: ["handfix.png", "scene=handfix&drag=0.40,0.48,0.62,0.86"],
  budget: ["planbudget.png", "scene=planbudget"],
  select: ["selectreview.png", "scene=selectreview"],
  bigselect: ["big-select.png", "scene=selectreview&n=300"],
  bigmake: ["big-make.png", "scene=make&n=300"],
  bigshots: ["big-shots.png", "scene=shots&n=300"],
  selectzoom: ["selectpreview.png", "scene=selectreview&clickcss=.sr2-zoom"],
  compare: ["comparetakes.png", "scene=compare"],
  dirlib: ["directionlib.png", "scene=directionlibrary&clickcss=.dl-card:nth-child(2)"],
  looks: ["looks.png", "scene=looks"],
  lighting: ["lighting.png", "scene=lighting&clickcss=.lt-run:nth-of-type(3) > summary"],
  cleanup: ["cleanup.png", "scene=cleanup"],
  models: ["modelchoice.png", "scene=modelchoice"],
  modelpicker: ["modelpicker.png", "scene=modelpicker"],
  home: ["home.png", "scene=home"],
  newfilm: ["newfilm.png", "scene=newfilm"],
  newfilmwrite: ["newfilm-story.png", "scene=newfilmwrite"],
  film: ["film.png", "scene=film"],
  cast: ["cast.png", "scene=cast"],
  castsound: ["cast-sound.png", "scene=cast&clickcss=.cw-tabs button:nth-child(5)"],
  soundfx: ["cast-sound-effects.png", "scene=cast&clickcss=.cw-tabs button:nth-child(5)&click=Sound effects"],
  soundscene: ["cast-sound-scene.png", "scene=cast&clickcss=.cw-tabs button:nth-child(5)&click=Scene sound"],
  soundstyle: ["cast-sound-style.png", "scene=cast&clickcss=.cw-tabs button:nth-child(5)&click=Sound style"],
  dirliball: ["directionlib-all.png", "scene=directionlibrary&click=All"],
  shots: ["shots.png", "scene=shots"],
  make: ["make.png", "scene=make"],
  studio: ["studio.png", "scene=studio&click=zzz&click=OK"],
  soundplan: ["film/sound-plan.png", "scene=soundplan"],
  ready: ["film/ready.png", "scene=ready"],
  timing: ["film/dialogue-timing.png", "scene=soundplan&click=When each voice falls"],
  pacing: ["film/pacing.png", "scene=pacing"],
  givenmodel: ["film/given-to-model.png", "scene=givenmodel"],
  givenhidden: ["film/given-to-model-hidden.png", "scene=givenmodel&click=Hide pictures"],
  shotcamera: ["shots-camera.png", "scene=shots&click=Camera"],
  export: ["export.png", "scene=export"],
  continuity: ["continuity.png", "scene=continuity"],
  assist: ["assist.png", "scene=assist"],
  shotsuggest: ["shot-suggestions.png", "scene=shotsuggest"],
  studioshot: ["studio-shot.png", "scene=studio&clickcss=.shot-card.story&click=zzz&click=OK"],
  studioadvanced: ["studio-advanced.png", "scene=studio&clickcss=.shot-card.story&click=zzz&click=Advanced&click=OK"],
  shotacting: ["shots-acting.png", "scene=shots&click=Acting"],
  studiovoice: ["studio-voice.png", "scene=studiovoice"],
  voice: ["voiceover.png", "scene=shots&click=Voiceover"],
  shotvoice: ["shot-voice.png", "scene=shotvoice&clickcss=.sl-tabs button:nth-child(6)"],
  shotblocking: ["shots-blocking.png", "scene=shots&click=Blocking"],
  bible: ["bible.png", "scene=cast&click=Rules %26 style"],
  principles: ["principles.png", "scene=cast&click=Rules %26 style&h=1500"],
  library: ["library.png", "scene=library"],
  supervisor: ["supervisor.png", "scene=supervisor"],
  acting: ["acting.png", "scene=acting"],
  layers: ["layers.png", "scene=layers"],
  lanes: ["layerlanes.png", "scene=layerlanes"],
  colourmatch: ["colourmatch.png", "scene=colourmatch"],
  compose: ["compose.png", "scene=compose"],
  motionlib: ["motionlibrary.png", "scene=compose&click=Motion"],
};

const browser = BROWSERS.find((p) => existsSync(p));
if (!browser) { console.error("No Edge or Chrome found."); process.exit(1); }
try { await fetch(BASE); } catch { console.error(`The preview isn't running on ${BASE.split("/docshots")[0]}. Start it with: npm run dev`); process.exit(1); }
mkdirSync(OUT, { recursive: true });

const profile = mkdtempSync(join(tmpdir(), "pf-shots-"));
const proc = spawn(browser, ["--headless=new", "--disable-gpu", "--hide-scrollbars", `--remote-debugging-port=${PORT}`, `--user-data-dir=${profile}`, "--no-first-run", "--autoplay-policy=no-user-gesture-required", "about:blank"], { stdio: "ignore" });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const cleanup = () => { try { proc.kill(); } catch { /* already gone */ } setTimeout(() => { try { rmSync(profile, { recursive: true, force: true }); } catch { /* still in use: the system clears it */ } }, 800); };
process.on("exit", cleanup);

let wsUrl = null;
for (let i = 0; i < 60 && !wsUrl; i++) {
  try { const list = await (await fetch(`http://127.0.0.1:${PORT}/json/list`)).json(); wsUrl = list.find((t) => t.type === "page")?.webSocketDebuggerUrl ?? null; } catch { /* not up yet */ }
  if (!wsUrl) await sleep(250);
}
if (!wsUrl) { console.error("Couldn't reach the browser."); cleanup(); process.exit(1); }
const ws = new WebSocket(wsUrl);
await new Promise((res, rej) => { ws.onopen = res; ws.onerror = rej; });
let id = 0;
const pending = new Map();
const problems = [];                                                       // PF_QA=1: console errors and uncaught exceptions, per scene
ws.onmessage = (m) => {
  const d = JSON.parse(m.data);
  if (d.id && pending.has(d.id)) { pending.get(d.id)(d); pending.delete(d.id); return; }
  if (d.method === "Runtime.exceptionThrown") problems.push("exception: " + String(d.params.exceptionDetails?.exception?.description ?? d.params.exceptionDetails?.text).split("\n")[0]);
  else if (d.method === "Runtime.consoleAPICalled" && d.params.type === "error") problems.push("console.error: " + d.params.args.map((a) => a.value ?? a.description ?? "").join(" ").slice(0, 200));
};
const send = (method, params = {}) => new Promise((res) => { const n = ++id; pending.set(n, res); ws.send(JSON.stringify({ id: n, method, params })); });
const evalJs = async (expression) => (await send("Runtime.evaluate", { expression, returnByValue: true })).result?.result?.value;

const names = process.argv.slice(2).length ? process.argv.slice(2) : Object.keys(SCENES);
await send("Page.enable");
if (process.env.PF_QA) await send("Runtime.enable");
let bad = 0;
let axeSource = null;
const a11y = {};
for (const name of names) {
  const spec = SCENES[name];
  if (!spec) { console.error(`unknown scene: ${name} (try: ${Object.keys(SCENES).join(", ")})`); continue; }
  const [file, query] = spec;
  try {
    await send("Emulation.setDeviceMetricsOverride", { width: 1400, height: 2400, deviceScaleFactor: 1, mobile: false });
    await send("Page.navigate", { url: `${BASE}?${query.replace(/ /g, "%20")}` });
    let size = null;
    for (let i = 0; i < 80 && !size; i++) { await sleep(250); const t = await evalJs("document.title"); if (/^\d+,\d+$/.test(t ?? "")) size = t.split(",").map(Number); }
    if (!size) { console.error(`${name}: the screen never reported its size`); continue; }
    if (process.env.PF_PERF) {                                                    // PF_PERF=1: how long the screen took to appear, and how big it is
      const m = await evalJs("JSON.stringify({ nodes: document.querySelectorAll('*').length, heapMB: Math.round((performance.memory ? performance.memory.usedJSHeapSize : 0) / 1048576), ms: Math.round(performance.now()) })");
      console.log(`   perf ${name}: ${m}`);
    }
    let [w, h] = [Math.min(1500, size[0] === 1440 ? 1440 : size[0]), Math.min(3400, size[1])];
    if (process.env.PF_WIDTH) w = Number(process.env.PF_WIDTH);                    // PF_WIDTH=1000: photograph (and check) the screen in a narrower window
    await send("Emulation.setDeviceMetricsOverride", { width: w, height: h, deviceScaleFactor: 1, mobile: false });
    await sleep(700);
    if (process.env.PF_A11Y) {                                                    // PF_A11Y=1: run axe-core (WCAG 2.1 A and AA) on this screen and report what it finds
      if (!axeSource) axeSource = readFileSync(join(ROOT, "node_modules", "axe-core", "axe.min.js"), "utf8");
      await evalJs(axeSource);
      const res = await send("Runtime.evaluate", { expression: "axe.run(document, { runOnly: { type: 'tag', values: ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'] } }).then(r => JSON.stringify(r.violations.map(v => ({ id: v.id, impact: v.impact, help: v.help, nodes: v.nodes.length, first: v.nodes[0] && v.nodes[0].target.join(' '), html: v.nodes[0] && v.nodes[0].html.slice(0, 140) }))))", awaitPromise: true, returnByValue: true });
      const found = JSON.parse(res.result?.result?.value ?? "[]");
      a11y[name] = found;
      for (const v of found) console.log(`   a11y ${v.impact.padEnd(8)} ${v.id}: ${v.help} (${v.nodes} node${v.nodes === 1 ? "" : "s"}) ${v.first ?? ""}`);
    }
    if (process.env.PF_OVERFLOW) {                                                // PF_OVERFLOW=1: anything pushed outside the window, or the page scrolling sideways
      const res = await send("Runtime.evaluate", { expression: `(() => { const W = document.documentElement.clientWidth; const out = [];
        const scrolls = (el) => { for (let p = el.parentElement; p && p !== document.body; p = p.parentElement) { const o = getComputedStyle(p).overflowX; if (o === "auto" || o === "scroll" || o === "hidden") return true; } return false; };
        for (const el of document.querySelectorAll("body *")) { const r = el.getBoundingClientRect(); if (r.width === 0 || r.height === 0) continue; const cs = getComputedStyle(el); if (cs.position === "fixed" && r.right <= W + 1) continue;
          if ((r.right > W + 2 || r.left < -2) && !scrolls(el) && cs.visibility !== "hidden" && !el.closest("svg")) out.push((el.className && el.className.baseVal === undefined ? "." + String(el.className).split(" ")[0] : el.tagName.toLowerCase()) + " " + Math.round(r.left) + ".." + Math.round(r.right)); }
        return JSON.stringify({ W, sideways: document.documentElement.scrollWidth > W + 1, n: out.length, first: [...new Set(out)].slice(0, 6) }); })()`, returnByValue: true });
      const o = JSON.parse(res.result?.result?.value ?? "{}");
      if (o.sideways || o.n) { bad++; console.log(`   !! overflow at ${o.W}px: ${o.sideways ? "page scrolls sideways; " : ""}${o.n} element(s) outside the window: ${(o.first ?? []).join(", ")}`); }
    }
    const shot = await send("Page.captureScreenshot", { format: "png", captureBeyondViewport: false });
    writeFileSync(join(OUT, file), Buffer.from(shot.result.data, "base64"));
    console.log(`${name.padEnd(11)} ${w}x${h}  ${file}`);
    if (process.env.PF_QA) { const mine = [...new Set(problems.splice(0))].filter((p) => !/createRoot\(\)/.test(p)); bad += mine.length; for (const p of mine) console.log("   !! " + p); }
  } catch (e) { console.error(`${name}: ${String(e.message ?? e).split("\n")[0]}`); }
}
if (process.env.PF_A11Y) {
  writeFileSync(join(OUT, "a11y.json"), JSON.stringify(a11y, null, 1));
  const all = Object.values(a11y).flat();
  console.log(`\naccessibility: ${all.length} finding(s) in ${Object.values(a11y).filter((x) => x.length).length} of ${Object.keys(a11y).length} screens (details in ${join(OUT, "a11y.json")})`);
  process.exitCode = all.length ? 1 : 0;
}
ws.close();
cleanup();
if (process.env.PF_QA) { console.log(bad ? `\n${bad} problem(s) found.` : "\nNo console errors or exceptions in any scene."); process.exitCode = bad ? 1 : 0; }
