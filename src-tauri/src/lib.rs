//! FilmCrafter desktop core: projects on disk, OS keychain, and the analysis/director engine.
//!
//! The engine (Python) runs as a hidden background process; its JSON-line progress is
//! forwarded to the UI as `engine-progress` events. Provider keys live only in the OS
//! credential store and are handed to an engine process through its environment.

use serde_json::{json, Value};
use std::fs;
use std::io::{BufRead, BufReader, Read};
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
use tauri::{AppHandle, Emitter, Manager};

const KEY_SERVICE: &str = "filmcrafter";

// ---- S-01: the spend confirmation -------------------------------------------------------------------------------------------------------
// A billable batch is queued only with a token that the confirmation sheet's Confirm button obtained from `confirm_spend`. A token is
// random, single-use, short-lived and bound to one batch (project folder, provider, kind and the shots, sorted), so it cannot be reused
// for a different or bigger batch. It does not prove a human clicked (the UI is trusted code), but a screen that forgets to ask is
// refused here instead of charging, and a stray `invoke("queue_render")` cannot spend.
const SPEND_TTL: std::time::Duration = std::time::Duration::from_secs(120);
const SPEND_MAX_OPEN: usize = 64;

#[derive(Default)]
struct SpendLedger {
    open: Vec<(String, String, std::time::Instant)>,   // (token, batch key, issued)
}

impl SpendLedger {
    fn prune(&mut self, now: std::time::Instant) {
        self.open.retain(|(_, _, at)| now.saturating_duration_since(*at) < SPEND_TTL);
        if self.open.len() > SPEND_MAX_OPEN {
            let extra = self.open.len() - SPEND_MAX_OPEN;
            self.open.drain(..extra);
        }
    }
    fn mint(&mut self, token: String, key: String, now: std::time::Instant) -> String {
        self.prune(now);
        self.open.push((token.clone(), key, now));
        token
    }
    /// Spends the token (it is gone whether or not the rest of the queueing succeeds) when it exists, is fresh and was issued for this exact batch.
    fn redeem(&mut self, token: &str, key: &str, now: std::time::Instant) -> bool {
        self.prune(now);
        match self.open.iter().position(|(t, _, _)| t == token) {
            Some(i) => self.open.remove(i).1 == key,
            None => false,
        }
    }
}

static SPEND: std::sync::Mutex<SpendLedger> = std::sync::Mutex::new(SpendLedger { open: Vec::new() });

/// The batch a token is bound to. The shots are sorted, so the order a screen lists them in does not matter.
fn spend_key(dir: &str, provider: &str, kind: &str, shots: &[String]) -> String {
    let mut s: Vec<&str> = shots.iter().map(String::as_str).collect();
    s.sort_unstable();
    json!([dir, provider, kind, s]).to_string()
}

/// Local ComfyUI renders cost nothing, so they need no confirmation.
fn spend_free(provider: &str) -> bool {
    provider == "comfyui"
}

fn new_spend_token() -> Result<String, String> {
    let mut b = [0u8; 16];
    getrandom::fill(&mut b).map_err(|_| "The computer could not make a safe random number, so nothing was queued.".to_string())?;
    Ok(b.iter().map(|x| format!("{x:02x}")).collect())
}

fn redeem_spend(token: Option<&str>, dir: &str, provider: &str, kind: &str, shots: &[String]) -> Result<(), String> {
    if spend_free(provider) {
        return Ok(());
    }
    let key = spend_key(dir, provider, kind, shots);
    let ok = token.map(|t| SPEND.lock().map(|mut l| l.redeem(t, &key, std::time::Instant::now())).unwrap_or(false)).unwrap_or(false);
    if ok {
        Ok(())
    } else {
        Err("This render was not confirmed, or the confirmation ran out or was for a different batch. Nothing was queued: open the render sheet, check the price and confirm again.".into())
    }
}

/// Called by a confirmation sheet's Confirm button, just before it queues the batch it showed the price of. Returns a one-use token
/// (empty for free ComfyUI work) that `queue_render` (and applying an agent's render request) requires.
#[tauri::command]
fn confirm_spend(dir: String, shots: Vec<String>, provider: String, kind: Option<String>) -> Result<String, String> {
    let dir = project_dir(&dir)?.to_string_lossy().to_string();
    if spend_free(&provider) {
        return Ok(String::new());
    }
    let key = spend_key(&dir, &provider, &kind.unwrap_or_else(|| "video".into()), &shots);
    let token = new_spend_token()?;
    let mut l = SPEND.lock().map_err(|_| "Could not record the confirmation.".to_string())?;
    Ok(l.mint(token, key, std::time::Instant::now()))
}

const PROVIDERS: [&str; 8] = ["openai", "anthropic", "fal", "kie", "google", "elevenlabs", "openrouter", "byteplus"];

fn err<E: std::fmt::Display>(e: E) -> String {
    e.to_string()
}

/// A provider's name as the person knows it, for the message that asks for its key.
fn provider_name(provider: &str) -> &'static str {
    match provider {
        "fal" => "fal.ai",
        "kie" => "Kie.ai",
        "google" => "Google Gemini",
        "openai" => "OpenAI",
        "byteplus" => "BytePlus",
        _ => "provider",
    }
}

fn projects_root(app: &AppHandle) -> Result<PathBuf, String> {
    let dir = app.path().document_dir().map_err(err)?.join("FilmCrafter");
    fs::create_dir_all(&dir).map_err(err)?;
    Ok(dir)
}

/// Where the engine lives.
/// - Development: the repo's `analysis/` folder with its `.venv`.
/// - Installed app: engine code ships as app resources (`engine/`), and a private Python environment is
///   set up once, on first launch, in the user's local app-data folder (see `setup_engine`).
static ENGINE: std::sync::OnceLock<(PathBuf, PathBuf)> = std::sync::OnceLock::new();

fn dev_engine() -> Option<(PathBuf, PathBuf)> {
    // Release builds always use their own engine (exactly what customers get); the source tree's engine is for
    // `tauri dev`, or a release build started with FILMCRAFTER_DEV_ENGINE=1.
    if !cfg!(debug_assertions) && std::env::var_os("FILMCRAFTER_DEV_ENGINE").is_none() {
        return None;
    }
    let dir = Path::new(env!("CARGO_MANIFEST_DIR")).join("..").join("analysis");
    let py = if cfg!(windows) { dir.join(".venv").join("Scripts").join("python.exe") } else { dir.join(".venv").join("bin").join("python") };
    (py.exists() && dir.join("filmcrafter_engine").exists()).then_some((dir, py))
}

fn installed_env(app: &AppHandle) -> Option<PathBuf> {
    app.path().app_local_data_dir().ok().map(|d| d.join("engine-env"))
}

fn init_engine(app: &AppHandle) {
    let _ = ENGINE.get_or_init(|| {
        if let Some(dev) = dev_engine() {
            return dev;
        }
        let code = app.path().resource_dir().map(|r| r.join("engine")).unwrap_or_default();
        let env = installed_env(app).unwrap_or_default();
        let py = env_python(&env);
        link_engine_code(&env, &code);
        (code, py)
    });
}

/// The embedded interpreter ignores PYTHONPATH, so register the engine code with it via a .pth file.
/// Refreshed on every launch in case the app was moved or updated.
fn env_python(env: &Path) -> PathBuf {
    if cfg!(windows) { env.join("python.exe") } else { env.join("python").join("bin").join("python3") }
}

fn site_packages(env: &Path) -> PathBuf {
    if cfg!(windows) { env.join("Lib").join("site-packages") } else { env.join("python").join("lib").join("python3.11").join("site-packages") }
}

fn link_engine_code(env: &Path, code: &Path) {
    let sp = site_packages(env);
    if sp.exists() {
        let want = code.to_string_lossy().to_string();
        let pth = sp.join("filmcrafter_engine.pth");
        if fs::read_to_string(&pth).map(|c| c.trim() != want).unwrap_or(true) {
            let _ = fs::write(&pth, want);
        }
    }
}

fn engine_dir() -> PathBuf {
    ENGINE.get().map(|e| e.0.clone()).unwrap_or_default()
}

fn engine_python() -> PathBuf {
    ENGINE.get().map(|e| e.1.clone()).unwrap_or_default()
}

fn read_json(path: &Path) -> Option<Value> {
    fs::read_to_string(path).ok().and_then(|s| serde_json::from_str(&s).ok())
}

/// A picture of the film itself, for its card on Home: the first chosen keyframe (by shot id), read from the film's own files. None when there is none, or when what the file names is not a picture
/// that lies inside the film's render folder (a hand-edited file cannot point the card at anything else).
fn film_thumb(dir: &Path) -> Option<String> {
    let render = dir.join("render");
    let k = read_json(&render.join("keyframes.json"))?;
    let prod = k.get("production")?.as_object()?;
    let base = fs::canonicalize(&render).ok()?;
    let mut ids: Vec<&String> = prod.keys().collect();
    ids.sort();
    for id in ids {
        let Some(name) = prod[id].as_str() else { continue };
        let rel = name.strip_prefix("project:").unwrap_or(name);
        let rp = Path::new(rel);
        let plain = !rel.is_empty() && rp.components().all(|c| matches!(c, std::path::Component::Normal(_)));
        let pic = rp.extension().and_then(|e| e.to_str()).map(|e| matches!(e.to_ascii_lowercase().as_str(), "png" | "jpg" | "jpeg" | "webp")).unwrap_or(false);
        if !plain || !pic {
            continue;
        }
        let full = render.join(rp);
        if fs::canonicalize(&full).map(|c| c.starts_with(&base) && c.is_file()).unwrap_or(false) {
            return Some(full.to_string_lossy().to_string());
        }
    }
    None
}

fn write_json(path: &Path, v: &Value) -> Result<(), String> {
    // Write-then-rename so a crash never leaves a half-written project file.
    let tmp = path.with_extension("json.tmp");
    fs::write(&tmp, serde_json::to_string_pretty(v).map_err(err)?).map_err(err)?;
    fs::rename(&tmp, path).map_err(err)
}

fn update_project(dir: &Path, patch: Value) -> Result<(), String> {
    let path = dir.join("project.json");
    let mut p = read_json(&path).unwrap_or_else(|| json!({}));
    if let (Some(obj), Some(add)) = (p.as_object_mut(), patch.as_object()) {
        for (k, v) in add {
            obj.insert(k.clone(), v.clone());
        }
    }
    write_json(&path, &p)
}

/// Run one engine job, forwarding progress lines to the UI. Returns stderr tail on failure.
fn run_engine(app: &AppHandle, job: &str, args: &[String], envs: &[(&str, String)]) -> Result<(), String> {
    run_engine_result(app, job, args, envs).map(|_| ())
}

/// Like run_engine, but returns the `data` of the engine's final `{"event":"result"}` line.
fn run_engine_result(app: &AppHandle, job: &str, args: &[String], envs: &[(&str, String)]) -> Result<Value, String> {
    init_engine(app);
    let mut cmd = Command::new(engine_python());
    cmd.args(args)
        .current_dir(engine_dir())
        .env("PYTHONPATH", engine_dir())
        .env("PYTHONIOENCODING", "utf-8")
        .env("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());
    for (k, v) in envs {
        cmd.env(k, v);
    }
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        cmd.creation_flags(0x0800_0000); // CREATE_NO_WINDOW: never flash a console at the user
    }
    let mut child = cmd.spawn().map_err(|e| format!("Could not start the engine: {e}"))?;
    let mut stderr = child.stderr.take().unwrap();
    let err_thread = std::thread::spawn(move || {
        let mut s = String::new();
        let _ = stderr.read_to_string(&mut s);
        s
    });
    let mut engine_error: Option<String> = None;
    let mut result = Value::Null;
    for line in BufReader::new(child.stdout.take().unwrap()).lines().map_while(Result::ok) {
        if let Ok(mut v) = serde_json::from_str::<Value>(&line) {
            if v["event"] == "error" {
                engine_error = v["message"].as_str().map(String::from);
            }
            if v["event"] == "result" {
                result = v["data"].take();
                continue;
            }
            v["task"] = json!(job);
            let _ = app.emit("engine-progress", v);
        }
    }
    let status = child.wait().map_err(err)?;
    let stderr_text = err_thread.join().unwrap_or_default();
    if status.success() && engine_error.is_none() {
        return Ok(result);
    }
    let tail: String = stderr_text.lines().rev().take(6).collect::<Vec<_>>().into_iter().rev().collect::<Vec<_>>().join("\n");
    Err(engine_error.unwrap_or(tail))
}

fn slug(title: &str) -> String {
    let s: String = title
        .chars()
        .map(|c| if c.is_alphanumeric() || c == ' ' || c == '-' { c } else { ' ' })
        .collect();
    let s = s.split_whitespace().collect::<Vec<_>>().join(" ");
    if s.is_empty() { "Untitled".into() } else { s }
}

// ---------- splash ----------

static LAUNCHED: std::sync::OnceLock<std::time::Instant> = std::sync::OnceLock::new();
/// How long the splash stays: long enough to read (it used to be 1.2 s, which was gone before anyone saw it). The person can close it sooner with the X, or open the guide from it.
const SPLASH_MIN: std::time::Duration = std::time::Duration::from_millis(4500);
static SPLASH_SKIP: std::sync::atomic::AtomicBool = std::sync::atomic::AtomicBool::new(false);
static OPEN_GUIDE: std::sync::atomic::AtomicBool = std::sync::atomic::AtomicBool::new(false);

/// Called by the UI after its first paint: keep the splash for its minimum (or until the person closes it), then close it and reveal the fully drawn main window.
#[tauri::command]
async fn app_ready(app: AppHandle) {
    use std::sync::atomic::Ordering;
    let started = *LAUNCHED.get_or_init(std::time::Instant::now);
    while started.elapsed() < SPLASH_MIN && !SPLASH_SKIP.load(Ordering::Relaxed) {
        tokio_sleep(std::time::Duration::from_millis(80)).await;
    }
    if let Some(main) = app.get_webview_window("main") {
        let _ = main.show();
        let _ = main.set_focus();
    }
    if let Some(splash) = app.get_webview_window("splashscreen") {
        let _ = splash.close();
    }
    if OPEN_GUIDE.swap(false, Ordering::Relaxed) {
        tokio_sleep(std::time::Duration::from_millis(500)).await;     // the window listens for the menu a moment after it appears
        let _ = app.emit("menu", "help");
    }
}

/// The splash's own buttons: close it now (the X), or close it and open the documentation. If the main window is not drawn yet, `app_ready` finishes the job the moment it is.
#[tauri::command]
fn splash_close(app: AppHandle, guide: Option<bool>) {
    use std::sync::atomic::Ordering;
    SPLASH_SKIP.store(true, Ordering::Relaxed);
    if guide.unwrap_or(false) {
        OPEN_GUIDE.store(true, Ordering::Relaxed);
    }
    let main_shown = app.get_webview_window("main").and_then(|m| m.is_visible().ok()).unwrap_or(false);
    if main_shown {
        if let Some(splash) = app.get_webview_window("splashscreen") {
            let _ = splash.close();
        }
        if OPEN_GUIDE.swap(false, Ordering::Relaxed) {
            let _ = app.emit("menu", "help");
        }
    }
}

async fn tokio_sleep(d: std::time::Duration) {
    let _ = tauri::async_runtime::spawn_blocking(move || std::thread::sleep(d)).await;
}

// ---------- engine setup (installed app, first launch) ----------

#[tauri::command]
fn engine_status(app: AppHandle) -> Value {
    init_engine(&app);
    let py = engine_python();
    let ready = py.exists() && engine_dir().join("filmcrafter_engine").exists()
        && (dev_engine().is_some() || installed_env(&app).map(|e| e.join(".ready")).is_some_and(|m| m.exists()));
    json!({"ready": ready, "dev": dev_engine().is_some(), "gpu": has_nvidia_gpu(), "python": py.to_string_lossy()})
}

fn has_nvidia_gpu() -> bool {
    let mut cmd = Command::new("nvidia-smi");
    cmd.arg("-L").stdout(Stdio::piped()).stderr(Stdio::null());
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        cmd.creation_flags(0x0800_0000);
    }
    cmd.output().map(|o| o.status.success() && String::from_utf8_lossy(&o.stdout).contains("GPU")).unwrap_or(false)
}

fn setup_step(app: &AppHandle, step: u32, total: u32, label: &str) {
    let _ = app.emit("engine-setup", json!({"step": step, "total": total, "label": label}));
}

fn run_quiet(program: &str, args: &[&str], cwd: Option<&Path>) -> Result<(), String> {
    let mut cmd = Command::new(program);
    cmd.args(args).stdout(Stdio::null()).stderr(Stdio::piped());
    if let Some(c) = cwd {
        cmd.current_dir(c);
    }
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        cmd.creation_flags(0x0800_0000);
    }
    let out = cmd.output().map_err(|e| format!("Couldn't run {program}: {e}"))?;
    if out.status.success() {
        Ok(())
    } else {
        let e = String::from_utf8_lossy(&out.stderr);
        Err(e.lines().rev().take(4).collect::<Vec<_>>().into_iter().rev().collect::<Vec<_>>().join("\n"))
    }
}

/// Standalone CPython for macOS (python-build-standalone). Newest 3.11 build, or a known-good fallback.
fn mac_python_url() -> String {
    let arch = if cfg!(target_arch = "aarch64") { "aarch64" } else { "x86_64" };
    let fallback = format!("https://github.com/astral-sh/python-build-standalone/releases/download/20260924/\
cpython-3.11.16+20260924-{arch}-apple-darwin-install_only.tar.gz");
    let out = Command::new("curl").args(["-sL", "--fail", "-H", "User-Agent: FilmCrafter",
        "https://api.github.com/repos/astral-sh/python-build-standalone/releases/latest"]).output();
    let Ok(o) = out else { return fallback };
    let Ok(v) = serde_json::from_slice::<Value>(&o.stdout) else { return fallback };
    let want = format!("{arch}-apple-darwin-install_only.tar.gz");
    v["assets"].as_array().into_iter().flatten()
        .filter_map(|a| Some((a["name"].as_str()?, a["browser_download_url"].as_str()?)))
        .find(|(n, _)| n.starts_with("cpython-3.11.") && n.ends_with(&want))
        .map(|(_, u)| u.to_string()).unwrap_or(fallback)
}

const PY_EMBED: &str = "https://www.python.org/ftp/python/3.11.9/python-3.11.9-embed-amd64.zip";
const GET_PIP: &str = "https://bootstrap.pypa.io/get-pip.py";

/// How much of the engine is on disk so far, for the first-launch progress line.
#[tauri::command]
async fn engine_setup_size(app: AppHandle) -> u64 {
    fn walk(p: &Path) -> u64 {
        fs::read_dir(p).map(|rd| rd.flatten().map(|e| match e.file_type() {
            Ok(t) if t.is_dir() => walk(&e.path()),
            _ => e.metadata().map(|m| m.len()).unwrap_or(0),
        }).sum()).unwrap_or(0)
    }
    let Some(env) = installed_env(&app) else { return 0 };
    tauri::async_runtime::spawn_blocking(move || walk(&env)).await.unwrap_or(0)
}

/// One-time engine install for the packaged app (Windows): private Python 3.11 + pinned engine packages
/// in local app data. GPU builds of PyTorch are used when an NVIDIA card is present. Resumable: each
/// step is skipped if already done.
#[tauri::command]
async fn setup_engine(app: AppHandle) -> Result<Value, String> {
    init_engine(&app);
    if dev_engine().is_some() {
        return Ok(json!({"ready": true, "dev": true}));
    }
    let env = installed_env(&app).ok_or("No app-data folder.")?;
    let reqs = engine_dir().join("requirements-engine.txt");
    tauri::async_runtime::spawn_blocking(move || {
        let total = 4;
        fs::create_dir_all(&env).map_err(err)?;
        let py = env_python(&env);
        let s = |p: &Path| p.to_string_lossy().to_string();
        if !cfg!(windows) && !py.exists() {
            setup_step(&app, 1, total, "Downloading Python for your Mac (about 20 MB)");
            let url = mac_python_url();
            let tgz = env.join("python.tar.gz");
            run_quiet("curl", &["-L", "--fail", "-o", &s(&tgz), &url], None)?;
            run_quiet("tar", &["-xzf", &s(&tgz)], Some(&env))?; // creates env/python/...
            let _ = fs::remove_file(&tgz);
        }
        if cfg!(windows) && !py.exists() {
            setup_step(&app, 1, total, "Downloading Python (about 11 MB)");
            let zip = env.join("python.zip");
            run_quiet("curl.exe", &["-L", "--fail", "-o", &s(&zip), PY_EMBED], None)?;
            run_quiet("tar.exe", &["-xf", &s(&zip)], Some(&env))?;
            let _ = fs::remove_file(&zip);
            // Embedded Python ignores site-packages until `import site` is enabled.
            if let Some(pth) = fs::read_dir(&env).map_err(err)?.flatten().map(|e| e.path())
                .find(|p| p.extension().and_then(|x| x.to_str()) == Some("_pth")) {
                let body = fs::read_to_string(&pth).map_err(err)?.replace("#import site", "import site");
                fs::write(&pth, format!("{body}\nLib\\site-packages\n")).map_err(err)?;
            }
        }
        if cfg!(windows) && !env.join("Scripts").join("pip.exe").exists() {
            setup_step(&app, 2, total, "Installing the package manager");
            let gp = env.join("get-pip.py");
            run_quiet("curl.exe", &["-L", "--fail", "-o", &s(&gp), GET_PIP], None)?;
            run_quiet(&s(&py), &[&s(&gp), "--no-warn-script-location"], Some(&env))?;
            let _ = fs::remove_file(&gp);
        }
        setup_step(&app, 3, total, "Installing the film engine (about 150 MB)");
        run_quiet(&s(&py), &["-m", "pip", "install", "--no-warn-script-location", "-r", &s(&reqs)], Some(&env))?;
        let gpu = false;
        link_engine_code(&env, &engine_dir());
        setup_step(&app, 4, total, "Checking everything works");
        run_quiet(&s(&py), &["-c", "import openai, fal_client, pypdf, imageio_ffmpeg, PIL, yaml, keyring, numpy, soundfile, requests, filmcrafter_engine.render, filmcrafter_engine.story, filmcrafter_engine.make"], Some(&env))?;
        fs::write(env.join(".ready"), "ok").map_err(err)?;
        Ok(json!({"ready": true, "gpu": gpu}))
    }).await.map_err(err)?
}

// ---------- keys ----------

#[tauri::command]
fn key_status() -> Value {
    let mut out = serde_json::Map::new();
    for p in PROVIDERS {
        let ok = keyring::Entry::new(KEY_SERVICE, p)
            .and_then(|e| e.get_password())
            .map(|k| !k.is_empty())
            .unwrap_or(false);
        out.insert(p.into(), json!(ok));
    }
    Value::Object(out)
}

#[tauri::command]
fn set_key(provider: String, key: String) -> Result<(), String> {
    if !PROVIDERS.contains(&provider.as_str()) {
        return Err("Unknown provider".into());
    }
    let key = key.trim();
    if key.is_empty() {
        return Err("Key is empty".into());
    }
    keyring::Entry::new(KEY_SERVICE, &provider).and_then(|e| e.set_password(key)).map_err(err)
}

#[tauri::command]
fn delete_key(provider: String) -> Result<(), String> {
    match keyring::Entry::new(KEY_SERVICE, &provider).and_then(|e| e.delete_credential()) {
        Ok(()) | Err(keyring::Error::NoEntry) => Ok(()),
        Err(e) => Err(err(e)),
    }
}

// ---------- projects ----------
//
// A project is a folder holding project.json and its media, plus a small `<Title>.filmcrafter`
// document file. Double-clicking that file (or choosing it in Open) opens the folder.

const DOC_EXT: &str = "filmcrafter";

/// Accept either a project folder or its .filmcrafter document and return the folder.
fn project_dir(path: &str) -> Result<PathBuf, String> {
    let p = PathBuf::from(path);
    let dir = if p.is_file() { p.parent().map(Path::to_path_buf).unwrap_or(p) } else { p };
    if dir.join("project.json").exists() {
        Ok(dir)
    } else {
        Err("That isn't a FilmCrafter project.".into())
    }
}

/// Make sure the project has its double-clickable document file (older projects didn't).
fn ensure_doc(dir: &Path) -> Option<PathBuf> {
    if let Ok(rd) = fs::read_dir(dir) {
        for e in rd.flatten() {
            if e.path().extension().and_then(|x| x.to_str()) == Some(DOC_EXT) && e.path().is_file() {
                return Some(e.path());
            }
        }
    }
    let title = read_json(&dir.join("project.json"))
        .and_then(|p| p["title"].as_str().map(String::from))
        .unwrap_or_else(|| "Untitled".into());
    let doc = dir.join(format!("{}.{DOC_EXT}", slug(&title)));
    let body = json!({"format": "filmcrafter-project", "version": 1, "data": "project.json",
                      "note": "Open this file with FilmCrafter. The project's media lives in this folder."});
    fs::write(&doc, serde_json::to_string_pretty(&body).ok()?).ok()?;
    Some(doc)
}

fn recent_path(app: &AppHandle) -> Option<PathBuf> {
    let d = app.path().app_data_dir().ok()?;
    fs::create_dir_all(&d).ok()?;
    Some(d.join("recent.json"))
}

/// The webview may read pictures, video and audio only from the folders FilmCrafter is working in (the configured scope covers the projects folder and the app's own data). A film opened from
/// anywhere else (another drive, the Desktop) is added here, for this run, when it is opened; so is every film in the recent list at start-up. Files the person picks in a dialog are
/// allowed by the dialog plugin itself. A folder that does not exist (a disconnected drive) is simply not added.
fn allow_media(app: &AppHandle, dir: &Path) {
    if dir.is_dir() {
        let _ = app.asset_protocol_scope().allow_directory(dir, true);
    }
}

fn remember(app: &AppHandle, dir: &Path) {
    allow_media(app, dir);
    let Some(p) = recent_path(app) else { return };
    let mut list: Vec<String> = read_json(&p).and_then(|v| serde_json::from_value(v).ok()).unwrap_or_default();
    let s = dir.to_string_lossy().to_string();
    list.retain(|x| x != &s);
    list.insert(0, s.clone());
    list.truncate(20);
    let _ = write_json(&p, &json!(list));
    // opening a project brings it back to the Recent list if it was hidden
    if let Some(hp) = hidden_path(app) {
        let mut h = hidden(app);
        if h.iter().any(|x| x == &s) { h.retain(|x| x != &s); let _ = write_json(&hp, &json!(h)); }
    }
}


/// Projects taken off the Recent list (never deleted: the folders stay where they are).
fn hidden_path(app: &AppHandle) -> Option<PathBuf> {
    recent_path(app).map(|p| p.with_file_name("hidden.json"))
}

fn hidden(app: &AppHandle) -> Vec<String> {
    hidden_path(app).and_then(|p| read_json(&p)).and_then(|v| serde_json::from_value(v).ok()).unwrap_or_default()
}

/// Recent list housekeeping: "remove" one project from the list, "clear" them all, or "restore" everything hidden.
/// Only the list changes; project files are never touched.
#[tauri::command]
fn recents(app: AppHandle, action: String, dir: Option<String>) -> Result<Value, String> {
    let hp = hidden_path(&app).ok_or("No app data folder.")?;
    let rp = recent_path(&app).ok_or("No app data folder.")?;
    let mut h = hidden(&app);
    match action.as_str() {
        "remove" => {
            let d = dir.ok_or("Which project?")?;
            if !h.contains(&d) { h.push(d.clone()); }
            let mut r: Vec<String> = read_json(&rp).and_then(|v| serde_json::from_value(v).ok()).unwrap_or_default();
            r.retain(|x| x != &d);
            write_json(&rp, &json!(r))?;
        }
        "clear" => {
            for p in list_projects(app.clone())? {
                if let Some(d) = p["dir"].as_str() { if !h.iter().any(|x| x == d) { h.push(d.to_string()); } }
            }
            write_json(&rp, &json!([]))?;
        }
        "restore" => h.clear(),
        _ => return Err("Unknown action.".into()),
    }
    write_json(&hp, &json!(h))?;
    Ok(json!({"hidden": h.len()}))
}

#[tauri::command]
fn hidden_count(app: AppHandle) -> usize {
    hidden(&app).len()
}

#[tauri::command]
fn list_projects(app: AppHandle) -> Result<Vec<Value>, String> {
    let mut out = vec![];
    let mut dirs: Vec<PathBuf> = fs::read_dir(projects_root(&app)?).map_err(err)?.flatten().map(|e| e.path()).collect();
    if let Some(r) = recent_path(&app).and_then(|p| read_json(&p)) {
        for d in r.as_array().into_iter().flatten().filter_map(|v| v.as_str()) {
            let d = PathBuf::from(d);
            if !dirs.contains(&d) {
                dirs.push(d);
            }
        }
    }
    let hide = hidden(&app);
    for dir in dirs {
        if hide.iter().any(|h| Path::new(h) == dir.as_path()) { continue; }
        if let (Ok(meta), Some(f)) = (fs::metadata(dir.join("film.json")), read_json(&dir.join("film.json"))) {   // a film
            let modified = meta.modified().ok().and_then(|t| t.duration_since(std::time::UNIX_EPOCH).ok()).map(|d| d.as_secs()).unwrap_or(0);
            let locked = f["story"]["locked"].is_number();
            let kind = f["story"]["kind"].as_str().unwrap_or("idea");
            out.push(json!({"title": f["title"], "dir": dir.to_string_lossy(), "modified": modified, "kind": "film", "aspect": f["aspect_ratio"], "thumb": film_thumb(&dir), "state": if locked { "Story locked".to_string() } else if kind == "screenplay" { "Screenplay".to_string() } else { format!("Story: {kind}") }}));
            continue;
        }
        let Ok(meta) = fs::metadata(dir.join("project.json")) else { continue };
        if let Some(mut p) = read_json(&dir.join("project.json")) {
            let modified = meta.modified().ok()
                .and_then(|t| t.duration_since(std::time::UNIX_EPOCH).ok())
                .map(|d| d.as_secs()).unwrap_or(0);
            p["dir"] = json!(dir.to_string_lossy());
            p["modified"] = json!(modified);
            out.push(p);
        }
    }
    out.sort_by(|a, b| b["modified"].as_u64().cmp(&a["modified"].as_u64()));
    Ok(out)
}


#[tauri::command]
fn load_project(app: AppHandle, dir: String) -> Result<Value, String> {
    let resolved = project_dir(&dir)?;
    let doc = ensure_doc(&resolved);
    remember(&app, &resolved);
    let dir = resolved.to_string_lossy().to_string();
    let d = resolved.as_path();
    let project = read_json(&d.join("project.json")).ok_or("This project could not be opened.")?;
    let song = project["song"].as_str().map(|s| d.join(s).to_string_lossy().to_string());
    Ok(json!({
        "dir": dir,
        "project": project,
        "song_path": song,
        "song_map": read_json(&d.join("songmap.json")),
        "production": read_json(&d.join("production.json")),
        "directed": read_json(&d.join("directed.json")),
        "jobs": read_json(&d.join("jobs.json")).map(|j| j["jobs"].clone()).unwrap_or(json!([])),
        "doc": doc.map(|p| p.to_string_lossy().to_string()),
        "keyframes": read_json(&d.join("keyframes.json")).unwrap_or(json!({})),
        "concepts": read_json(&d.join("concepts.json")),
        "treatment": read_json(&d.join("treatment.json")),
    }))
}

// ---------- rendering ----------

fn provider_env() -> Vec<(&'static str, String)> {
    let mut env = vec![];
    // OpenAI powers the visual review of finished takes.
    for (provider, var) in [("fal", "FAL_KEY"), ("kie", "KIE_KEY"), ("openai", "FILMCRAFTER_OPENAI_KEY"), ("anthropic", "ANTHROPIC_API_KEY"), ("google", "GEMINI_API_KEY"), ("elevenlabs", "ELEVENLABS_KEY"), ("byteplus", "BYTEPLUS_KEY")] {
        if let Ok(k) = keyring::Entry::new(KEY_SERVICE, provider).and_then(|e| e.get_password()) {
            env.push((var, k));
        }
    }
    env
}

fn render_args(sub: &str, rest: &[String]) -> Vec<String> {
    let mut a = vec!["-m".to_string(), "filmcrafter_engine.render".into(), sub.into()];
    a.extend_from_slice(rest);
    a
}

/// Project folders with a live background renderer, so we never start two for one project.
static RUNNERS: std::sync::Mutex<Vec<String>> = std::sync::Mutex::new(Vec::new());

/// Start (or keep) the background renderer for a project. It drives every queued/in-flight job,
/// including ones left running when the app was closed, then exits.
#[tauri::command]
fn ensure_renderer(app: AppHandle, dir: String) {
    let Ok(dir) = project_dir(&dir).map(|d| d.to_string_lossy().to_string()) else { return };     // only ever a real project
    {
        let mut r = RUNNERS.lock().unwrap();
        if r.contains(&dir) {
            // a renderer is running (maybe just finishing): make it look again before it stops,
            // so work queued in that moment is never left waiting
            let mut again = RERUN.lock().unwrap();
            if !again.contains(&dir) { again.push(dir); }
            return;
        }
        r.push(dir.clone());
    }
    std::thread::spawn(move || {
        loop {
            let res = run_engine(&app, "render", &render_args("run", std::slice::from_ref(&dir)), &provider_env());
            let mut runners = RUNNERS.lock().unwrap();
            let mut again = RERUN.lock().unwrap();
            if again.contains(&dir) {
                again.retain(|d| d != &dir);
                continue;   // new work arrived while it was running: go round once more
            }
            runners.retain(|d| d != &dir);
            let _ = app.emit("render-idle", json!({"dir": dir, "error": res.err()}));
            break;
        }
    });
}

/// Projects whose renderer should look for work once more before it stops.
static RERUN: std::sync::Mutex<Vec<String>> = std::sync::Mutex::new(Vec::new());

#[tauri::command]
async fn render_catalog(app: AppHandle, provider: String, kind: Option<String>, refresh: Option<bool>) -> Result<Value, String> {
    tauri::async_runtime::spawn_blocking(move || {
        let mut args: Vec<String> = vec!["--provider".into(), provider, "--kind".into(), kind.unwrap_or_else(|| "video".into())];
        if refresh.unwrap_or(false) {
            args.push("--refresh".into());   // ask the provider again instead of using today's saved list (to see a model added today)
        }
        run_engine_result(&app, "catalog", &render_args("catalog", &args), &[])
    }).await.map_err(err)?
}


fn shot_args(dir: String, shots: Vec<String>, provider: String, model: Option<String>, overrides: Value) -> Vec<String> {
    let mut a = vec![dir, "--shots".into(), shots.join(","), "--provider".into(), provider,
                     "--overrides".into(), overrides.to_string()];
    if let Some(m) = model.filter(|m| !m.is_empty()) {
        a.push("--model".into());
        a.push(m);
    }
    a
}

/// Exactly what would be sent for one shot. Uploads nothing and costs nothing.
#[tauri::command]
async fn render_preview(app: AppHandle, dir: String, shot: String, provider: String, model: Option<String>,
                        overrides: Value, kind: Option<String>) -> Result<Value, String> {
    let dir = project_dir(&dir)?.to_string_lossy().to_string();
    tauri::async_runtime::spawn_blocking(move || {
        let mut a = shot_args(dir, vec![shot], provider, model, overrides);
        a.extend(["--kind".into(), kind.unwrap_or_else(|| "video".into())]);
        run_engine_result(&app, "preview", &render_args("preview", &a), &[])
    }).await.map_err(err)?
}

/// Queue shots for rendering (billable once the renderer sends them) and start the renderer.
#[tauri::command]
#[allow(clippy::too_many_arguments)]         // the arguments are the command's public shape, named by the screen
async fn queue_render(app: AppHandle, dir: String, shots: Vec<String>, provider: String, model: Option<String>,
                      overrides: Value, fix_notes: Option<Vec<String>>, kind: Option<String>,
                      source_job: Option<String>, spend_token: Option<String>) -> Result<Value, String> {
    // ComfyUI runs locally with no key; the engine checks that it's reachable.
    let key_ok = provider == "comfyui" || keyring::Entry::new(KEY_SERVICE, &provider).and_then(|e| e.get_password()).is_ok();
    if !key_ok {
        return Err(format!("Add your {} key in Settings first.", provider_name(&provider)));
    }
    let dir = project_dir(&dir)?.to_string_lossy().to_string();
    redeem_spend(spend_token.as_deref(), &dir, &provider, kind.as_deref().unwrap_or("video"), &shots)?;
    let app2 = app.clone();
    let d2 = dir.clone();
    let made = tauri::async_runtime::spawn_blocking(move || {
        let mut args = shot_args(d2, shots, provider, model, overrides);
        args.push("--fix-notes".into());
        args.push(json!(fix_notes.unwrap_or_default()).to_string());
        args.extend(["--kind".into(), kind.unwrap_or_else(|| "video".into())]);
        if let Some(s) = source_job {
            args.extend(["--source-job".into(), s]);
        }
        run_engine_result(&app2, "enqueue", &render_args("enqueue", &args), &[])
    }).await.map_err(err)??;
    ensure_renderer(app, dir);
    Ok(made)
}

/// Cost estimate from live provider prices (free; fetches prices only).
#[tauri::command]
async fn render_estimate(app: AppHandle, dir: String, shots: Vec<String>, provider: String, model: Option<String>,
                         kind: Option<String>) -> Result<Value, String> {
    let dir = project_dir(&dir)?.to_string_lossy().to_string();
    tauri::async_runtime::spawn_blocking(move || {
        let mut args = vec![dir, "--shots".into(), shots.join(","), "--provider".into(), provider,
                            "--kind".into(), kind.unwrap_or_else(|| "video".into())];
        if let Some(m) = model.filter(|m| !m.is_empty()) {
            args.push("--model".into());
            args.push(m);
        }
        run_engine_result(&app, "estimate", &render_args("estimate", &args), &provider_env())
    }).await.map_err(err)?
}

#[tauri::command]
async fn resolve_job(app: AppHandle, dir: String, job: String, action: String) -> Result<Value, String> {
    let dir = project_dir(&dir)?.to_string_lossy().to_string();
    let app2 = app.clone();
    let d2 = dir.clone();
    let res = tauri::async_runtime::spawn_blocking(move || {
        run_engine_result(&app2, "resolve", &render_args("resolve", &[d2, "--job".into(), job, "--action".into(), action]), &[])
    }).await.map_err(err)??;
    ensure_renderer(app, dir);
    Ok(res)
}

/// Reference library, storyboard, versions and thumbnails (filmcrafter_engine.library). Nothing billable.
#[tauri::command]
async fn library(app: AppHandle, dir: String, action: String, data: Option<Value>) -> Result<Value, String> {
    const ACTIONS: [&str; 17] = ["storyboard", "thumbs", "library", "upsert", "delete", "assign", "reset", "approve", "approve_latest", "lock",
                                 "shot_refs", "pending_keyframes", "approve_keyframes", "bible", "keyframe_options", "choose_keyframe", "reject_keyframe"];
    if !ACTIONS.contains(&action.as_str()) {
        return Err("Unknown library action.".into());
    }
    project_dir(&dir)?;
    tauri::async_runtime::spawn_blocking(move || {
        let args = vec!["-m".to_string(), "filmcrafter_engine.library".into(), action, dir,
                        "--data".into(), data.unwrap_or_else(|| json!({})).to_string()];
        run_engine_result(&app, "library", &args, &[])
    }).await.map_err(err)?
}

/// "Regenerate shot 12 using Kling" -> a proposed action (nothing is sent; the app confirms and prices it first).
#[tauri::command]
async fn parse_action(app: AppHandle, dir: String, note: String, selected: Option<String>, playhead: Option<f64>) -> Result<Value, String> {
    let d = project_dir(&dir)?.to_string_lossy().to_string();
    tauri::async_runtime::spawn_blocking(move || {
        let mut a = vec!["-m".into(), "filmcrafter_engine.actions".into(), d, "--note".into(), note];
        if let Some(s) = selected { a.extend(["--selected".into(), s]); }
        if let Some(p) = playhead { a.extend(["--playhead".into(), format!("{p:.2}")]); }
        run_engine_result(&app, "actions", &a, &provider_env())
    }).await.map_err(err)?
}

/// Providers overview and ComfyUI setup (address, workflows). action: status | comfy_config | comfy_add | comfy_remove
#[tauri::command]
async fn providers(app: AppHandle, action: String, data: Option<Value>) -> Result<Value, String> {
    if !["status", "comfy_config", "comfy_add", "comfy_remove"].contains(&action.as_str()) {
        return Err("Unknown action.".into());
    }
    tauri::async_runtime::spawn_blocking(move || {
        run_engine_result(&app, "providers", &["-m".into(), "filmcrafter_engine.router".into(), action,
                                               data.unwrap_or_else(|| json!({})).to_string()], &provider_env())
    }).await.map_err(err)?
}

// ---------- setup wizard ----------





/// Where a project is in the setup wizard: {stage, done: [..], skipped: [..], concept, source_video, ...}.
#[tauri::command]
fn set_onboarding(dir: String, value: Value) -> Result<(), String> {
    let d = project_dir(&dir)?;
    if !value.is_object() {
        return Err("Invalid setup state.".into());
    }
    update_project(&d, json!({"onboarding": value}))
}

/// Studio: use a screenplay (a file, or pasted text) as the project's plan. The script only becomes the project's
/// script if its scenes import; the previous plan, takes and keyframes are archived by the engine, never deleted.
#[tauri::command]
async fn adopt_script(app: AppHandle, dir: String, path: Option<String>, text: Option<String>) -> Result<Value, String> {
    let d = project_dir(&dir)?;
    tauri::async_runtime::spawn_blocking(move || {
        let staging = d.join("cache");
        fs::create_dir_all(&staging).map_err(err)?;
        let (candidate, ext, source) = if let Some(t) = text.filter(|t| !t.trim().is_empty()) {
            let c = staging.join("script-candidate.txt");
            fs::write(&c, t).map_err(err)?;
            (c, "txt".to_string(), None)
        } else if let Some(pth) = path {
            let src = PathBuf::from(&pth);
            let ext = src.extension().and_then(|e| e.to_str()).unwrap_or("").to_lowercase();
            if !["pdf", "txt", "md", "fountain"].contains(&ext.as_str()) {
                return Err("Use a PDF, TXT or MD script.".into());
            }
            let c = staging.join(format!("script-candidate.{ext}"));
            fs::copy(&src, &c).map_err(|e| format!("Could not read the script: {e}"))?;
            (c, ext, Some(pth))
        } else {
            return Err("Paste a script or choose a file.".into());
        };
        let res = run_engine_result(&app, "script", &["-m".into(), "filmcrafter_engine.script_import".into(), "adopt".into(),
                                                     d.to_string_lossy().to_string(), candidate.to_string_lossy().to_string()], &[]);
        let res = match res { Ok(v) => v, Err(e) => { let _ = fs::remove_file(&candidate); return Err(e); } };
        let mut p = read_json(&d.join("project.json")).ok_or("Missing project file")?;
        let name = format!("script.{ext}");
        if let Some(old) = p["script"].as_str() {
            if d.join(old).exists() {
                let _ = fs::rename(d.join(old), d.join(format!("replaced {old}")));
            }
        }
        fs::rename(&candidate, d.join(&name)).map_err(err)?;
        p["script"] = json!(name);
        if let Some(src) = source { p["script_source"] = json!(src); }
        if let Some(o) = p.as_object_mut() { o.remove("script_note"); }
        write_json(&d.join("project.json"), &p)?;
        Ok(res)
    }).await.map_err(err)?
}


/// Budget guard: balances, project spend and whether a batch fits (status), or move unsent jobs (reroute).
#[tauri::command]
async fn budget(app: AppHandle, action: String, dir: Option<String>, need: Option<Value>, provider: Option<String>) -> Result<Value, String> {
    if !["status", "reroute"].contains(&action.as_str()) {
        return Err("Unknown action.".into());
    }
    tauri::async_runtime::spawn_blocking(move || {
        let mut a = vec!["-m".to_string(), "filmcrafter_engine.budget".into(), action];
        if let Some(d) = dir { a.push(project_dir(&d)?.to_string_lossy().to_string()); }
        if let Some(n) = need { a.extend(["--need".into(), n.to_string()]); }
        if let Some(p) = provider { a.extend(["--provider".into(), p]); }
        run_engine_result(&app, "budget", &a, &provider_env())
    }).await.map_err(err)?
}

/// Bring Your Own Media (filmcrafter_engine.media): own images/clips as takes, moving stills, transitions,
/// a plan cut from the song. Free: nothing is sent to any provider.
#[tauri::command]
async fn media(app: AppHandle, dir: String, action: String, data: Option<Value>) -> Result<Value, String> {
    if !["import", "fill", "stills", "motion", "transition", "plan"].contains(&action.as_str()) {
        return Err("Unknown media action.".into());
    }
    let d = project_dir(&dir)?.to_string_lossy().to_string();
    tauri::async_runtime::spawn_blocking(move || {
        run_engine_result(&app, "media", &["-m".into(), "filmcrafter_engine.media".into(), action, d,
                                           "--data".into(), data.unwrap_or_else(|| json!({})).to_string()], &[])
    }).await.map_err(err)?
}

/// Continuity Director (filmcrafter_engine.continuity). Only ai_check uses the AI brain (one look per scene).
#[tauri::command]
async fn continuity(app: AppHandle, dir: String, action: String, data: Option<Value>) -> Result<Value, String> {
    if !["get", "set", "shot", "chain", "check", "ai_check"].contains(&action.as_str()) {
        return Err("Unknown continuity action.".into());
    }
    let d = project_dir(&dir)?.to_string_lossy().to_string();
    let env = if action == "ai_check" { openai_env()? } else { vec![] };
    tauri::async_runtime::spawn_blocking(move || {
        run_engine_result(&app, "continuity", &["-m".into(), "filmcrafter_engine.continuity".into(), action, d,
                                                "--data".into(), data.unwrap_or_else(|| json!({})).to_string()], &env)
    }).await.map_err(err)?
}

/// Performance profiles (filmcrafter_engine.performance). Free.
#[tauri::command]
async fn performance(app: AppHandle, dir: String, action: String, data: Option<Value>) -> Result<Value, String> {
    if !["get", "set"].contains(&action.as_str()) {
        return Err("Unknown performance action.".into());
    }
    let d = project_dir(&dir)?.to_string_lossy().to_string();
    tauri::async_runtime::spawn_blocking(move || {
        run_engine_result(&app, "performance", &["-m".into(), "filmcrafter_engine.performance".into(), action, d,
                                                 "--data".into(), data.unwrap_or_else(|| json!({})).to_string()], &[])
    }).await.map_err(err)?
}

/// How each model has done in this project (filmcrafter_engine.track): takes, failures, cost, review verdicts and the free sound check on sung takes. Reads what the project recorded; sends nothing.
#[tauri::command]
async fn track(app: AppHandle, dir: String, action: String) -> Result<Value, String> {
    if action != "stats" {
        return Err("Unknown track action.".into());
    }
    let d = project_dir(&dir)?.to_string_lossy().to_string();
    tauri::async_runtime::spawn_blocking(move || {
        run_engine_result(&app, "track", &["-m".into(), "filmcrafter_engine.track".into(), action, d], &[])
    }).await.map_err(err)?
}

/// Upscale a keyframe or a take (filmcrafter_engine.upscale): Topaz, Recraft and others through Kie.ai or fal.ai. "run" sends one picture or video to the provider, who bills it; the other
/// actions only read or undo. A run is written to the project the moment the provider accepts it, so closing the app does not lose it ("resume").
#[tauri::command]
async fn upscale(app: AppHandle, dir: String, action: String, data: Option<Value>) -> Result<Value, String> {
    const ACTIONS: [&str; 5] = ["tools", "status", "resume", "revert", "run"];
    if !ACTIONS.contains(&action.as_str()) {
        return Err("Unknown upscale action.".into());
    }
    let d = project_dir(&dir)?.to_string_lossy().to_string();
    tauri::async_runtime::spawn_blocking(move || {
        run_engine_result(&app, "upscale", &["-m".into(), "filmcrafter_engine.upscale".into(), action, d, "--data".into(), data.unwrap_or_else(|| json!({})).to_string()], &provider_env())
    }).await.map_err(err)?
}

/// Routing modes and the project budget (filmcrafter_engine.routing).
#[tauri::command]
async fn routing(app: AppHandle, dir: String, action: String, data: Option<Value>) -> Result<Value, String> {
    if !["status", "set", "pick", "models"].contains(&action.as_str()) {
        return Err("Unknown routing action.".into());
    }
    let d = project_dir(&dir)?.to_string_lossy().to_string();
    tauri::async_runtime::spawn_blocking(move || {
        run_engine_result(&app, "routing", &["-m".into(), "filmcrafter_engine.routing".into(), action, d,
                                             "--data".into(), data.unwrap_or_else(|| json!({})).to_string()], &provider_env())
    }).await.map_err(err)?
}

/// Local Model Manager (filmcrafter_engine.localmodels): Ollama / LM Studio / ComfyUI on this computer.
#[tauri::command]
async fn local_models(app: AppHandle, action: String, data: Option<Value>) -> Result<Value, String> {
    if !["status", "pull", "delete", "use", "start", "lms_get", "unload", "test"].contains(&action.as_str()) {
        return Err("Unknown action.".into());
    }
    tauri::async_runtime::spawn_blocking(move || {
        run_engine_result(&app, "localmodels", &["-m".into(), "filmcrafter_engine.localmodels".into(), action,
                                                 "--data".into(), data.unwrap_or_else(|| json!({})).to_string()], &[])
    }).await.map_err(err)?
}

/// Production Supervisor (filmcrafter_engine.supervisor): list findings, record decisions; Fix / Regenerate queue renders
/// (mode and budget apply in the engine) and start the renderer.
#[tauri::command]
async fn supervisor(app: AppHandle, dir: String, action: String, data: Option<Value>) -> Result<Value, String> {
    if !["list", "decide", "decide_many"].contains(&action.as_str()) {
        return Err("Unknown supervisor action.".into());
    }
    let d = project_dir(&dir)?.to_string_lossy().to_string();
    let data = data.unwrap_or_else(|| json!({}));
    let renders = matches!(data["action"].as_str(), Some("fix") | Some("regenerate") | Some("recheck"));
    let app2 = app.clone();
    let res = tauri::async_runtime::spawn_blocking(move || {
        run_engine_result(&app2, "supervisor", &["-m".into(), "filmcrafter_engine.supervisor".into(), action, d,
                                                 "--data".into(), data.to_string()], &provider_env())
    }).await.map_err(err)??;
    if renders {
        ensure_renderer(app, dir);
    }
    Ok(res)
}

/// Worldwide creative-direction library (filmcrafter_engine.directions_library). Free.
#[tauri::command]
async fn direction_library(app: AppHandle, action: String, dir: Option<String>, data: Option<Value>) -> Result<Value, String> {
    if !["list", "match", "apply", "save", "delete"].contains(&action.as_str()) {
        return Err("Unknown action.".into());
    }
    let mut args: Vec<String> = vec!["-m".into(), "filmcrafter_engine.directions_library".into(), action];
    if let Some(d) = dir { args.push(project_dir(&d)?.to_string_lossy().to_string()); }
    args.extend(["--data".into(), data.unwrap_or_else(|| json!({})).to_string()]);
    tauri::async_runtime::spawn_blocking(move || run_engine_result(&app, "directions", &args, &[])).await.map_err(err)?
}

/// Optional filmmaker craft traits. Names stay in the project/UI; render prompts receive only traits.
#[tauri::command]
async fn director_style(app: AppHandle, dir: String, action: String, data: Value) -> Result<Value, String> {
    if !["list", "set", "clear"].contains(&action.as_str()) { return Err("Unknown director style action.".into()); }
    let d = project_dir(&dir)?.to_string_lossy().to_string();
    let args = vec!["-m".into(), "filmcrafter_engine.directorstyle".into(), action, d, "--data".into(), data.to_string()];
    tauri::async_runtime::spawn_blocking(move || run_engine_result(&app, "director_style", &args, &[])).await.map_err(err)?
}

/// Golden-path helpers (filmcrafter_engine.golden): take status per shot, free preview, Kie/fal split.
#[tauri::command]
async fn golden(app: AppHandle, dir: String, action: String, data: Option<Value>) -> Result<Value, String> {
    if !["status", "preview", "split", "changes"].contains(&action.as_str()) {
        return Err("Unknown action.".into());
    }
    let d = project_dir(&dir)?.to_string_lossy().to_string();
    let task = if action == "preview" { "export" } else { "golden" };
    tauri::async_runtime::spawn_blocking(move || {
        run_engine_result(&app, task, &["-m".into(), "filmcrafter_engine.golden".into(), action, d,
                                         "--data".into(), data.unwrap_or_else(|| json!({})).to_string()], &provider_env())
    }).await.map_err(err)?
}

/// Lip-sync check (filmcrafter_engine.lipsync_check): "count" is free; "run" uses the AI brain's vision model.
#[tauri::command]
async fn lipsync_check(app: AppHandle, dir: String, action: String, data: Option<Value>) -> Result<Value, String> {
    if !["count", "run", "timing"].contains(&action.as_str()) {
        return Err("Unknown action.".into());
    }
    let d = project_dir(&dir)?.to_string_lossy().to_string();
    let env = if action == "run" { openai_env()? } else { vec![] };
    tauri::async_runtime::spawn_blocking(move || {
        run_engine_result(&app, "lipsync_check", &["-m".into(), "filmcrafter_engine.lipsync_check".into(), action, d,
                                                   "--data".into(), data.unwrap_or_else(|| json!({})).to_string()], &env)
    }).await.map_err(err)?
}

/// Takes never visually checked: count them (free), or check them now (run: one AI look each).
#[tauri::command]
async fn review_backlog(app: AppHandle, dir: String, run: bool) -> Result<Value, String> {
    let d = project_dir(&dir)?.to_string_lossy().to_string();
    let env = if run { provider_env() } else { vec![] };
    tauri::async_runtime::spawn_blocking(move || {
        let mut a = render_args("backlog", &[d]);
        if run { a.push("--run".into()); }
        run_engine_result(&app, "review", &a, &env)
    }).await.map_err(err)?
}

/// ComfyUI without the nodes (filmcrafter_engine.comfy_setup): detect | start | setup. Local only, free.
#[tauri::command]
async fn comfy_setup(app: AppHandle, action: String, data: Option<Value>) -> Result<Value, String> {
    if !["detect", "start", "setup", "downloads", "download", "health", "test"].contains(&action.as_str()) {
        return Err("Unknown action.".into());
    }
    tauri::async_runtime::spawn_blocking(move || {
        run_engine_result(&app, "comfy", &["-m".into(), "filmcrafter_engine.comfy_setup".into(), action,
                                           "--data".into(), data.unwrap_or_else(|| json!({})).to_string()], &[])
    }).await.map_err(err)?
}

/// Compose a shot (filmcrafter_engine.compose): state | set_motion | clear_motion | models | queue_motion. Everything except queue_motion is free and local; queue_motion adds a billable
/// take through the same path as every other render (key check, budget, price shown first by the screen) and starts the renderer.
#[tauri::command]
async fn compose(app: AppHandle, dir: String, action: String, data: Value) -> Result<Value, String> {
    const ACTIONS: [&str; 19] = ["state", "set_motion", "clear_motion", "models", "queue_motion", "library_list", "library_add", "library_rename", "library_remove", "library_restore", "library_use", "library_tag", "library_export", "library_import","prompt_set", "prompt_write", "prompt_lint", "prompt_recipes", "prompt_preview"];
    if !ACTIONS.contains(&action.as_str()) {
        return Err("Unknown action.".into());
    }
    if action == "queue_motion" {
        let provider = data["provider"].as_str().unwrap_or("").to_string();
        if provider != "comfyui" && keyring::Entry::new(KEY_SERVICE, &provider).and_then(|e| e.get_password()).is_err() {
            let name = match provider.as_str() { "fal" => "fal.ai", "kie" => "Kie.ai", "google" => "Google Gemini", _ => "provider" };
            return Err(format!("Add your {name} key in Settings first."));
        }
    }
    let d = project_dir(&dir)?.to_string_lossy().to_string();
    let args: Vec<String> = vec!["-m".into(), "filmcrafter_engine.compose".into(), action.clone(), d.clone(), "--data".into(), data.to_string()];
    let app2 = app.clone();
    let res = tauri::async_runtime::spawn_blocking(move || run_engine_result(&app2, "compose", &args, &[])).await.map_err(err)??;
    if action == "queue_motion" {
        ensure_renderer(app, d);
    }
    Ok(res)
}

/// Fix only the bad hand (filmcrafter_engine.handfix): plan | queue | locate. `plan` is free; `locate` sends the keyframe to the AI brain's vision model (a few cents, shown first by the screen);
/// `queue` makes 1 to 3 versions of a crop of the marked part through the same path as every other render (key check, mode, budget) and starts the renderer. The result waits as a new keyframe: nothing
/// replaces the approved one until it is used (keyframe_set swap_apply, one undoable step).
#[tauri::command]
async fn hand_fix(app: AppHandle, dir: String, action: String, data: Value) -> Result<Value, String> {
    if !["plan", "queue", "locate"].contains(&action.as_str()) {
        return Err("Unknown action.".into());
    }
    let d = project_dir(&dir)?.to_string_lossy().to_string();
    let args: Vec<String> = vec!["-m".into(), "filmcrafter_engine.handfix".into(), action.clone(), d.clone(), "--data".into(), data.to_string()];
    let app2 = app.clone();
    let res = tauri::async_runtime::spawn_blocking(move || run_engine_result(&app2, "hand_fix", &args, &provider_env())).await.map_err(err)??;
    if action == "queue" {
        ensure_renderer(app, d);
    }
    Ok(res)
}

/// Work on the whole set of keyframes (filmcrafter_engine.keyframeset): check_plan | check_run | remake_plan | remake_run | remodel_plan | remodel_run | swap_status | swap_apply. The plans are free.
/// check_run sends each picture to the AI brain's vision model (a few cents each, shown first by the screen); remake_run and remodel_run queue new pictures through the same path as every other
/// render (key check, mode, budget) and start the renderer; nothing replaces an approved keyframe until swap_apply, which is one undoable step.
#[tauri::command]
async fn keyframe_set(app: AppHandle, dir: String, action: String, data: Value) -> Result<Value, String> {
    const ACTIONS: [&str; 8] = ["check_plan", "check_run", "remake_plan", "remake_run", "remodel_plan", "remodel_run", "swap_status", "swap_apply"];
    if !ACTIONS.contains(&action.as_str()) {
        return Err("Unknown action.".into());
    }
    let d = project_dir(&dir)?.to_string_lossy().to_string();
    let args: Vec<String> = vec!["-m".into(), "filmcrafter_engine.keyframeset".into(), action.clone(), d.clone(), "--data".into(), data.to_string()];
    let app2 = app.clone();
    let res = tauri::async_runtime::spawn_blocking(move || run_engine_result(&app2, "keyframe_set", &args, &provider_env())).await.map_err(err)??;
    if action == "remake_run" || action == "remodel_run" {
        ensure_renderer(app, d);
    }
    Ok(res)
}

/// Retry a failed render on a cheaper, proven model (filmcrafter_engine.retrycheap): options | retry. `options` is free and sends nothing; `retry` queues the shot again through the same path as
/// every other render (key check, mode, budget) and starts the renderer. The screen shows the price and asks first.
#[tauri::command]
async fn retry_cheaper(app: AppHandle, dir: String, action: String, data: Value) -> Result<Value, String> {
    if !["options", "retry"].contains(&action.as_str()) {
        return Err("Unknown action.".into());
    }
    if action == "retry" {
        let provider = data["provider"].as_str().unwrap_or("").to_string();
        if provider != "comfyui" && keyring::Entry::new(KEY_SERVICE, &provider).and_then(|e| e.get_password()).is_err() {
            return Err(format!("Add your {} key in Settings first.", provider_name(&provider)));
        }
    }
    let d = project_dir(&dir)?.to_string_lossy().to_string();
    let args: Vec<String> = vec!["-m".into(), "filmcrafter_engine.retrycheap".into(), action.clone(), d.clone(), "--data".into(), data.to_string()];
    let app2 = app.clone();
    let res = tauri::async_runtime::spawn_blocking(move || run_engine_result(&app2, "retry_cheaper", &args, &provider_env())).await.map_err(err)??;
    if action == "retry" {
        ensure_renderer(app, d);
    }
    Ok(res)
}

/// Undo and redo for the changes made to a shot (filmcrafter_engine.shothistory): list | undo | redo. Free and local; only small settings are put back, no picture or video is deleted.
#[tauri::command]
async fn shot_history(app: AppHandle, dir: String, action: String) -> Result<Value, String> {
    if !["list", "undo", "redo"].contains(&action.as_str()) {
        return Err("Unknown action.".into());
    }
    let d = project_dir(&dir)?.to_string_lossy().to_string();
    let args: Vec<String> = vec!["-m".into(), "filmcrafter_engine.shothistory".into(), action, d];
    tauri::async_runtime::spawn_blocking(move || run_engine_result(&app, "shot_history", &args, &[])).await.map_err(err)?
}

/// Prove a video model with a take you already have (filmcrafter_engine.proof): check | record | forget | report. All free and local; `record` measures the take again before it remembers anything.
#[tauri::command]
async fn proof(app: AppHandle, dir: String, action: String, data: Value) -> Result<Value, String> {
    if !["check", "record", "forget", "report"].contains(&action.as_str()) {
        return Err("Unknown action.".into());
    }
    let d = project_dir(&dir)?.to_string_lossy().to_string();
    let args: Vec<String> = vec!["-m".into(), "filmcrafter_engine.proof".into(), action, d, "--data".into(), data.to_string()];
    tauri::async_runtime::spawn_blocking(move || run_engine_result(&app, "proof", &args, &[])).await.map_err(err)?
}

/// One-click ComfyUI (filmcrafter_engine.comfy_install): plan | install. `plan` reads one web page and downloads nothing; `install` downloads ComfyUI's own official portable build from
/// its GitHub releases (checked against GitHub's checksum), unpacks it into a folder of its own and registers it so Find ComfyUI can start it. The user presses the button after reading
/// what, from where and how big.
#[tauri::command]
async fn comfy_install(app: AppHandle, action: String, data: Option<Value>) -> Result<Value, String> {
    if !["plan", "install"].contains(&action.as_str()) {
        return Err("Unknown action.".into());
    }
    tauri::async_runtime::spawn_blocking(move || {
        run_engine_result(&app, "comfy", &["-m".into(), "filmcrafter_engine.comfy_install".into(), action,
                                           "--data".into(), data.unwrap_or_else(|| json!({})).to_string()], &[])
    }).await.map_err(err)?
}

/// Start and end frames per shot (filmcrafter_engine.frames): get | set | start | chain | support | options | choose | use_image.
#[tauri::command]
async fn frames(app: AppHandle, dir: String, action: String, data: Value) -> Result<Value, String> {
    const ACTIONS: [&str; 10] = ["get", "set", "start", "chain", "support", "options", "choose", "use_image", "use_start", "extend_info"];
    if !ACTIONS.contains(&action.as_str()) {
        return Err("Unknown frames action.".into());
    }
    let d = project_dir(&dir)?.to_string_lossy().to_string();
    let args: Vec<String> = vec!["-m".into(), "filmcrafter_engine.frames".into(), action, d, "--data".into(), data.to_string()];
    tauri::async_runtime::spawn_blocking(move || run_engine_result(&app, "frames", &args, &provider_env())).await.map_err(err)?
}

fn film_dir(path: &str) -> Result<PathBuf, String> {
    let p = PathBuf::from(path);
    let dir = if p.is_file() { p.parent().map(Path::to_path_buf).unwrap_or(p) } else { p };
    if dir.join("film.json").exists() { Ok(dir) } else { Err("That isn't a FilmCrafter film.".into()) }
}

/// Films: a story-first project (filmcrafter_engine.story). `create` makes a new film in the projects folder and `preview` / `read_file` need no film
/// at all; every other action works on an existing film folder. Reading and advice are free and local; nothing here is sent anywhere.
#[tauri::command]
async fn film(app: AppHandle, action: String, target: Option<String>, data: Value) -> Result<Value, String> {
    const ACTIONS: [&str; 12] = ["create", "status", "preview", "read_file", "add_version", "set_current", "lock", "as_is", "rec_set", "set_mode", "set_aspect", "reread"];
    if !ACTIONS.contains(&action.as_str()) {
        return Err("Unknown film action.".into());
    }
    let free = ["create", "preview", "read_file"].contains(&action.as_str());
    let dir = if free { projects_root(&app)? } else { film_dir(target.as_deref().unwrap_or(""))? };
    if !free { remember(&app, &dir); }
    let args: Vec<String> = vec!["-m".into(), "filmcrafter_engine.story".into(), action.clone(), dir.to_string_lossy().into(),
                                 "--data".into(), data.to_string()];
    let app2 = app.clone();
    let res = tauri::async_runtime::spawn_blocking(move || run_engine_result(&app2, "story", &args, &[])).await.map_err(err)??;
    if action == "create" {
        if let Some(d) = res["dir"].as_str() { remember(&app, Path::new(d)); }
    }
    Ok(res)
}

/// The Production Bible, Cast and World of a film (filmcrafter_engine.bible). Free and local: nothing is sent anywhere. Pictures are copied into the film from files the person chose.
#[tauri::command]
async fn film_bible(app: AppHandle, action: String, target: String, data: Value) -> Result<Value, String> {
    const ACTIONS: [&str; 14] = ["get", "seed", "update_rules", "update_sound_style", "set_voice_profile", "upsert", "remove", "add_state", "remove_state", "add_wardrobe", "add_media", "replace_media", "update_media", "remove_media"];
    if !ACTIONS.contains(&action.as_str()) {
        return Err("Unknown action.".into());
    }
    let dir = film_dir(&target)?;
    let args: Vec<String> = vec!["-m".into(), "filmcrafter_engine.bible".into(), action, dir.to_string_lossy().into(), "--data".into(), data.to_string()];
    tauri::async_runtime::spawn_blocking(move || run_engine_result(&app, "bible", &args, &[])).await.map_err(err)?
}

/// Scenes and shots of a film (filmcrafter_engine.shots): the breakdown, each Shot Contract, and editing them. Free and local; nothing is sent anywhere.
#[tauri::command]
async fn film_shots(app: AppHandle, action: String, target: String, data: Value) -> Result<Value, String> {
    const ACTIONS: [&str; 14] = ["get", "breakdown", "shot", "set", "add", "duplicate", "delete", "move", "merge", "split", "suggest", "command", "principles", "blocking"];
    if !ACTIONS.contains(&action.as_str()) {
        return Err("Unknown action.".into());
    }
    let dir = film_dir(&target)?;
    let args: Vec<String> = vec!["-m".into(), "filmcrafter_engine.shots".into(), action, dir.to_string_lossy().into(), "--data".into(), data.to_string()];
    tauri::async_runtime::spawn_blocking(move || run_engine_result(&app, "shots", &args, &[])).await.map_err(err)?
}

/// A take recorded in the app: the screen sends a 16-bit WAV as the raw request body and gets back the path of a file saved under ~/.filmcrafter/incoming, which the person's voice import then
/// copies into the film. Only a small, well-formed WAV is accepted; the name is made here (never taken from the screen), and old takes there are cleared after a day.
const MAX_TAKE_BYTES: usize = 64 * 1024 * 1024;

fn wav_ok(b: &[u8]) -> bool {
    b.len() > 44 && &b[0..4] == b"RIFF" && &b[8..12] == b"WAVE"
}

#[tauri::command]
fn save_voice_take(request: tauri::ipc::Request<'_>) -> Result<String, String> {
    let tauri::ipc::InvokeBody::Raw(bytes) = request.body() else { return Err("No recording was sent.".into()) };
    if bytes.len() > MAX_TAKE_BYTES {
        return Err("That recording is too long. Record a line or a scene at a time.".into());
    }
    if !wav_ok(bytes) {
        return Err("That recording is not a WAV file.".into());
    }
    let dir = dirs_home().ok_or("No home folder.")?.join(".filmcrafter").join("incoming");
    fs::create_dir_all(&dir).map_err(err)?;
    if let Ok(rd) = fs::read_dir(&dir) {
        for e in rd.flatten() {
            let old = e.file_name().to_string_lossy().starts_with("take-")
                && e.metadata().and_then(|m| m.modified()).ok().and_then(|t| t.elapsed().ok()).map(|a| a.as_secs() > 86_400).unwrap_or(false);
            if old {
                let _ = fs::remove_file(e.path());
            }
        }
    }
    let stamp = std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).map(|d| d.as_nanos()).unwrap_or(0);
    let path = dir.join(format!("take-{stamp}-{}.wav", std::process::id()));
    fs::write(&path, bytes).map_err(err)?;
    Ok(path.to_string_lossy().into_owned())
}

/// The person's own recorded voices (filmcrafter_engine.voiceover): matching file names to shots and people, attaching, removing. Nothing here spends money or sends a file anywhere;
/// the recordings are copied into the film and only read by the render when a video is made, after the price has been shown and confirmed.
#[tauri::command]
async fn film_voice(app: AppHandle, action: String, target: String, data: Value) -> Result<Value, String> {
    const ACTIONS: [&str; 4] = ["status", "match", "import", "remove"];
    if !ACTIONS.contains(&action.as_str()) {
        return Err("Unknown action.".into());
    }
    let dir = film_dir(&target)?;
    let args: Vec<String> = vec!["-m".into(), "filmcrafter_engine.voiceover".into(), action, dir.to_string_lossy().into(), "--data".into(), data.to_string()];
    tauri::async_runtime::spawn_blocking(move || run_engine_result(&app, "voice", &args, &[])).await.map_err(err)?
}

/// Custom voices with ElevenLabs (filmcrafter_engine.cast_voice): choose, design or clone a person's voice, and speak a written line in it. Only the ElevenLabs key is given to the engine here.
/// Looking things up is free; anything that uses the person's plan (speaking, previewing, designing a voice, keeping a designed voice, cloning) is refused by the engine itself unless the
/// call says `confirmed` (designing also needs `unknown_cost_accepted`, since its cost is not published), and cloning is refused without `consent` as well. Every such call is written to the
/// film's voice ledger; `ledger`, `ledger_resolve` and `set_limit` read and annotate that record.
#[tauri::command]
async fn film_cast_voice(app: AppHandle, action: String, target: String, data: Value) -> Result<Value, String> {
    const ACTIONS: [&str; 16] = ["status", "library", "set", "clear", "design", "design_save", "clone", "estimate", "speak", "preview", "takes", "use_take", "sample", "ledger", "ledger_resolve", "set_limit"];
    if !ACTIONS.contains(&action.as_str()) {
        return Err("Unknown action.".into());
    }
    let dir = film_dir(&target)?;
    let args: Vec<String> = vec!["-m".into(), "filmcrafter_engine.cast_voice".into(), action, dir.to_string_lossy().into(), "--data".into(), data.to_string()];
    let envs: Vec<(&str, String)> = keyring::Entry::new(KEY_SERVICE, "elevenlabs").and_then(|e| e.get_password()).ok().map(|k| vec![("ELEVENLABS_KEY", k)]).unwrap_or_default();
    tauri::async_runtime::spawn_blocking(move || run_engine_result(&app, "cast_voice", &args, &envs)).await.map_err(err)?
}

/// The film's sound effects and music libraries (filmcrafter_engine.audiolib): list, import (copies the chosen files into the film), describe and link, approve, remove (moves aside, never deletes) and
/// restore. Free and local: nothing is sent anywhere.
#[tauri::command]
async fn film_audio(app: AppHandle, action: String, target: String, data: Value) -> Result<Value, String> {
    const ACTIONS: [&str; 6] = ["list", "import", "update", "approve", "remove", "restore"];
    if !ACTIONS.contains(&action.as_str()) {
        return Err("Unknown audio action.".into());
    }
    let dir = film_dir(&target)?;
    let args: Vec<String> = vec!["-m".into(), "filmcrafter_engine.audiolib".into(), action, dir.to_string_lossy().into(), "--data".into(), data.to_string()];
    tauri::async_runtime::spawn_blocking(move || run_engine_result(&app, "audio", &args, &[])).await.map_err(err)?
}

/// Directing voices (filmcrafter_engine.voicedirect): the spoken version of a line, natural-delivery and voice suggestions (the writing AI is paid per call: the screen shows the estimate and asks
/// first), voicing a whole scene (the engine refuses without `confirmed` and a spending cap in credits) and the scene table read. Free actions never send anything.
#[tauri::command]
async fn film_voice_direct(app: AppHandle, action: String, target: String, data: Value) -> Result<Value, String> {
    const ACTIONS: [&str; 11] = ["performance", "performance_set", "performance_clear", "natural_estimate", "natural_suggest", "voices_estimate", "voices_suggest", "voices_match", "scene_plan", "scene_voice", "table_read"];
    if !ACTIONS.contains(&action.as_str()) {
        return Err("Unknown action.".into());
    }
    let dir = film_dir(&target)?;
    let args: Vec<String> = vec!["-m".into(), "filmcrafter_engine.voicedirect".into(), action, dir.to_string_lossy().into(), "--data".into(), data.to_string()];
    tauri::async_runtime::spawn_blocking(move || run_engine_result(&app, "voicedirect", &args, &provider_env())).await.map_err(err)?
}

/// Audio cues, the planned soundscape of a scene (filmcrafter_engine.audiocues): list, place, change, approve, remove and restore cues, free "quick ideas", and the sound director (the writing AI
/// proposes a soundscape; the screen shows the estimate and asks first). Nothing here makes sound or spends on sound; cues are plans.
#[tauri::command]
async fn film_cues(app: AppHandle, action: String, target: String, data: Value) -> Result<Value, String> {
    const ACTIONS: [&str; 10] = ["list", "add", "update", "approve", "remove", "restore", "refresh", "quick", "director_estimate", "director_suggest"];
    if !ACTIONS.contains(&action.as_str()) {
        return Err("Unknown cue action.".into());
    }
    let dir = film_dir(&target)?;
    let args: Vec<String> = vec!["-m".into(), "filmcrafter_engine.audiocues".into(), action, dir.to_string_lossy().into(), "--data".into(), data.to_string()];
    tauri::async_runtime::spawn_blocking(move || run_engine_result(&app, "cues", &args, &provider_env())).await.map_err(err)?
}

/// Making sound effects and music with a provider (filmcrafter_engine.audiogen): `providers`, `estimate`, `pending` and `rights` are free and send nothing; `generate` is refused by the engine
/// unless the request is confirmed, the rights are acknowledged and (when the provider does not publish a price) the unknown cost is accepted; a finished-but-slow Kie.ai task is fetched
/// with `check` (already paid for). Only the keys of the providers are given to the engine.
#[tauri::command]
async fn film_audiogen(app: AppHandle, action: String, target: String, data: Value) -> Result<Value, String> {
    const ACTIONS: [&str; 6] = ["providers", "estimate", "generate", "pending", "check", "rights"];
    if !ACTIONS.contains(&action.as_str()) {
        return Err("Unknown action.".into());
    }
    let dir = film_dir(&target)?;
    let args: Vec<String> = vec!["-m".into(), "filmcrafter_engine.audiogen".into(), action, dir.to_string_lossy().into(), "--data".into(), data.to_string()];
    tauri::async_runtime::spawn_blocking(move || run_engine_result(&app, "audiogen", &args, &provider_env())).await.map_err(err)?
}

/// The mix of the planned sound (filmcrafter_engine.audiomix): the settings (how far music dips under voices, a loudness target, the peak ceiling, muted lanes), and a preview of one scene's
/// mix. Free and local. The finished film's mix is made by the exporter.
#[tauri::command]
async fn film_mix(app: AppHandle, action: String, target: String, data: Value) -> Result<Value, String> {
    const ACTIONS: [&str; 3] = ["settings", "set_settings", "preview"];
    if !ACTIONS.contains(&action.as_str()) {
        return Err("Unknown mix action.".into());
    }
    let dir = film_dir(&target)?;
    let args: Vec<String> = vec!["-m".into(), "filmcrafter_engine.audiomix".into(), action, dir.to_string_lossy().into(), "--data".into(), data.to_string()];
    tauri::async_runtime::spawn_blocking(move || run_engine_result(&app, "mix", &args, &[])).await.map_err(err)?
}

/// The filmmaker's own materials (filmcrafter_engine.materials): storyboards, asset sheets, shot lists and notes. `scan` and `review` only read and make a plan; `apply` copies the ticked items into the film
/// (after a snapshot of its records). Free and local: nothing is bought or sent anywhere.
#[tauri::command]
async fn film_materials(app: AppHandle, action: String, target: String, data: Value) -> Result<Value, String> {
    const ACTIONS: [&str; 4] = ["scan", "apply", "review", "history"];
    if !ACTIONS.contains(&action.as_str()) {
        return Err("Unknown materials action.".into());
    }
    let dir = film_dir(&target)?;
    let args: Vec<String> = vec!["-m".into(), "filmcrafter_engine.materials".into(), action, dir.to_string_lossy().into(), "--data".into(), data.to_string()];
    tauri::async_runtime::spawn_blocking(move || run_engine_result(&app, "materials", &args, &[])).await.map_err(err)?
}

/// Action choreography (filmcrafter_engine.choreography): a fight, chase or sports moment planned beat by beat as short shots. Free, local and deterministic: nothing is sent anywhere.
/// `apply` adds the beats as NEW shots and never changes an existing one.
#[tauri::command]
async fn film_choreography(app: AppHandle, action: String, target: String, data: Value) -> Result<Value, String> {
    const ACTIONS: [&str; 7] = ["types", "generate", "update", "apply", "list", "remove", "get"];
    if !ACTIONS.contains(&action.as_str()) {
        return Err("Unknown action choreography action.".into());
    }
    let dir = film_dir(&target)?;
    let args: Vec<String> = vec!["-m".into(), "filmcrafter_engine.choreography".into(), action, dir.to_string_lossy().into(), "--data".into(), data.to_string()];
    tauri::async_runtime::spawn_blocking(move || run_engine_result(&app, "choreography", &args, &[])).await.map_err(err)?
}

/// Places nobody described (filmcrafter_engine.placecare): `status` lists them, `draft` fills in a first description from the story's own words (never over one that exists). Free and local.
#[tauri::command]
async fn film_placecare(app: AppHandle, action: String, target: String) -> Result<Value, String> {
    const ACTIONS: [&str; 2] = ["status", "draft"];
    if !ACTIONS.contains(&action.as_str()) {
        return Err("Unknown place action.".into());
    }
    let dir = film_dir(&target)?;
    let args: Vec<String> = vec!["-m".into(), "filmcrafter_engine.placecare".into(), action, dir.to_string_lossy().into()];
    tauri::async_runtime::spawn_blocking(move || run_engine_result(&app, "placecare", &args, &[])).await.map_err(err)?
}

/// Sound plan (filmcrafter_engine.audioplan): how each shot's voice will be made and why, what it will take, and the shot's own on/off setting for who speaks on screen. Free and local; it makes and buys nothing.
#[tauri::command]
async fn film_audioplan(app: AppHandle, action: String, target: String, data: Value) -> Result<Value, String> {
    const ACTIONS: [&str; 3] = ["report", "apply", "set"];
    if !ACTIONS.contains(&action.as_str()) {
        return Err("Unknown sound plan action.".into());
    }
    let dir = film_dir(&target)?;
    let args: Vec<String> = vec!["-m".into(), "filmcrafter_engine.audioplan".into(), action, dir.to_string_lossy().into(), "--data".into(), data.to_string()];
    tauri::async_runtime::spawn_blocking(move || run_engine_result(&app, "audioplan", &args, &[])).await.map_err(err)?
}

/// Readiness (filmcrafter_engine.readiness): what is still open in the film, in the order a film is made, and the one next step. Free, local and read-only.
#[tauri::command]
async fn film_readiness(app: AppHandle, action: String, target: String) -> Result<Value, String> {
    const ACTIONS: [&str; 1] = ["report"];
    if !ACTIONS.contains(&action.as_str()) {
        return Err("Unknown readiness action.".into());
    }
    let dir = film_dir(&target)?;
    let args: Vec<String> = vec!["-m".into(), "filmcrafter_engine.readiness".into(), action, dir.to_string_lossy().into()];
    tauri::async_runtime::spawn_blocking(move || run_engine_result(&app, "readiness", &args, &[])).await.map_err(err)?
}

/// Pacing (filmcrafter_engine.pacing): the rhythm of the film's cuts and where it works against the story. Free, local and read-only.
#[tauri::command]
async fn film_pacing(app: AppHandle, action: String, target: String) -> Result<Value, String> {
    const ACTIONS: [&str; 1] = ["report"];
    if !ACTIONS.contains(&action.as_str()) {
        return Err("Unknown pacing action.".into());
    }
    let dir = film_dir(&target)?;
    let args: Vec<String> = vec!["-m".into(), "filmcrafter_engine.pacing".into(), action, dir.to_string_lossy().into()];
    tauri::async_runtime::spawn_blocking(move || run_engine_result(&app, "pacing", &args, &[])).await.map_err(err)?
}

/// Composition (filmcrafter_engine.composition): `guide` says where the people sit in a shot's frame; `set` switches the wording in the requests on or off for the film. Free and local.
#[tauri::command]
async fn film_composition(app: AppHandle, action: String, target: String, data: Value) -> Result<Value, String> {
    const ACTIONS: [&str; 2] = ["guide", "set"];
    if !ACTIONS.contains(&action.as_str()) {
        return Err("Unknown composition action.".into());
    }
    let dir = film_dir(&target)?;
    let args: Vec<String> = vec!["-m".into(), "filmcrafter_engine.composition".into(), action, dir.to_string_lossy().into(), "--data".into(), data.to_string()];
    tauri::async_runtime::spawn_blocking(move || run_engine_result(&app, "composition", &args, &[])).await.map_err(err)?
}

/// What the film has cost so far (filmcrafter_engine.spending): by step and provider, reported amounts apart from estimates, units never added together. Free, local and read-only.
#[tauri::command]
async fn film_spending(app: AppHandle, action: String, target: String) -> Result<Value, String> {
    const ACTIONS: [&str; 1] = ["summary"];
    if !ACTIONS.contains(&action.as_str()) {
        return Err("Unknown spending action.".into());
    }
    let dir = film_dir(&target)?;
    let args: Vec<String> = vec!["-m".into(), "filmcrafter_engine.spending".into(), action, dir.to_string_lossy().into()];
    tauri::async_runtime::spawn_blocking(move || run_engine_result(&app, "spending", &args, &[])).await.map_err(err)?
}

/// What may be out of date because a voice or the planned sound changed after it was made (filmcrafter_engine.outdated). Free, local and read-only: it never changes, deletes or re-makes anything.
#[tauri::command]
async fn film_outdated(app: AppHandle, target: String) -> Result<Value, String> {
    let dir = film_dir(&target)?;
    let args: Vec<String> = vec!["-m".into(), "filmcrafter_engine.outdated".into(), "report".into(), dir.to_string_lossy().into()];
    tauri::async_runtime::spawn_blocking(move || run_engine_result(&app, "outdated", &args, &[])).await.map_err(err)?
}

/// The AI model registry (filmcrafter_engine.registry): `status`, `list` and `in_use` are free and read-only; `refresh` asks the providers' own model lists (free reads, the keys only reach their own
/// provider) and keeps the answer on this computer, apart from the app and from every film. It never changes a film.
#[tauri::command]
async fn model_registry(app: AppHandle, action: String, target: Option<String>, data: Value) -> Result<Value, String> {
    const ACTIONS: [&str; 4] = ["status", "list", "refresh", "in_use"];
    if !ACTIONS.contains(&action.as_str()) {
        return Err("Unknown action.".into());
    }
    let mut args: Vec<String> = vec!["-m".into(), "filmcrafter_engine.registry".into(), action.clone()];
    if action == "in_use" {
        args.push(film_dir(target.as_deref().unwrap_or(""))?.to_string_lossy().into());
    }
    args.push("--data".into());
    args.push(data.to_string());
    tauri::async_runtime::spawn_blocking(move || run_engine_result(&app, "registry", &args, &provider_env())).await.map_err(err)?
}

/// Before the app is updated: keep a snapshot of every recent film's own records and a copy of the app's settings (filmcrafter_engine.preupdate). Free and local; it only adds copies and
/// never touches a film, a key or the program. To be called by the update flow before anything is installed.
#[tauri::command]
async fn prepare_update(app: AppHandle, version: String) -> Result<Value, String> {
    let films: Vec<String> = recent_path(&app).and_then(|p| read_json(&p)).and_then(|v| serde_json::from_value(v).ok()).unwrap_or_default();
    let mut settings: Vec<String> = vec![];
    if let Some(p) = recent_path(&app) {
        settings.push(p.to_string_lossy().to_string());
        settings.push(p.with_file_name("hidden.json").to_string_lossy().to_string());
    }
    let data = json!({"version": version, "films": films, "settings": settings});
    let args: Vec<String> = vec!["-m".into(), "filmcrafter_engine.preupdate".into(), "snapshot".into(), "--data".into(), data.to_string()];
    tauri::async_runtime::spawn_blocking(move || run_engine_result(&app, "preupdate", &args, &[])).await.map_err(err)?
}

/// Making the film (filmcrafter_engine.make): builds the render project from the shots, tracks storyboard panels, keyframes and takes, locks and chooses. It never spends money:
/// pictures and video are queued with the render commands, after the app has shown the price and the person has confirmed it.
#[tauri::command]
async fn film_make(app: AppHandle, action: String, target: String, data: Value) -> Result<Value, String> {
    const ACTIONS: [&str; 9] = ["sync", "status", "tag", "choose", "lock", "reference", "import", "soundtrack", "progress"];
    if !ACTIONS.contains(&action.as_str()) {
        return Err("Unknown action.".into());
    }
    let dir = film_dir(&target)?;
    let args: Vec<String> = vec!["-m".into(), "filmcrafter_engine.make".into(), action, dir.to_string_lossy().into(), "--data".into(), data.to_string()];
    tauri::async_runtime::spawn_blocking(move || run_engine_result(&app, "make", &args, &[])).await.map_err(err)?
}

/// The Continuity Director for a film (filmcrafter_engine.filmcheck): advisory findings about drift between shots. Free and local; it never changes the film.
#[tauri::command]
async fn film_check(app: AppHandle, action: String, target: String, data: Value) -> Result<Value, String> {
    const ACTIONS: [&str; 3] = ["check", "decide", "apply"];
    if !ACTIONS.contains(&action.as_str()) {
        return Err("Unknown action.".into());
    }
    let dir = film_dir(&target)?;
    let args: Vec<String> = vec!["-m".into(), "filmcrafter_engine.filmcheck".into(), action, dir.to_string_lossy().into(), "--data".into(), data.to_string()];
    tauri::async_runtime::spawn_blocking(move || run_engine_result(&app, "filmcheck", &args, &[])).await.map_err(err)?
}

/// Hand the film to an editor (filmcrafter_engine.interchange): an EDL, OpenTimelineIO, Final Cut Pro XML, a shot manifest, subtitles and copies of the takes and soundtrack. Free and local.
#[tauri::command]
async fn film_interchange(app: AppHandle, target: String) -> Result<Value, String> {
    let dir = film_dir(&target)?;
    let args: Vec<String> = vec!["-m".into(), "filmcrafter_engine.interchange".into(), "write".into(), dir.to_string_lossy().into()];
    tauri::async_runtime::spawn_blocking(move || run_engine_result(&app, "interchange", &args, &[])).await.map_err(err)?
}

/// Optional writing help for Cast & World (filmcrafter_engine.assist): `estimate` shows the price and sends nothing; `suggest` asks the configured writing brain (OpenAI, OpenRouter, Ollama or LM Studio)
/// for a suggestion and returns it. It never changes the Bible: the person chooses what to use.
#[tauri::command]
async fn film_assist(app: AppHandle, action: String, target: String, data: Value) -> Result<Value, String> {
    const ACTIONS: [&str; 2] = ["estimate", "suggest"];
    if !ACTIONS.contains(&action.as_str()) {
        return Err("Unknown action.".into());
    }
    let dir = film_dir(&target)?;
    let args: Vec<String> = vec!["-m".into(), "filmcrafter_engine.assist".into(), action, dir.to_string_lossy().into(), "--data".into(), data.to_string()];
    tauri::async_runtime::spawn_blocking(move || run_engine_result(&app, "assist", &args, &provider_env())).await.map_err(err)?
}

#[tauri::command]
fn is_film(path: String) -> bool {
    let p = PathBuf::from(&path);
    p.join("film.json").exists() || p.parent().map(|d| d.join("film.json").exists() && p.extension().and_then(|x| x.to_str()) == Some(DOC_EXT)).unwrap_or(false)
}

/// Overnight on ComfyUI (filmcrafter_engine.overnight): start | stop | status. Free: ComfyUI only.
#[tauri::command]
async fn overnight(app: AppHandle, dir: String, action: String, confirmed: Option<bool>) -> Result<Value, String> {
    if !["start", "stop", "status"].contains(&action.as_str()) {
        return Err("Unknown action.".into());
    }
    let d = project_dir(&dir)?.to_string_lossy().to_string();
    let starts = action == "start";
    let app2 = app.clone();
    let mut args: Vec<String> = vec!["-m".into(), "filmcrafter_engine.overnight".into(), action, d];
    if confirmed.unwrap_or(false) { args.push("--confirmed".into()); }
    let res = tauri::async_runtime::spawn_blocking(move || run_engine_result(&app2, "overnight", &args, &provider_env())).await.map_err(err)??;
    if starts {
        ensure_renderer(app, dir);
    }
    Ok(res)
}


/// What the Director changed from the plan (filmcrafter_engine.director_audit): audit | split. Free and local; nothing is rendered.
#[tauri::command]
async fn director_audit(app: AppHandle, dir: String, action: String, data: Value) -> Result<Value, String> {
    const ACTIONS: [&str; 2] = ["audit", "split"];
    if !ACTIONS.contains(&action.as_str()) {
        return Err("Unknown action.".into());
    }
    let d = project_dir(&dir)?.to_string_lossy().to_string();
    let args: Vec<String> = vec!["-m".into(), "filmcrafter_engine.director_audit".into(), action, d, "--data".into(), data.to_string()];
    tauri::async_runtime::spawn_blocking(move || run_engine_result(&app, "director_audit", &args, &[])).await.map_err(err)?
}

/// Lyric captions on the exported film (filmcrafter_engine.captions): get | set | edit | preview. Free and local.
#[tauri::command]
async fn captions(app: AppHandle, dir: String, action: String, data: Value) -> Result<Value, String> {
    const ACTIONS: [&str; 5] = ["get", "set", "edit", "preview", "section"];
    if !ACTIONS.contains(&action.as_str()) {
        return Err("Unknown action.".into());
    }
    let d = project_dir(&dir)?.to_string_lossy().to_string();
    let args: Vec<String> = vec!["-m".into(), "filmcrafter_engine.captions".into(), action, d, "--data".into(), data.to_string()];
    tauri::async_runtime::spawn_blocking(move || run_engine_result(&app, "captions", &args, &[])).await.map_err(err)?
}

/// On-screen text over the exported film (filmcrafter_engine.overlays): list | add | update | remove | preview | sync | reorder | duplicate | history | undo | redo. Free and local.
#[tauri::command]
async fn overlays(app: AppHandle, dir: String, action: String, data: Value) -> Result<Value, String> {
    const ACTIONS: [&str; 12] = ["list", "add", "update", "remove", "preview", "sync", "reorder", "duplicate", "history", "undo", "redo", "key_suggest"];
    if !ACTIONS.contains(&action.as_str()) {
        return Err("Unknown action.".into());
    }
    let d = project_dir(&dir)?.to_string_lossy().to_string();
    let args: Vec<String> = vec!["-m".into(), "filmcrafter_engine.overlays".into(), action, d, "--data".into(), data.to_string()];
    tauri::async_runtime::spawn_blocking(move || run_engine_result(&app, "overlays", &args, &[])).await.map_err(err)?
}


/// The intro title card (filmcrafter_engine.titlecard): state | preview | make | remove | intro_shot. Free and local: it only writes on-screen text
/// settings (drawn at export) or adds an ordinary shot; a picture the user chose is copied into the project.
#[tauri::command]
async fn title_card(app: AppHandle, dir: String, action: String, data: Value) -> Result<Value, String> {
    const ACTIONS: [&str; 5] = ["state", "preview", "make", "remove", "intro_shot"];
    if !ACTIONS.contains(&action.as_str()) {
        return Err("Unknown action.".into());
    }
    let d = project_dir(&dir)?.to_string_lossy().to_string();
    let args: Vec<String> = vec!["-m".into(), "filmcrafter_engine.titlecard".into(), action, d, "--data".into(), data.to_string()];
    tauri::async_runtime::spawn_blocking(move || run_engine_result(&app, "titlecard", &args, &[])).await.map_err(err)?
}

/// Colour match between shots (filmcrafter_engine.colormatch): state | analyze | set | clear. Free and local: it only reads the takes and writes a small
/// correction per shot that the export applies; the takes themselves are never changed.
#[tauri::command]
async fn colour_match(app: AppHandle, dir: String, action: String, data: Value) -> Result<Value, String> {
    const ACTIONS: [&str; 4] = ["state", "analyze", "set", "clear"];
    if !ACTIONS.contains(&action.as_str()) {
        return Err("Unknown action.".into());
    }
    let d = project_dir(&dir)?.to_string_lossy().to_string();
    let args: Vec<String> = vec!["-m".into(), "filmcrafter_engine.colormatch".into(), action, d, "--data".into(), data.to_string()];
    tauri::async_runtime::spawn_blocking(move || run_engine_result(&app, "colormatch", &args, &[])).await.map_err(err)?
}

/// Colour Studio (filmcrafter_engine.grading): a grade for a shot, a scene or the film, and .cube LUTs. Free and local: it writes small records in the film's edit folder and the export applies them;
/// the takes themselves are never changed and nothing is sent anywhere. `lut_import` reads one .cube file you picked (checked strictly, then copied in).
#[tauri::command]
async fn grading(app: AppHandle, dir: String, action: String, data: Value) -> Result<Value, String> {
    const ACTIONS: [&str; 12] = ["state", "set_grade", "clear_grade", "lut_import", "lut_remove", "lut_favorite", "preset_save", "preset_apply", "preset_delete", "undo", "redo", "preview"];
    if !ACTIONS.contains(&action.as_str()) {
        return Err("Unknown action.".into());
    }
    let d = project_dir(&dir)?.to_string_lossy().to_string();
    let args: Vec<String> = vec!["-m".into(), "filmcrafter_engine.grading".into(), action, d, "--data".into(), data.to_string()];
    tauri::async_runtime::spawn_blocking(move || run_engine_result(&app, "grading", &args, &[])).await.map_err(err)?
}

/// Editing the film's cut (filmcrafter_engine.editing): read the sequence, make one named edit (cut, trim, delete, move, roll, markers...), snap, undo and redo. Free and local: it writes only the film's
/// edit record; takes, shot contracts and the screenplay are never touched, and nothing is sent anywhere.
#[tauri::command]
async fn editing(app: AppHandle, dir: String, action: String, data: Value) -> Result<Value, String> {
    const ACTIONS: [&str; 6] = ["sequence_get", "edit", "place_missing", "snap", "undo", "redo"];
    if !ACTIONS.contains(&action.as_str()) {
        return Err("Unknown action.".into());
    }
    let d = project_dir(&dir)?.to_string_lossy().to_string();
    let args: Vec<String> = vec!["-m".into(), "filmcrafter_engine.editing".into(), action, d, "--data".into(), data.to_string()];
    tauri::async_runtime::spawn_blocking(move || run_engine_result(&app, "editing", &args, &[])).await.map_err(err)?
}

/// Preview copies of big clips (filmcrafter_engine.proxies): status | build | clear. Free and local: it makes small copies in the project's cache for the player to use; the export never reads them
/// and the takes are never changed.
#[tauri::command]
async fn proxies(app: AppHandle, dir: String, action: String, data: Value) -> Result<Value, String> {
    const ACTIONS: [&str; 3] = ["status", "build", "clear"];
    if !ACTIONS.contains(&action.as_str()) {
        return Err("Unknown action.".into());
    }
    let d = project_dir(&dir)?.to_string_lossy().to_string();
    let args: Vec<String> = vec!["-m".into(), "filmcrafter_engine.proxies".into(), action, d, "--data".into(), data.to_string()];
    tauri::async_runtime::spawn_blocking(move || run_engine_result(&app, "proxies", &args, &[])).await.map_err(err)?
}

/// The Smart Editor (filmcrafter_engine.smart_editor): suggestions for the cut that explain themselves, with a real before and after preview. Free and local: nothing is sent anywhere and nothing is
/// rendered by a provider; `accept` writes the film's cut as one change (one undo takes it back), everything else only reads.
#[tauri::command]
async fn smart_editor(app: AppHandle, dir: String, action: String, data: Value) -> Result<Value, String> {
    const ACTIONS: [&str; 7] = ["recipes", "suggest", "ask", "accept", "reject", "reset_rejected", "preview"];
    if !ACTIONS.contains(&action.as_str()) {
        return Err("Unknown action.".into());
    }
    let d = project_dir(&dir)?.to_string_lossy().to_string();
    let args: Vec<String> = vec!["-m".into(), "filmcrafter_engine.smart_editor".into(), action, d, "--data".into(), data.to_string()];
    tauri::async_runtime::spawn_blocking(move || run_engine_result(&app, "smart_editor", &args, &[])).await.map_err(err)?
}

/// Creative presets (filmcrafter_engine.presets): a catalog of named settings that are previewed before they are applied, never overwrite your own choices, and can be undone, saved and shared as a file.
/// Free and local: only the film's own settings change; nothing is regenerated, no provider is called, nothing is sent anywhere.
#[tauri::command]
async fn presets(app: AppHandle, dir: String, action: String, data: Value) -> Result<Value, String> {
    const ACTIONS: [&str; 12] = ["catalog", "plan", "apply", "undo", "save_mine", "delete_mine", "favorite", "export", "import_file", "stack_get", "reframe_set", "set_pending"];
    if !ACTIONS.contains(&action.as_str()) {
        return Err("Unknown action.".into());
    }
    let d = project_dir(&dir)?.to_string_lossy().to_string();
    let args: Vec<String> = vec!["-m".into(), "filmcrafter_engine.presets".into(), action, d, "--data".into(), data.to_string()];
    tauri::async_runtime::spawn_blocking(move || run_engine_result(&app, "presets", &args, &[])).await.map_err(err)?
}

/// A series plan for a micro-drama (filmcrafter_engine.series): an editable scaffold made from an idea. Free and local; it writes the plan in the film's presets folder and nothing else.
#[tauri::command]
async fn series(app: AppHandle, dir: String, action: String, data: Value) -> Result<Value, String> {
    const ACTIONS: [&str; 9] = ["get", "create", "set_season", "set_episode", "reset_field", "resize", "report", "export_markdown", "make_films"];
    if !ACTIONS.contains(&action.as_str()) {
        return Err("Unknown action.".into());
    }
    let d = project_dir(&dir)?.to_string_lossy().to_string();
    let args: Vec<String> = vec!["-m".into(), "filmcrafter_engine.series".into(), action, d, "--data".into(), data.to_string()];
    tauri::async_runtime::spawn_blocking(move || run_engine_result(&app, "series", &args, &[])).await.map_err(err)?
}

/// Acting depth (filmcrafter_engine.acting): timed performance beats per shot, an emotional arc per character, signature gestures. Reading and editing are free and local;
/// `beats_write` and `arc_write` ask the Director (an AI call), and the screen shows their estimated price and asks first.
#[tauri::command]
async fn acting(app: AppHandle, dir: String, action: String, data: Value) -> Result<Value, String> {
    const ACTIONS: [&str; 11] = ["get", "beats_get", "beats_set", "beats_clear", "beats_estimate", "beats_write", "arc_set", "arc_clear", "arc_estimate", "arc_write", "business_set"];
    if !ACTIONS.contains(&action.as_str()) {
        return Err("Unknown action.".into());
    }
    let d = project_dir(&dir)?.to_string_lossy().to_string();
    let args: Vec<String> = vec!["-m".into(), "filmcrafter_engine.acting".into(), action, d, "--data".into(), data.to_string()];
    tauri::async_runtime::spawn_blocking(move || run_engine_result(&app, "acting", &args, &[])).await.map_err(err)?
}

/// The Performance Director (filmcrafter_engine.performance_director): what a person wants and hides, the scene Performance Breakdown, suggested beats and nudges. Free and local: nothing is sent
/// anywhere and nothing is rendered or charged; the screenplay, the shots and the Bible are only read.
#[tauri::command]
async fn performance_director(app: AppHandle, dir: String, action: String, data: Value) -> Result<Value, String> {
    const ACTIONS: [&str; 15] = ["characters_get", "character_set", "character_clear", "breakdown_get", "breakdown_set", "breakdown_reset", "breakdown_accept", "beats_suggest", "nudges_get", "nudge_set",
        "kind_options", "continuity_get", "continuity_dismiss", "model_labels", "delivery_hint"];
    if !ACTIONS.contains(&action.as_str()) {
        return Err("Unknown action.".into());
    }
    let d = project_dir(&dir)?.to_string_lossy().to_string();
    let args: Vec<String> = vec!["-m".into(), "filmcrafter_engine.performance_director".into(), action, d, "--data".into(), data.to_string()];
    tauri::async_runtime::spawn_blocking(move || run_engine_result(&app, "performance_director", &args, &[])).await.map_err(err)?
}

/// Sound layers for each shot (filmcrafter_engine.shotsound): get | set | delete | restore | reset | split | overview | levels. Free and local: a take's own sound is kept
/// apart from its picture and mixed at export; `split` separates voices from effects and music on this computer. The takes themselves are never changed.
#[tauri::command]
async fn shot_sound(app: AppHandle, dir: String, action: String, data: Value) -> Result<Value, String> {
    const ACTIONS: [&str; 8] = ["get", "set", "delete", "restore", "reset", "split", "overview", "levels"];
    if !ACTIONS.contains(&action.as_str()) {
        return Err("Unknown action.".into());
    }
    let d = project_dir(&dir)?.to_string_lossy().to_string();
    let args: Vec<String> = vec!["-m".into(), "filmcrafter_engine.shotsound".into(), action, d, "--data".into(), data.to_string()];
    tauri::async_runtime::spawn_blocking(move || run_engine_result(&app, "shotsound", &args, &[])).await.map_err(err)?
}

/// Layer styles and lyric layers (filmcrafter_engine.layerkit): styles | save | apply | delete_style | lyrics | lyrics_remove. Free and local: styles are kept in
/// the user's own app folder, lyric layers are on-screen text settings drawn at export.
#[tauri::command]
async fn layer_kit(app: AppHandle, dir: String, action: String, data: Value) -> Result<Value, String> {
    const ACTIONS: [&str; 14] = ["styles", "save", "apply", "delete_style", "lyrics", "lyrics_remove", "templates", "template_save", "template_apply", "template_delete", "template_remove", "builtin_list", "builtin_preview", "builtin_apply"];
    if !ACTIONS.contains(&action.as_str()) {
        return Err("Unknown action.".into());
    }
    let d = project_dir(&dir)?.to_string_lossy().to_string();
    let args: Vec<String> = vec!["-m".into(), "filmcrafter_engine.layerkit".into(), action, d, "--data".into(), data.to_string()];
    tauri::async_runtime::spawn_blocking(move || run_engine_result(&app, "layerkit", &args, &[])).await.map_err(err)?
}

/// Insert or remove a custom frame (filmcrafter_engine.customframe): state | insert | remove (only a frame you added). Adds an ordinary shot next to a shot you choose, using time the song already has;
/// a generated frame is priced and confirmed when you render it like any other shot, and a colour, picture or clip is free.
#[tauri::command]
async fn custom_frame(app: AppHandle, dir: String, action: String, data: Value) -> Result<Value, String> {
    const ACTIONS: [&str; 3] = ["state", "insert", "remove"];
    if !ACTIONS.contains(&action.as_str()) {
        return Err("Unknown action.".into());
    }
    let d = project_dir(&dir)?.to_string_lossy().to_string();
    let args: Vec<String> = vec!["-m".into(), "filmcrafter_engine.customframe".into(), action, d, "--data".into(), data.to_string()];
    tauri::async_runtime::spawn_blocking(move || run_engine_result(&app, "customframe", &args, &[])).await.map_err(err)?
}

/// Clean up unused videos and pictures (filmcrafter_engine.cleanup): scan | discard | restore | empty. Files only ever move to the project's own trash
/// folder (restorable); `empty` is the one step that deletes, and only touches that trash. The engine re-checks every path itself; the screen's list is not trusted.
#[tauri::command]
async fn cleanup(app: AppHandle, dir: String, action: String, data: Value) -> Result<Value, String> {
    const ACTIONS: [&str; 4] = ["scan", "discard", "restore", "empty"];
    if !ACTIONS.contains(&action.as_str()) {
        return Err("Unknown action.".into());
    }
    let d = project_dir(&dir)?.to_string_lossy().to_string();
    let args: Vec<String> = vec!["-m".into(), "filmcrafter_engine.cleanup".into(), action, d, "--data".into(), data.to_string()];
    tauri::async_runtime::spawn_blocking(move || run_engine_result(&app, "cleanup", &args, &[])).await.map_err(err)?
}

/// Camera and lighting choices for a shot (filmcrafter_engine.camera): vocab | get | set | reset. Free and local: it only changes the words
/// written into that shot's prompt; nothing is rendered or billed until you render the shot.
#[tauri::command]
async fn camera(app: AppHandle, dir: String, action: String, data: Value) -> Result<Value, String> {
    const ACTIONS: [&str; 6] = ["vocab", "get", "set", "reset", "suggest", "suggest_apply"];
    if !ACTIONS.contains(&action.as_str()) {
        return Err("Unknown action.".into());
    }
    let d = project_dir(&dir)?.to_string_lossy().to_string();
    let args: Vec<String> = vec!["-m".into(), "filmcrafter_engine.camera".into(), action, d, "--data".into(), data.to_string()];
    tauri::async_runtime::spawn_blocking(move || run_engine_result(&app, "camera", &args, &[])).await.map_err(err)?
}

/// The Lighting Designer (filmcrafter_engine.lighting): plan | apply | undo | moods. Free and local: it reads the mood of each shot and proposes light; applying writes
/// ordinary camera choices (never over one you made yourself unless asked) and Undo puts them back. Nothing is rendered or billed.
#[tauri::command]
async fn lighting(app: AppHandle, dir: String, action: String, data: Value) -> Result<Value, String> {
    const ACTIONS: [&str; 4] = ["plan", "apply", "undo", "moods"];
    if !ACTIONS.contains(&action.as_str()) {
        return Err("Unknown action.".into());
    }
    let d = project_dir(&dir)?.to_string_lossy().to_string();
    let args: Vec<String> = vec!["-m".into(), "filmcrafter_engine.lighting".into(), action, d, "--data".into(), data.to_string()];
    tauri::async_runtime::spawn_blocking(move || run_engine_result(&app, "lighting", &args, &[])).await.map_err(err)?
}

/// Send the exported film to Premiere Pro or DaVinci Resolve (filmcrafter_engine.editor_export): package. Writes one Final Cut Pro XML
/// import file (a bin with the finished film and the shots as timelines) into the project's exports folder. Free and local; it never
/// touches the editors themselves.
#[tauri::command]
async fn editor_export(app: AppHandle, dir: String, action: String, data: Value) -> Result<Value, String> {
    const ACTIONS: [&str; 1] = ["package"];
    if !ACTIONS.contains(&action.as_str()) {
        return Err("Unknown action.".into());
    }
    let d = project_dir(&dir)?.to_string_lossy().to_string();
    let args: Vec<String> = vec!["-m".into(), "filmcrafter_engine.editor_export".into(), action, d, "--data".into(), data.to_string()];
    tauri::async_runtime::spawn_blocking(move || run_engine_result(&app, "editor_export", &args, &[])).await.map_err(err)?
}

/// Fonts for captions and on-screen text (filmcrafter_engine.fonts): list | add. Free and local; `add` copies a chosen .ttf/.otf into the project.
#[tauri::command]
async fn fonts(app: AppHandle, dir: String, action: String, data: Value) -> Result<Value, String> {
    const ACTIONS: [&str; 2] = ["list", "add"];
    if !ACTIONS.contains(&action.as_str()) {
        return Err("Unknown action.".into());
    }
    let d = project_dir(&dir)?.to_string_lossy().to_string();
    let args: Vec<String> = vec!["-m".into(), "filmcrafter_engine.fonts".into(), action, d, "--data".into(), data.to_string()];
    tauri::async_runtime::spawn_blocking(move || run_engine_result(&app, "fonts", &args, &[])).await.map_err(err)?
}

/// Pictures made from the specs of references that have none (filmcrafter_engine.refgen): candidates | estimate | queue | use | discard |
/// status. `queue` needs the price confirmed on screen first; the render runner then sends the jobs like any other image job.
#[tauri::command]
async fn refgen(app: AppHandle, dir: String, action: String, data: Value) -> Result<Value, String> {
    const ACTIONS: [&str; 8] = ["candidates", "estimate", "queue", "use", "discard", "status", "cards", "own"];
    if !ACTIONS.contains(&action.as_str()) {
        return Err("Unknown action.".into());
    }
    let d = project_dir(&dir)?.to_string_lossy().to_string();
    let args: Vec<String> = vec!["-m".into(), "filmcrafter_engine.refgen".into(), action.clone(), d, "--data".into(), data.to_string()];
    let app2 = app.clone();
    let res = tauri::async_runtime::spawn_blocking(move || run_engine_result(&app2, "refgen", &args, &provider_env())).await.map_err(err)??;
    if action == "queue" {
        ensure_renderer(app, dir);
    }
    Ok(res)
}

/// Agent Studio's workflow ledger. It may queue a bounded first-scene proof only
/// on free local ComfyUI. Paid execution remains behind queue_render's spend token.
#[tauri::command]
async fn agent_studio(app: AppHandle, dir: String, action: String, data: Value) -> Result<Value, String> {
    const ACTIONS: [&str; 14] = ["state", "update_brief", "analyze", "accept_analysis", "create_plan", "approve", "request_changes", "impact", "inbox", "orchestrate", "plan_first_scene", "start_first_scene", "pause", "resume"];
    if !ACTIONS.contains(&action.as_str()) {
        return Err("Unknown Agent Studio action.".into());
    }
    let d = project_dir(&dir)?.to_string_lossy().to_string();
    let renderer_dir = d.clone();
    let app2 = app.clone();
    let start_renderer = matches!(action.as_str(), "start_first_scene" | "orchestrate");
    let env = if action == "analyze" { openai_env()? } else { vec![] };
    let args = vec!["-m".into(), "filmcrafter_engine.agent_studio".into(), action, d, "--data".into(), data.to_string()];
    let res = tauri::async_runtime::spawn_blocking(move || run_engine_result(&app2, "agent_studio", &args, &env)).await.map_err(err)??;
    if start_renderer { ensure_renderer(app, renderer_dir); }
    Ok(res)
}


/// Is there a newer FilmCrafter? (filmcrafter_engine.updates) One read-only request to the project's public release list; sends nothing about the user.
#[tauri::command]
async fn check_update(app: AppHandle) -> Result<Value, String> {
    let args: Vec<String> = vec!["-m".into(), "filmcrafter_engine.updates".into(), "check".into(), "--current".into(), env!("CARGO_PKG_VERSION").into()];
    tauri::async_runtime::spawn_blocking(move || run_engine_result(&app, "updates", &args, &[])).await.map_err(err)?
}

/// Provider diagnostics: free signed-in checks plus real job history. Never sends a render; never returns keys.
#[tauri::command]
async fn diagnostics(app: AppHandle) -> Result<Value, String> {
    let mut args: Vec<String> = vec!["-m".into(), "filmcrafter_engine.diagnostics".into(), "run".into(),
                                     projects_root(&app)?.to_string_lossy().to_string()];
    if let Some(r) = recent_path(&app).and_then(|p| read_json(&p)) {
        args.extend(r.as_array().into_iter().flatten().filter_map(|v| v.as_str().map(String::from)));
    }
    tauri::async_runtime::spawn_blocking(move || {
        run_engine_result(&app, "diagnostics", &args, &provider_env())
    }).await.map_err(err)?
}

// ---------- save / save as / launch ----------

/// Everything is written to disk as you work; Save confirms that and stamps the project.
#[tauri::command]
fn save_project(dir: String) -> Result<Value, String> {
    let d = project_dir(&dir)?;
    let now = std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).map(|d| d.as_secs()).unwrap_or(0);
    update_project(&d, json!({"saved": now}))?;
    Ok(json!({"saved": now}))
}

/// True when `inner` is `outer` or a folder somewhere inside it (both are made absolute first, so `..`, short names and links cannot hide it).
fn is_inside(inner: &Path, outer: &Path) -> bool {
    let a = fs::canonicalize(inner).unwrap_or_else(|_| inner.to_path_buf());
    let b = fs::canonicalize(outer).unwrap_or_else(|_| outer.to_path_buf());
    a.starts_with(&b)
}

/// Copy a folder. `avoid` is the folder being written to: it is never copied into itself, so saving a project to a folder inside the project cannot go round and round.
fn copy_tree(from: &Path, to: &Path, skip: &[&str], avoid: &Path) -> std::io::Result<()> {
    fs::create_dir_all(to)?;
    for e in fs::read_dir(from)?.flatten() {
        let name = e.file_name();
        let n = name.to_string_lossy();
        if skip.contains(&n.as_ref()) || n.ends_with(".tmp") {
            continue;
        }
        let (src, dst) = (e.path(), to.join(&name));
        if src.is_dir() {
            if is_inside(&src, avoid) { continue; }
            copy_tree(&src, &dst, &[], avoid)?
        } else {
            fs::copy(&src, &dst).map(|_| ())?
        }
    }
    Ok(())
}

/// Save a copy under a new name/location chosen in the standard Save dialog (`dest` = "…/Name.filmcrafter").
/// Media and takes come along; caches and old exports don't. Returns the new project folder.
#[tauri::command]
async fn save_project_as(app: AppHandle, dir: String, dest: String) -> Result<String, String> {
    let src = project_dir(&dir)?;
    let dest = PathBuf::from(dest);
    let title = dest.file_stem().and_then(|s| s.to_str()).map(String::from).ok_or("Choose a file name.")?;
    let parent = dest.parent().ok_or("Choose a folder.")?.to_path_buf();
    let new_dir = parent.join(slug(&title));
    if is_inside(&parent, &src) {
        return Err(format!("Choose a folder outside this project. \"{}\" is inside it, so a copy saved there would contain itself.", parent.display()));
    }
    if is_inside(&src, &new_dir) {
        return Err("Choose a different name: that folder is the project itself or holds it.".into());
    }
    if new_dir.exists() && fs::read_dir(&new_dir).map(|mut r| r.next().is_some()).unwrap_or(false) {
        return Err(format!("A folder named \"{}\" already exists there.", slug(&title)));
    }
    tauri::async_runtime::spawn_blocking(move || {
        copy_tree(&src, &new_dir, &["cache", "exports"], &new_dir).map_err(|e| format!("Couldn't copy the project: {e}"))?;
        fs::create_dir_all(new_dir.join("cache")).map_err(err)?;
        fs::create_dir_all(new_dir.join("exports")).map_err(err)?;
        for e in fs::read_dir(&new_dir).map_err(err)?.flatten() {
            if e.path().extension().and_then(|x| x.to_str()) == Some(DOC_EXT) {
                let _ = fs::remove_file(e.path());
            }
        }
        update_project(&new_dir, json!({"title": title}))?;
        ensure_doc(&new_dir);
        remember(&app, &new_dir);
        Ok(new_dir.to_string_lossy().to_string())
    }).await.map_err(err)?
}

/// A .filmcrafter or .filmpack file (or a .pulse from an earlier version) the app was launched with (double-click in Explorer), if any.
#[tauri::command]
fn launch_path() -> Option<String> {
    std::env::args().skip(1).find(|a| is_project_arg(a) || Path::new(a).join("project.json").exists())
}

fn is_project_arg(a: &str) -> bool {
    let l = a.to_lowercase();
    l.ends_with(&format!(".{DOC_EXT}")) || l.ends_with(".filmpack") || l.ends_with(".pulse")
}

/// Save a whole film as one .filmpack file (a zip of its folder: story, cast, shots, voices, pictures, videos, render project; without rebuildable caches).
#[tauri::command]
async fn pack_film(app: AppHandle, target: String, dest: String) -> Result<Value, String> {
    let d = film_dir(&target)?.to_string_lossy().to_string();
    tauri::async_runtime::spawn_blocking(move || {
        run_engine_result(&app, "pack", &["-m".into(), "filmcrafter_engine.packer".into(), "pack".into(), d, dest], &[])
    }).await.map_err(err)?
}

/// Save a render project on its own as one file (a zip of the folder, without rebuildable caches).
#[tauri::command]
async fn pack_project(app: AppHandle, dir: String, dest: String) -> Result<Value, String> {
    let d = project_dir(&dir)?.to_string_lossy().to_string();
    tauri::async_runtime::spawn_blocking(move || {
        run_engine_result(&app, "pack", &["-m".into(), "filmcrafter_engine.packer".into(), "pack".into(), d, dest], &[])
    }).await.map_err(err)?
}

/// Automatic project snapshots (the decisions, not the media): "backup" (skipped if nothing changed), "backups", "restore".
#[tauri::command]
async fn backups(app: AppHandle, dir: String, action: String, name: Option<String>) -> Result<Value, String> {
    if !["backup", "backups", "restore"].contains(&action.as_str()) {
        return Err("Unknown backup action.".into());
    }
    let d = project_dir(&dir)?.to_string_lossy().to_string();
    let mut args: Vec<String> = vec!["-m".into(), "filmcrafter_engine.packer".into(), action, d];
    if let Some(n) = name { args.push(n); }
    tauri::async_runtime::spawn_blocking(move || run_engine_result(&app, "backup", &args, &[])).await.map_err(err)?
}

/// Backups of a film's own records (script versions, Bible, cast, voices, film.json), separate from the render project's snapshots above: "make" (skipped if nothing changed), "list",
/// "verify", "restore" (checks the snapshot first, snapshots the present state, never deletes, never puts back the voice ledger). Free and local.
#[tauri::command]
async fn film_backup(app: AppHandle, action: String, target: String, name: Option<String>) -> Result<Value, String> {
    const ACTIONS: [&str; 4] = ["make", "list", "verify", "restore"];
    if !ACTIONS.contains(&action.as_str()) {
        return Err("Unknown backup action.".into());
    }
    let dir = film_dir(&target)?;
    let mut args: Vec<String> = vec!["-m".into(), "filmcrafter_engine.filmbackup".into(), action, dir.to_string_lossy().into()];
    if let Some(n) = name { args.push(n); }
    tauri::async_runtime::spawn_blocking(move || run_engine_result(&app, "film_backup", &args, &[])).await.map_err(err)?
}

/// Open a .filmpack file (or a .pulse from an earlier version): unpack it into the projects folder under a new name and return that folder.
#[tauri::command]
async fn open_pulse(app: AppHandle, path: String) -> Result<String, String> {
    let root = projects_root(&app)?.to_string_lossy().to_string();
    let app2 = app.clone();
    let res = tauri::async_runtime::spawn_blocking(move || {
        run_engine_result(&app2, "pack", &["-m".into(), "filmcrafter_engine.packer".into(), "unpack".into(), path, root], &[])
    }).await.map_err(err)??;
    let dir = res["dir"].as_str().ok_or("The project could not be unpacked.")?.to_string();
    remember(&app, Path::new(&dir));
    Ok(dir)
}

// ---------- project settings & reference media ----------

const ASPECTS: [&str; 9] = ["2.39:1", "21:9", "16:9", "4:3", "1:1", "4:5", "3:4", "9:16", "9:21"];

/// Project-wide render settings: aspect ratio, quality tier, lip-sync. Applies to every future render.
#[tauri::command]
fn set_project_settings(dir: String, settings: Value) -> Result<(), String> {
    let d = project_dir(&dir)?;
    let mut patch = serde_json::Map::new();
    if let Some(a) = settings["aspect_ratio"].as_str() {
        if !ASPECTS.contains(&a) {
            return Err("Unsupported aspect ratio.".into());
        }
        patch.insert("aspect_ratio".into(), json!(a));
    }
    if let Some(q) = settings["quality"].as_str() {
        if !["draft", "standard", "high", "max"].contains(&q) {
            return Err("Unknown quality.".into());
        }
        patch.insert("quality".into(), json!(q));
    }
    if let Some(t) = settings["title"].as_str() {
        let t = t.trim();
        if t.is_empty() || t.len() > 120 {
            return Err("Give the project a title (up to 120 characters).".into());
        }
        patch.insert("title".into(), json!(t));
    }
    if let Some(l) = settings["lip_sync"].as_str() {
        patch.insert("lip_sync".into(), json!(match l { "off" => "off", "closeups" => "closeups", _ => "auto" }));
    }
    // how a sung or spoken shot is made on a model that cannot take a first frame and the song's audio together: from the keyframe (the words only, the default) or from the audio
    if let Some(m) = settings["lip_sync_mode"].as_str() {
        patch.insert("lip_sync_mode".into(), json!(match m { "audio_first" => "audio_first", "auto" => "auto", _ => "first_frame" }));
    }
    // who is singing: a project whose vocal is a narrator or voice-over (nobody on screen sings it), and per-shot "this shot sings / does not sing" choices
    if let Some(v) = settings["vocalist"].as_str() {
        patch.insert("vocalist".into(), json!(if v == "offscreen" { "offscreen" } else { "onscreen" }));
    }
    if let Some(o) = settings["sing_shot"].as_object() {
        let id = o.get("id").and_then(|x| x.as_str()).unwrap_or("");
        let v = o.get("value").and_then(|x| x.as_str()).unwrap_or("auto");
        if id.is_empty() || id.len() > 40 || !["auto", "on", "off"].contains(&v) {
            return Err("Choose a shot and whether it sings.".into());
        }
        let mut map = read_json(&d.join("project.json")).and_then(|p| p.get("sing_shots").cloned()).and_then(|m| m.as_object().cloned()).unwrap_or_default();
        if v == "auto" { map.remove(id); } else { map.insert(id.to_string(), json!(v)); }
        patch.insert("sing_shots".into(), Value::Object(map));
    }
    update_project(&d, Value::Object(patch))
}

/// Copy a user-chosen image, video or audio file into the project so renders can use it.
/// Returns a `project:` reference that the renderer uploads to the provider when it's needed.
#[tauri::command]
fn import_reference(dir: String, path: String) -> Result<Value, String> {
    let d = project_dir(&dir)?;
    let src = PathBuf::from(&path);
    let meta = fs::metadata(&src).map_err(|_| "That file can't be read.".to_string())?;
    if meta.len() > 500 * 1024 * 1024 {
        return Err("That file is larger than 500 MB.".into());
    }
    let ext = src.extension().and_then(|e| e.to_str()).unwrap_or("").to_lowercase();
    let kind = match ext.as_str() {
        "png" | "jpg" | "jpeg" | "jfif" | "webp" | "gif" | "bmp" | "tif" | "tiff" => "image",
        "mp4" | "mov" | "webm" | "mkv" | "m4v" => "video",
        "mp3" | "wav" | "m4a" | "aac" | "flac" | "ogg" => "audio",
        _ => return Err("Use an image, video or audio file.".into()),
    };
    let refs = d.join("assets").join("refs");
    fs::create_dir_all(&refs).map_err(err)?;
    let stem = slug(src.file_stem().and_then(|s| s.to_str()).unwrap_or("reference"));
    let mut name = format!("{stem}.{ext}");
    let mut n = 2;
    while refs.join(&name).exists() {
        if fs::metadata(refs.join(&name)).map(|m| m.len()).ok() == Some(meta.len()) {
            break; // same file already imported
        }
        name = format!("{stem} {n}.{ext}");
        n += 1;
    }
    if !refs.join(&name).exists() {
        fs::copy(&src, refs.join(&name)).map_err(|e| format!("Couldn't copy the file: {e}"))?;
    }
    Ok(json!({"ref": format!("project:assets/refs/{name}"), "kind": kind, "name": name,
              "path": refs.join(&name).to_string_lossy()}))
}

/// Approve (or clear) a keyframe image for a shot; video renders of that shot then start from it.
#[tauri::command]
fn set_keyframe(dir: String, plan: String, shot: String, image: Option<String>) -> Result<(), String> {
    let d = project_dir(&dir)?;
    let path = d.join("keyframes.json");
    let mut kf = read_json(&path).unwrap_or_else(|| json!({}));
    if !kf[&plan].is_object() {
        kf[&plan] = json!({});
    }
    match image {
        Some(i) if i.starts_with("project:") => { kf[&plan][&shot] = json!(i); }
        Some(_) => return Err("Keyframes must be project images.".into()),
        None => { if let Some(o) = kf[&plan].as_object_mut() { o.remove(&shot); } }
    }
    write_json(&path, &kf)
}



// ---------- looks ----------

#[tauri::command]
fn list_styles() -> Result<Value, String> {
    read_json(&engine_dir().join("filmcrafter_engine").join("styles.json"))
        .map(|v| v["styles"].clone())
        .ok_or_else(|| "The look library is missing.".into())
}

/// look: {"style": id, "notes"?: str, "prompt"?: str, "avoid"?: str}. Applies to every future render.
#[tauri::command]
fn set_look(dir: String, look: Value) -> Result<(), String> {
    if !look["style"].is_string() {
        return Err("Choose a look.".into());
    }
    let d = project_dir(&dir)?;
    let old = read_json(&d.join("project.json")).map(|p| p["look"].clone()).unwrap_or(Value::Null);
    update_project(&d, json!({ "look": keep_own_looks(&old, look) }))
}

/// Changing the film's look must not lose the scenes and shots played in a look of their own (stylebible): the picker only knows the film's look, so they are carried over.
fn keep_own_looks(old: &Value, mut new: Value) -> Value {
    if let (Some(o), Some(n)) = (old.as_object(), new.as_object_mut()) {
        for key in ["scenes", "shots"] {
            if !n.contains_key(key) {
                if let Some(v) = o.get(key).filter(|v| v.as_object().is_some_and(|m| !m.is_empty())) {
                    n.insert(key.to_string(), v.clone());
                }
            }
        }
    }
    new
}

/// A look for one scene or one shot (filmcrafter_engine.stylebible): read | set_scene | set_shot. Free and local. It writes only the look's rules in project.json; nothing is rendered,
/// charged or replaced, and a new take still shows its price first.
#[tauri::command]
async fn stylebible(app: AppHandle, dir: String, action: String, data: Value) -> Result<Value, String> {
    const ACTIONS: [&str; 4] = ["read", "set_scene", "set_shot", "set_shot_options"];
    if !ACTIONS.contains(&action.as_str()) {
        return Err("Unknown action.".into());
    }
    let d = project_dir(&dir)?.to_string_lossy().to_string();
    let args: Vec<String> = vec!["-m".into(), "filmcrafter_engine.stylebible".into(), action, d, "--data".into(), data.to_string()];
    tauri::async_runtime::spawn_blocking(move || run_engine_result(&app, "stylebible", &args, &[])).await.map_err(err)?
}

// ---------- song-first creative development ----------

/// The AI brain's environment: the OpenAI key, or nothing when a local model (Ollama / LM Studio) is chosen.
fn openai_env() -> Result<Vec<(&'static str, String)>, String> {
    if brain_provider() == "anthropic" {
        let key = keyring::Entry::new(KEY_SERVICE, "anthropic").and_then(|e| e.get_password()).ok().filter(|k| !k.is_empty())
            .ok_or_else(|| "Add your Anthropic Claude API key in Settings, or choose another AI brain.".to_string())?;
        return Ok(vec![("ANTHROPIC_API_KEY", key)]);
    }
    if brain_provider() == "gemini" {
        let key = keyring::Entry::new(KEY_SERVICE, "google").and_then(|e| e.get_password()).ok().filter(|k| !k.is_empty())
            .ok_or_else(|| "Add your Google Gemini key in Settings, or choose another AI brain.".to_string())?;
        return Ok(vec![("GEMINI_API_KEY", key)]);
    }
    if brain_provider() == "openrouter" {
        // OpenRouter: one key, hundreds of cheaper models. The OpenAI key (if any) still goes along for the things that use OpenAI directly.
        let key = keyring::Entry::new(KEY_SERVICE, "openrouter").and_then(|e| e.get_password()).ok().filter(|k| !k.is_empty())
            .ok_or_else(|| "Add your OpenRouter key in Settings, or choose another AI brain.".to_string())?;
        let mut env = vec![("FILMCRAFTER_OPENROUTER_KEY", key)];
        if let Ok(k) = keyring::Entry::new(KEY_SERVICE, "openai").and_then(|e| e.get_password()) {
            env.push(("FILMCRAFTER_OPENAI_KEY", k));
        }
        return Ok(env);
    }
    let key = keyring::Entry::new(KEY_SERVICE, "openai").and_then(|e| e.get_password()).ok();
    if local_brain() {
        return Ok(key.map(|k| vec![("FILMCRAFTER_OPENAI_KEY", k)]).unwrap_or_default());
    }
    key.map(|k| vec![("FILMCRAFTER_OPENAI_KEY", k)])
        .ok_or_else(|| "Add your OpenAI key in Settings, or choose a local model (Ollama or LM Studio).".to_string())
}

/// Which AI brain ~/.filmcrafter/llm.json chose: "openai" (the default), "openrouter", "ollama" or "lmstudio".
fn brain_provider() -> String {
    dirs_home().map(|h| h.join(".filmcrafter").join("llm.json"))
        .and_then(|p| read_json(&p))
        .and_then(|v| v["provider"].as_str().map(String::from))
        .filter(|p| ["openai", "anthropic", "openrouter", "gemini", "ollama", "lmstudio"].contains(&p.as_str()))
        .unwrap_or_else(|| "openai".into())
}

/// A model on this computer (Ollama, LM Studio) serves the Director and friends: no key is needed.
fn local_brain() -> bool {
    matches!(brain_provider().as_str(), "ollama" | "lmstudio")
}

fn dirs_home() -> Option<PathBuf> {
    std::env::var_os("USERPROFILE").or_else(|| std::env::var_os("HOME")).map(PathBuf::from)
}

/// AI brain settings: get | set | models | test (see filmcrafter_engine.llm).
#[tauri::command]
async fn ai_brain(app: AppHandle, action: String, data: Option<Value>) -> Result<Value, String> {
    if !["get", "set", "models", "test"].contains(&action.as_str()) {
        return Err("Unknown action.".into());
    }
    let env = if action == "models" { provider_env() } else if action == "test" { openai_env().unwrap_or_default() } else { vec![] };
    tauri::async_runtime::spawn_blocking(move || {
        run_engine_result(&app, "brain", &["-m".into(), "filmcrafter_engine.llm".into(), action,
                                           data.unwrap_or_else(|| json!({})).to_string()], &env)
    }).await.map_err(err)?
}

/// Safe Agent Studio chat. The model may read project summaries and create suggestions;
/// paid work is never submitted here and writes remain reviewable unless explicitly enabled.
#[tauri::command]
async fn director_chat(app: AppHandle, dir: String, action: String, data: Option<Value>) -> Result<Value, String> {
    if !["turn", "proposals", "apply", "reject"].contains(&action.as_str()) { return Err("Unknown action.".into()); }
    let d = project_dir(&dir)?.to_string_lossy().to_string();
    let env = if action == "turn" { openai_env()? } else { vec![] };
    tauri::async_runtime::spawn_blocking(move || run_engine_result(&app, "director-chat", &[
        "-m".into(), "filmcrafter_engine.directorchat".into(), action, d, "--data".into(), data.unwrap_or_else(|| json!({})).to_string()
    ], &env)).await.map_err(err)?
}

// ---------- director command ----------

/// A natural-language note re-directs the matching shots (never story, order or timing). Undoable.
#[tauri::command]
async fn director_command(app: AppHandle, dir: String, note: String, selected: Option<String>,
                          playhead: Option<f64>) -> Result<Value, String> {
    let env = openai_env()?;
    let d = project_dir(&dir)?.to_string_lossy().to_string();
    tauri::async_runtime::spawn_blocking(move || {
        let mut a = vec!["-m".into(), "filmcrafter_engine.command".into(), "run".into(), d, "--note".into(), note];
        if let Some(s) = selected { a.extend(["--selected".into(), s]); }
        if let Some(p) = playhead { a.extend(["--playhead".into(), format!("{p:.2}")]); }
        run_engine_result(&app, "command", &a, &env)
    }).await.map_err(err)?
}

#[tauri::command]
async fn undo_command(app: AppHandle, dir: String, id: String) -> Result<Value, String> {
    let d = project_dir(&dir)?.to_string_lossy().to_string();
    tauri::async_runtime::spawn_blocking(move || {
        run_engine_result(&app, "command", &["-m".into(), "filmcrafter_engine.command".into(), "undo".into(), d,
                                             "--id".into(), id], &[])
    }).await.map_err(err)?
}

// ---------- export ----------

#[tauri::command]
async fn export_project(app: AppHandle, dir: String, preset: String, window: Option<Vec<f64>>) -> Result<Value, String> {
    let dir = project_dir(&dir)?.to_string_lossy().to_string();
    tauri::async_runtime::spawn_blocking(move || {
        let mut args: Vec<String> = vec!["-m".into(), "filmcrafter_engine.export".into(), dir, "--preset".into(), preset];
        if let Some(w) = window.filter(|w| w.len() == 2 && w.iter().all(|x| x.is_finite())) {   // a preview: only that part of the film
            args.push("--window".into());
            args.push(format!("{},{}", w[0], w[1]));
        }
        run_engine_result(&app, "export", &args, &[])
    }).await.map_err(err)?
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    LAUNCHED.get_or_init(std::time::Instant::now);
    tauri::Builder::default()
        // Double-clicking a project while the app is open focuses it and opens the project there.
        .plugin(tauri_plugin_single_instance::init(|app, args, _cwd| {
            if let Some(main) = app.get_webview_window("main") {
                let _ = main.show();
                let _ = main.unminimize();
                let _ = main.set_focus();
            }
            if let Some(p) = args.iter().skip(1).find(|a| is_project_arg(a)) {
                let _ = app.emit("open-path", p.clone());
            }
        }))
        .plugin(tauri_plugin_opener::init())
        .menu(|app| {
            use tauri::menu::{MenuBuilder, MenuItemBuilder, PredefinedMenuItem, SubmenuBuilder};
            let item = |id: &str, text: &str, accel: Option<&str>| {
                let mut b = MenuItemBuilder::with_id(id, text);
                if let Some(a) = accel {
                    b = b.accelerator(a);
                }
                b.build(app)
            };
            let file = SubmenuBuilder::new(app, "File")
                .item(&item("new", "New Film…", Some("CmdOrCtrl+N"))?)
                .item(&item("open", "Open Film…", Some("CmdOrCtrl+O"))?)
                .separator()
                .item(&item("save", "Save", Some("CmdOrCtrl+S"))?)
                .item(&item("save_pulse", "Save a Copy as One File (.filmpack)…", Some("CmdOrCtrl+Shift+S"))?)
                .item(&item("backups", "Restore from Backup…", None)?)
                .separator()
                .item(&item("export", "Export…", Some("CmdOrCtrl+E"))?)
                .item(&item("reveal", "Show in Explorer", None)?)
                .item(&item("close", "Close Film", Some("CmdOrCtrl+W"))?)
                .separator()
                .item(&item("settings", "Settings…", Some("CmdOrCtrl+,"))?)
                .item(&PredefinedMenuItem::quit(app, Some("Exit"))?)
                .build()?;
            let view = SubmenuBuilder::new(app, "View")
                .item(&item("mode_simple", "Simple Mode", Some("CmdOrCtrl+1"))?)
                .item(&item("mode_director", "Director Mode", Some("CmdOrCtrl+2"))?)
                .item(&item("inspector", "Toggle Inspector", Some("CmdOrCtrl+I"))?)
                .build()?;
            let direct = SubmenuBuilder::new(app, "Direct")
                .item(&item("command", "Director Command…", Some("CmdOrCtrl+K"))?)
                .build()?;
            let help = SubmenuBuilder::new(app, "Help")
                .item(&item("help", "Documentation", Some("F1"))?)
                .build()?;
            let mut bar = MenuBuilder::new(app);
            #[cfg(target_os = "macos")]
            {
                let app_menu = SubmenuBuilder::new(app, "FilmCrafter")
                    .item(&PredefinedMenuItem::about(app, Some("About FilmCrafter"), None)?)
                    .separator()
                    .item(&item("settings_mac", "Settings…", Some("CmdOrCtrl+,"))?)
                    .separator()
                    .item(&PredefinedMenuItem::hide(app, None)?)
                    .item(&PredefinedMenuItem::hide_others(app, None)?)
                    .item(&PredefinedMenuItem::show_all(app, None)?)
                    .separator()
                    .item(&PredefinedMenuItem::quit(app, None)?)
                    .build()?;
                let edit = SubmenuBuilder::new(app, "Edit")
                    .item(&PredefinedMenuItem::undo(app, None)?)
                    .item(&PredefinedMenuItem::redo(app, None)?)
                    .separator()
                    .item(&PredefinedMenuItem::cut(app, None)?)
                    .item(&PredefinedMenuItem::copy(app, None)?)
                    .item(&PredefinedMenuItem::paste(app, None)?)
                    .item(&PredefinedMenuItem::select_all(app, None)?)
                    .build()?;
                bar = bar.item(&app_menu).item(&file).item(&edit);
            }
            #[cfg(not(target_os = "macos"))]
            {
                bar = bar.item(&file);
            }
            bar.item(&view).item(&direct).item(&help).build()
        })
        .on_menu_event(|app, event| {
            let id = event.id().0.clone();
            let _ = app.emit("menu", if id == "settings_mac" { "settings".to_string() } else { id });
        })
        .plugin(tauri_plugin_dialog::init())
        .setup(|app| {
            init_engine(app.handle());
            if let Ok(root) = projects_root(app.handle()) { allow_media(app.handle(), &root); }
            if let Some(p) = recent_path(app.handle()) {
                for d in read_json(&p).and_then(|v| serde_json::from_value::<Vec<String>>(v).ok()).unwrap_or_default() { allow_media(app.handle(), Path::new(&d)); }
            }
            // Safety net: never leave the user staring at the splash if the UI fails to report ready.
            let handle = app.handle().clone();
            std::thread::spawn(move || {
                std::thread::sleep(std::time::Duration::from_secs(8));
                if let Some(main) = handle.get_webview_window("main") {
                    if !main.is_visible().unwrap_or(true) {
                        let _ = main.show();
                    }
                }
                if let Some(splash) = handle.get_webview_window("splashscreen") {
                    let _ = splash.close();
                }
            });
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            key_status, set_key, delete_key, splash_close, list_projects, load_project,
            ensure_renderer, render_catalog, render_preview,
            queue_render, confirm_spend, resolve_job, export_project, list_styles, set_look, app_ready, render_estimate,
            save_project, save_project_as, pack_film, backups, film_backup, frames, film, film_bible, film_shots, film_make, film_voice, film_cast_voice, film_voice_direct, film_audio, film_cues, film_audiogen, film_mix, film_materials, film_choreography, film_placecare, film_audioplan, film_readiness, film_pacing, film_composition, film_spending, film_outdated, model_registry, prepare_update, save_voice_take, film_check, film_assist, film_interchange, is_film, launch_path, engine_status, setup_engine, engine_setup_size, set_project_settings, import_reference, set_keyframe, director_command, undo_command, library, parse_action, providers,
            set_onboarding, adopt_script, lighting, ai_brain, director_chat, budget, diagnostics, media, continuity, performance, routing, local_models, supervisor, direction_library, director_style, recents, hidden_count, pack_project, open_pulse, golden, lipsync_check, review_backlog, comfy_setup, comfy_install, compose, overnight, refgen, agent_studio, overlays, captions, director_audit, fonts, editor_export, camera, check_update, stylebible, performance_director, title_card, cleanup, custom_frame, layer_kit, colour_match, grading, editing, proxies, smart_editor, presets, series, shot_sound, acting, track, upscale, proof, shot_history, retry_cheaper, keyframe_set, hand_fix
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}

#[cfg(test)]
fn load_project_data(d: &Path) -> Option<Value> {
    Some(json!({
        "project": read_json(&d.join("project.json"))?,
        "song_map": read_json(&d.join("songmap.json")),
        "production": read_json(&d.join("production.json")),
        "song_path": d.join("song.wav").to_string_lossy(),
    }))
}

#[cfg(test)]
mod tests {
    use super::*;

    fn scratch(tag: &str) -> PathBuf {
        let d = std::env::temp_dir().join(format!("pf-thumb-{}-{}-{}", tag, std::process::id(), std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).unwrap().as_nanos()));
        fs::create_dir_all(d.join("render").join("keyframes")).unwrap();
        d
    }

    #[test]
    fn a_film_card_shows_the_first_chosen_keyframe_and_nothing_a_hand_edited_file_points_elsewhere() {
        let d = scratch("ok");
        fs::write(d.join("render").join("keyframes").join("b.png"), b"x").unwrap();
        fs::write(d.join("render").join("keyframes").join("a.jpg"), b"x").unwrap();
        fs::write(d.join("render").join("notes.txt"), b"x").unwrap();
        fs::write(d.join("secret.png"), b"x").unwrap();
        let kf = |v: Value| fs::write(d.join("render").join("keyframes.json"), serde_json::to_string(&v).unwrap()).unwrap();
        assert!(film_thumb(&d).is_none(), "no record: no picture");
        kf(json!({"production": {"S01-02": "project:keyframes/b.png", "S01-01": "project:keyframes/a.jpg"}}));
        assert!(film_thumb(&d).unwrap().ends_with("a.jpg"), "the first shot by its id");
        kf(json!({"production": {"S01-01": "project:keyframes/missing.png", "S01-02": "project:keyframes/b.png"}}));
        assert!(film_thumb(&d).unwrap().ends_with("b.png"), "a missing file is skipped");
        for bad in ["project:../secret.png", "../secret.png", "project:/etc/passwd", "project:C:/Windows/win.png", "project:notes.txt", "project:", "project:keyframes/..\\..\\secret.png"] {
            kf(json!({"production": {"S01-01": bad}}));
            assert!(film_thumb(&d).is_none(), "refused: {bad}");
        }
        kf(json!({"production": {"S01-01": 5, "S01-02": null}}));
        assert!(film_thumb(&d).is_none(), "not text: skipped");
        fs::write(d.join("render").join("keyframes.json"), b"not json").unwrap();
        assert!(film_thumb(&d).is_none(), "damaged: no picture, no crash");
        let _ = fs::remove_dir_all(&d);
    }

    #[test]
    fn changing_the_films_look_keeps_the_looks_of_scenes_and_shots() {
        let old = json!({"style": "claymation", "scenes": {"6": "live-action"}, "shots": {"S06-02": "anime"}, "notes": "n"});
        let kept = keep_own_looks(&old, json!({"style": "noir"}));
        assert_eq!(kept, json!({"style": "noir", "scenes": {"6": "live-action"}, "shots": {"S06-02": "anime"}}));
        // a key the new look already has is left as it is (the other is still carried over); an old look without any, or none at all, adds nothing
        assert_eq!(keep_own_looks(&old, json!({"style": "noir", "shots": {}})), json!({"style": "noir", "shots": {}, "scenes": {"6": "live-action"}}));
        assert_eq!(keep_own_looks(&old, json!({"style": "noir", "shots": {"S01-01": "noir"}, "scenes": {}})), json!({"style": "noir", "shots": {"S01-01": "noir"}, "scenes": {}}));
        assert_eq!(keep_own_looks(&json!({"style": "x"}), json!({"style": "noir"})), json!({"style": "noir"}));
        assert_eq!(keep_own_looks(&Value::Null, json!({"style": "noir"})), json!({"style": "noir"}));
    }

    #[test]
    fn a_spend_token_is_single_use_bound_to_its_batch_and_expires() {
        use std::time::{Duration, Instant};
        let t0 = Instant::now();
        let shots = vec!["s2".to_string(), "s1".to_string()];
        let key = spend_key("D:/p", "fal", "video", &shots);
        assert_eq!(key, spend_key("D:/p", "fal", "video", &["s1".to_string(), "s2".to_string()]), "order does not matter");
        for other in [spend_key("D:/q", "fal", "video", &shots), spend_key("D:/p", "kie", "video", &shots), spend_key("D:/p", "fal", "image", &shots),
                      spend_key("D:/p", "fal", "video", &["s1".to_string()]), spend_key("D:/p", "fal", "video", &["s1".to_string(), "s2".to_string(), "s3".to_string()])] {
            let mut l = SpendLedger::default();
            l.mint("tok".into(), key.clone(), t0);
            assert!(!l.redeem("tok", &other, t0), "a token for one batch must not pay for another");
            assert!(!l.redeem("tok", &key, t0), "and a failed try spends it");
        }
        let mut l = SpendLedger::default();
        l.mint("tok".into(), key.clone(), t0);
        assert!(!l.redeem("nope", &key, t0));
        assert!(l.redeem("tok", &key, t0 + Duration::from_secs(5)));
        assert!(!l.redeem("tok", &key, t0 + Duration::from_secs(6)), "single use");
        l.mint("old".into(), key.clone(), t0);
        assert!(!l.redeem("old", &key, t0 + SPEND_TTL), "expired");
    }

    #[test]
    fn the_ledger_stays_small() {
        let t0 = std::time::Instant::now();
        let mut l = SpendLedger::default();
        for i in 0..(SPEND_MAX_OPEN + 20) {
            l.mint(format!("t{i}"), "k".into(), t0);
        }
        assert!(l.open.len() <= SPEND_MAX_OPEN + 1);
        assert!(!l.redeem("t0", "k", t0), "the oldest was dropped");
        assert!(l.redeem(&format!("t{}", SPEND_MAX_OPEN + 19), "k", t0));
    }

    #[test]
    fn byteplus_has_a_key_slot_a_name_and_no_free_pass() {
        assert!(PROVIDERS.contains(&"byteplus"));
        assert_eq!(provider_name("byteplus"), "BytePlus");
        assert_eq!(provider_name("kie"), "Kie.ai");
        assert_eq!(provider_name("something else"), "provider");
        assert!(redeem_spend(None, "d", "byteplus", "image", &["s1".into()]).is_err(), "no token, no spending");
    }

    #[test]
    fn tokens_are_random_hex_and_only_comfyui_is_exempt() {
        let (a, b) = (new_spend_token().unwrap(), new_spend_token().unwrap());
        assert_eq!(a.len(), 32);
        assert!(a.chars().all(|c| c.is_ascii_hexdigit()));
        assert_ne!(a, b);
        assert!(spend_free("comfyui"));
        for p in ["fal", "kie", "google", "openai", "byteplus", "own", ""] {
            assert!(!spend_free(p), "{p}");
        }
        assert!(redeem_spend(None, "d", "comfyui", "video", &[]).is_ok());
        assert!(redeem_spend(None, "d", "fal", "video", &["s1".into()]).is_err(), "no token, no spending");
        assert!(redeem_spend(Some("bogus"), "d", "kie", "image", &["s1".into()]).is_err());
        let key = spend_key("d", "fal", "video", &["s1".to_string()]);
        SPEND.lock().unwrap().mint("good-token".into(), key, std::time::Instant::now());
        assert!(redeem_spend(Some("good-token"), "d", "fal", "video", &["s1".into()]).is_ok());
        assert!(redeem_spend(Some("good-token"), "d", "fal", "video", &["s1".into()]).is_err(), "single use");
    }

    #[test]
    fn a_recorded_take_must_be_a_wav() {
        let mut w = b"RIFF".to_vec();
        w.extend([0u8; 4]);
        w.extend(b"WAVE");
        w.extend([0u8; 40]);
        assert!(wav_ok(&w));
        assert!(!wav_ok(b"RIFF"));
        assert!(!wav_ok(&[0u8; 100]));
    }

    #[test]
    fn the_webview_may_read_only_the_projects_folder_and_the_apps_own_data_not_the_whole_home_folder() {
        let conf: Value = serde_json::from_str(include_str!("../tauri.conf.json")).unwrap();
        let scope: Vec<String> = conf["app"]["security"]["assetProtocol"]["scope"].as_array().unwrap().iter().map(|v| v.as_str().unwrap().to_string()).collect();
        for s in &scope {
            assert!(!matches!(s.as_str(), "$HOME/**" | "$DOCUMENT/**" | "**" | "/**" | "$DESKTOP/**" | "$DOWNLOAD/**"), "too wide: {s}");
        }
        assert!(scope.iter().any(|s| s == "$DOCUMENT/FilmCrafter/**"), "the projects folder must stay readable");
    }

    #[test]
    fn keychain_round_trip() {
        // Uses a throwaway entry so a real provider key is never touched.
        let e = keyring::Entry::new("filmcrafter-selftest", "probe").unwrap();
        e.set_password("s3cret-value").unwrap();
        assert_eq!(e.get_password().unwrap(), "s3cret-value");
        e.delete_credential().unwrap();
        assert!(matches!(e.get_password(), Err(keyring::Error::NoEntry)));
    }

    #[test]
    fn a_folder_is_inside_itself_and_what_it_holds_and_nothing_else() {
        let base = std::env::temp_dir().join(format!("pf-inside-{}", std::process::id()));
        let (a, b) = (base.join("proj"), base.join("proj copy"));
        fs::create_dir_all(a.join("assets")).unwrap();
        fs::create_dir_all(&b).unwrap();
        assert!(is_inside(&a, &a) && is_inside(&a.join("assets"), &a));
        assert!(!is_inside(&b, &a), "a sibling whose name starts the same is not inside");
        assert!(!is_inside(&a, &a.join("assets")));
        assert!(is_inside(&a.join("assets").join("..").join("assets"), &a), "dots do not hide it");
        let _ = fs::remove_dir_all(&base);
    }

    #[test]
    fn copying_a_project_into_a_folder_inside_it_does_not_copy_it_into_itself_again_and_again() {
        let base = std::env::temp_dir().join(format!("pf-selfcopy-{}", std::process::id()));
        let src = base.join("proj");
        fs::create_dir_all(src.join("assets")).unwrap();
        fs::write(src.join("project.json"), "{}").unwrap();
        fs::write(src.join("assets").join("a.png"), "x").unwrap();
        let dst = src.join("copy");
        copy_tree(&src, &dst, &[], &dst).unwrap();
        assert!(dst.join("project.json").exists() && dst.join("assets").join("a.png").exists());
        assert!(!dst.join("copy").exists(), "the copy must not contain a copy of itself");
        let deepest = walk_depth(&base);
        assert!(deepest <= 4, "no runaway nesting, got {deepest}");
        let _ = fs::remove_dir_all(&base);
    }

    fn walk_depth(p: &Path) -> usize {
        fs::read_dir(p).map(|r| r.flatten().filter(|e| e.path().is_dir()).map(|e| 1 + walk_depth(&e.path())).max().unwrap_or(0)).unwrap_or(0)
    }

    #[test]
    fn slug_is_filesystem_safe() {
        assert_eq!(slug("Exit Plan: Remix/2"), "Exit Plan Remix 2");
        assert_eq!(slug("???"), "Untitled");
    }

    #[test]
    fn loads_a_real_project_when_present() {
        let Some(docs) = std::env::var_os("USERPROFILE").map(|h| PathBuf::from(h).join("Documents/FilmCrafter/Exit Plan.filmcrafter")) else { return };
        if !docs.exists() { return; }
        let v = load_project_data(&docs).unwrap();
        assert_eq!(v["project"]["title"], "Exit Plan");
        assert!(v["song_map"]["peaks"].as_array().unwrap().len() == 2000);
        let shots: usize = v["production"]["scenes"].as_array().unwrap().iter()
            .map(|s| s["shots"].as_array().unwrap().len()).sum();
        assert_eq!(shots, 70);
        assert!(Path::new(v["song_path"].as_str().unwrap()).exists());
    }

    #[test]
    fn only_a_real_project_folder_is_accepted() {
        let base = std::env::temp_dir().join(format!("pf-projdir-{}", std::process::id()));
        let _ = fs::remove_dir_all(&base);
        fs::create_dir_all(&base).unwrap();
        assert!(project_dir(base.to_str().unwrap()).is_err(), "a folder without project.json is not a project");
        assert!(project_dir(base.join("nowhere").to_str().unwrap()).is_err(), "a folder that does not exist is not a project");
        assert!(project_dir("C:/Windows").is_err() && project_dir("/etc").is_err(), "system folders are not projects");
        fs::write(base.join("project.json"), "{}").unwrap();
        assert_eq!(project_dir(base.to_str().unwrap()).unwrap(), base);
        assert_eq!(project_dir(base.join("project.json").to_str().unwrap()).unwrap(), base, "a file inside a project names the project");
        let _ = fs::remove_dir_all(&base);
    }

    #[test]
    fn engine_python_exists() {
        let Some((_, py)) = dev_engine() else { return }; // CI / installed layouts have no dev venv
        assert!(py.exists(), "engine venv missing at {:?}", py);
    }
}
