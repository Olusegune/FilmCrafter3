"""Real-speech checks of the new FilmCrafter engine modules (Windows text-to-speech voices as recordings, Windows' offline recognizer as a rough intelligibility check). Prints measurements only.

Windows only. Run it twice from the repository root: the first run queues every recording for the recognizer, `powershell -File scripts/real_speech_check/asr_batch.ps1` transcribes them (the recognizer
cannot be started from Python: it hangs), and the second run prints the measurements. See docs/REAL_TESTS.md."""
import json, os, re, shutil, subprocess, sys, time
import numpy as np, soundfile as sf
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "analysis"))
from filmcrafter_engine import adrsync as A, audioqa as Q, bible, proaudio as P, shots as S, story, voiceover as V, shotsound

HERE = os.path.dirname(os.path.abspath(__file__))
for need_wav in ("david", "zira"):                                       # the two recordings are made with Windows' own voices the first time (tts.ps1)
    if not os.path.isfile(os.path.join(HERE, f"{need_wav}.wav")):
        voice = {"david": "Microsoft David Desktop", "zira": "Microsoft Zira Desktop"}[need_wav]
        subprocess.run(["powershell", "-NoProfile", "-File", os.path.join(HERE, "tts.ps1"), "-Voice", voice, "-Text", "I did not think you would come back, but here you are, standing in my kitchen, and I do not know what to say.",
                        "-Out", os.path.join(HERE, f"{need_wav}.wav")], check=True)
WORK = os.path.join(HERE, "work")
shutil.rmtree(WORK, ignore_errors=True); os.makedirs(WORK)
TEXT = "I did not think you would come back, but here you are, standing in my kitchen, and I do not know what to say."


import hashlib
CACHE = os.path.join(HERE, "transcripts.json")
PENDING = os.path.join(HERE, "pending")
cache = json.load(open(CACHE, encoding="utf-8-sig")) if os.path.isfile(CACHE) else {}
need = []


def asr(path):
    """A transcript from Windows' offline recognizer, by the file's content. The recognizer is run by asr_batch.ps1 (it hangs when started from here), so a file not yet transcribed is queued and the script is run again."""
    os.makedirs(PENDING, exist_ok=True)
    tmp = os.path.join(WORK, "asr_tmp.wav")                              # the recognizer wants plain 16-bit mono (a 24-bit file hangs it), so every file is converted first
    subprocess.run([P._ffmpeg(), "-y", "-hide_banner", "-loglevel", "error", "-i", path, "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", tmp], check=True)
    key = hashlib.sha1(open(tmp, "rb").read()).hexdigest()[:16]
    if key in cache:
        return cache[key]
    shutil.copyfile(tmp, os.path.join(PENDING, key + ".wav"))
    need.append(key)
    return ""


def words(t):
    return re.sub(r"[^a-z' ]", " ", t.lower()).split()


def wer(ref, hyp):
    r, h = words(ref), words(hyp)
    d = np.zeros((len(r) + 1, len(h) + 1), dtype=int)
    d[:, 0] = range(len(r) + 1); d[0, :] = range(len(h) + 1)
    for i in range(1, len(r) + 1):
        for j in range(1, len(h) + 1):
            d[i, j] = min(d[i - 1, j] + 1, d[i, j - 1] + 1, d[i - 1, j - 1] + (r[i - 1] != h[j - 1]))
    return round(d[-1, -1] / max(1, len(r)), 3)


def f0(path):
    x, r = sf.read(path); x = x if x.ndim == 1 else x[:, 0]
    out = []
    for i in range(0, min(len(x), r * 12) - 2048, 1024):
        w = x[i:i + 2048] - np.mean(x[i:i + 2048])
        if np.sqrt(np.mean(w ** 2)) < 0.02: continue
        ac = np.correlate(w, w, "full")[2047:]
        lo, hi = int(r / 400), int(r / 70)
        k = lo + int(np.argmax(ac[lo:hi]))
        if ac[k] > 0.4 * ac[0]: out.append(r / k)
    return round(float(np.median(out)), 1) if out else None


def dur(path):
    return round(sf.info(path).duration, 2)


def film(name):
    d = story.create(os.path.join(WORK, "films"), name, "screenplay", "INT. KITCHEN - NIGHT\n\nA small kitchen.\n\nMAMA\nI did not think you would come back.\n\nINT. YARD - DAY\n\nRain.\n\nMAMA\nHere you are.\n")["dir"]
    bible.seed(d); S.breakdown(d)
    return d


def line_shot(d):
    return next(s["id"] for s in V.status(d)["shots"] if any(p["lines"] for p in s["people"]))


res = {}
print("== baseline transcripts")
base = {k: asr(os.path.join(HERE, f"{k}.wav")) for k in ("david", "zira")}
for k, v in base.items():
    res[f"baseline_wer_{k}"] = wer(TEXT, v); print(k, "WER vs the text:", res[f"baseline_wer_{k}"], "|", v)

print("\n== T1 the audio inspector on real speech (should find little to complain about)")
for k in ("david", "zira"):
    r = Q.inspect_file(os.path.join(HERE, f"{k}.wav"), "voice", k)
    m = r["metrics"]
    print(k, "seconds", m["seconds"], "peak", m["peak_db"], "noise floor", m["noise_floor_db"], "speech level", m["speech_level_db"], "silences", m["silences"], "dropouts", m["dropout_count"], "clicks", m["click_count"], "lufs", (r["loudness"] or {}).get("lufs"))
    print("   findings:", [(f["severity"], f["code"]) for f in r["findings"]])
    res[f"inspect_{k}"] = [(f["severity"], f["code"]) for f in r["findings"]]

print("\n== T2 dub-fit on real speech: intelligibility and pitch after a tempo change")
d = film("DubFit"); sid = line_shot(d)
rec_len = dur(os.path.join(HERE, "david.wav"))
for tempo_name, shot_len in (("~1.05", rec_len / 1.05 + 0.1), ("~1.12", rec_len / 1.12 + 0.1)):
    S.set_fields(d, sid, {"generation": {"duration": round(shot_len, 2)}})
    V.attach(d, sid, "Mama", os.path.join(HERE, "david.wav"), fit=False)
    p = A.fit_plan(d, sid, "Mama")
    r = A.fit_make(d, sid, "Mama", allow_extreme=False) if p["class"] in ("natural", "audible") else None
    if r:
        out = os.path.join(d, *r["take"].split("/"))
        h = asr(out)
        print(f"tempo {r['tempo']} ({p['class']}): length {rec_len} -> {dur(out)} s (expected {round(rec_len / r['tempo'], 2)}); f0 {f0(os.path.join(HERE, 'david.wav'))} -> {f0(out)} Hz; WER vs original transcript {wer(base['david'], h)} (vs text {wer(TEXT, h)})")
        res[f"fit_{r['tempo']}"] = {"class": p["class"], "wer_vs_original": wer(base["david"], h), "f0": [f0(os.path.join(HERE, "david.wav")), f0(out)]}
    else:
        print("plan", p)

print("\n== T3 lining up: real speech against a different voice saying the same thing")
d = film("Align"); sid = line_shot(d)
S.set_fields(d, sid, {"generation": {"duration": 12.0}})
david, rate = sf.read(os.path.join(HERE, "david.wav")); zira, _ = sf.read(os.path.join(HERE, "zira.wav"))
shutil.copyfile(os.path.join(HERE, "zira.wav"), os.path.join(d, "guide_zira.wav")); shutil.copyfile(os.path.join(HERE, "david.wav"), os.path.join(d, "guide_david.wav"))
def onset(x, r):
    x = x if x.ndim == 1 else x[:, 0]
    e = np.sqrt(np.convolve(x ** 2, np.ones(int(0.02 * r)) / int(0.02 * r), "same"))
    return round(float(np.argmax(e > 0.05 * e.max())) / r, 3)
print("speech onset: david", onset(david, rate), "zira", onset(zira, rate))
for delay in (0.0, 0.4, 1.1):
    late = np.concatenate([np.zeros(int(delay * rate)), david if david.ndim == 1 else david[:, 0]]).astype("float32")
    sf.write(os.path.join(WORK, f"late{delay}.wav"), late, rate)
    V.attach(d, sid, "Mama", os.path.join(WORK, f"late{delay}.wav"), fit=False)
    for gname in ("guide_david.wav", "guide_zira.wav"):
        s = A.align(d, sid, "Mama", guide=gname)
        expect = -delay if gname == "guide_david.wav" else round(onset(zira, rate) - (onset(david, rate) + delay), 3)
        print(f"recording delayed {delay}s vs {gname}: suggests {s['shift_seconds']}s ({s['frames']} frames), match {s['strength']}, reliable {s['reliable']}; expected about {expect}s; error {round(s['shift_seconds'] - expect, 3)}s")
        res[f"align_{delay}_{gname}"] = {"suggest": s["shift_seconds"], "expect": expect, "reliable": s["reliable"], "strength": s["strength"]}

print("\n== T4 the pro export with real dialogue: round trip through 48 kHz / 24-bit and the master gain")
d = film("Export"); ids = [s["id"] for s in sorted(S.view(d)["shots"], key=lambda s: (int(s["scene"]), s["index"]))]
lines = [s["id"] for s in V.status(d)["shots"] if any(p["lines"] for p in s["people"])]
V.attach(d, lines[0], "Mama", os.path.join(HERE, "david.wav"), fit=True)
V.attach(d, lines[1], "Mama", os.path.join(HERE, "zira.wav"), fit=True)
t0 = time.time()
r = P.export(d, {"target_lufs": -23.0, "start_tc": "01:00:00:00", "stems": ["dialogue"], "mixes": ["final"]})
print("export seconds", round(time.time() - t0, 1), "ok", r["ok"], "problems", r["problems"], "mix", r["mixes"])
stem = os.path.join(r["folder"], r["stems"][0].replace("/", os.sep))
mix = os.path.join(r["folder"], r["mixes"][0]["file"].replace("/", os.sep))
times, total, _ = P.film_times(d)
x, rt = sf.read(stem, always_2d=True)
a, b = times[lines[0]]
seg = os.path.join(WORK, "stem_line1.wav"); sf.write(seg, x[int(a * rt):int((a + dur(os.path.join(HERE, "david.wav"))) * rt), :], rt, subtype="PCM_24")
h = asr(seg)
print("dialogue stem (shot 1) transcript:", h, "| WER vs the original's transcript", wer(base["david"], h))
res["export_wer_stem"] = wer(base["david"], h)
m = Q.inspect_file(mix, "mix", "mix", target_lufs=-23.0)
print("final mix: lufs", (m["loudness"] or {}).get("lufs"), "true peak", (m["loudness"] or {}).get("true_peak_db"), "findings", [(f["severity"], f["code"]) for f in m["findings"]])
res["export_mix"] = {"lufs": (m["loudness"] or {}).get("lufs"), "findings": [(f["severity"], f["code"]) for f in m["findings"]]}

print("\n== RESULT JSON")
print(json.dumps(res, default=str))
