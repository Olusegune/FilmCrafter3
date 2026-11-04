# FilmCrafter

Story-first AI filmmaking for Windows (macOS to be proven). Craft stories into cinema.

FilmCrafter is a sibling of PULSEFRAME (music-first AI directing). It started from PULSEFRAME 1.36.0 and is developed independently; see `docs/architecture/` for the baseline, the plan, the reuse map, the port ledger and the honest status of every goal.

## What it does

Screenplay or idea -> Production Bible, Cast and World -> shots with Shot Contracts -> pictures -> video -> continuity check -> soundtrack -> export or hand-off to an editor.
Your story is kept exactly as given; suggestions never edit it. Every generation shows its price and waits for a yes. Chosen and locked work is never replaced.

- **Agent Studio:** a guided production workspace for a story, preferences, budget and explicit milestone approvals. It shares one project with Manual Studio, includes a restart-safe approval/failure inbox and focused revision impact previews, and can isolate a first-scene proof across picture, dialogue, score, SFX, graphics, mix and preview. Local ComfyUI visuals can run automatically; cloud and audio generation retain their live cost, rights and confirmation gates. See `docs/AGENT_STUDIO.md`.
- **Director style (optional):** select camera, lens, lighting, colour, pace and performance traits from a worldwide filmmaker library, or clear the choice. Only craft traits—not a filmmaker's name—reach generation prompts, and the choice never changes the story or the project's visual look.

- **Look:** about 100 looks in six kinds of film (photorealistic, 3D, 2D, hybrid, hands-on crafts, art movements), a genre feel on top, the twelve principles of animation, and 48 filmmakers' visual approaches that work in any look. Where: Cast & World > Rules & style.
- **Voiceover:** attach your own recorded voices (`CHLOE_S01-04.wav`) to the people in each shot; the mouth follows your recording and the finished film plays it.
- **Sound & Music:** the audio half of the Production Bible: each character's voice (approved voices are never replaced silently), libraries of sound effects and music you import or make (ElevenLabs sound effects and music, Suno through Kie.ai: the price and the unestablished commercial rights are shown first), a planned soundscape for every scene (free quick ideas or the sound director), lanes on the Edit timeline, and an export mix with music dipping under voices, a limiter and an optional loudness target. Voice a whole scene with one price and a spending cap, make another take, and hear a table read before any video. Anything that may be out of date after a voice or sound changes is listed, never changed behind your back. See `docs/CREATIVE_PRODUCTION_EXPANSION.md`.
- **Frame shape:** 2.39:1, 21:9, 16:9, 4:3, 1:1, 4:5, 3:4, 9:16 or 9:21, chosen when the film is made and changeable later.
- **Blocking:** a top-down plan per shot, with the 180-degree line checked across a scene.
- **Quality:** a Production Supervisor shot by shot, a hands and faces check, a continuity check.
- **Hand-off:** EDL, OpenTimelineIO and Final Cut Pro XML (verified in DaVinci Resolve Studio), manifest, subtitles.

See `docs/GOLDEN_PATH.md` (the order that makes a film cheapest and calmest), `docs/GETTING_STARTED.md` (also the in-app guide, F1) for a walk through with pictures, `docs/QA.md` for what has been tested and what has not, and `docs/architecture/STATUS.md` for the honest state of each phase.

## Develop

```
npm ci
npm run tauri dev        # desktop app
npm run dev              # UI only, http://localhost:1420
python scripts/test_all.py
```

The film workflow's engine tests need only: `pytest requests pillow numpy soundfile imageio-ffmpeg pyyaml keyring pypdf fal-client openai`. The whole suite also wants `librosa` and, for the hand-off test, `opentimelineio` with `otio-cmx3600-adapter`.

Scripts (`scripts/`):

| Script | What it does |
|---|---|
| `test_all.py` | every kind of check in one table |
| `engine_reach.py` | which engine modules the app can still reach (a start for removing dead code); `--why <module>` says who imports one |
| `audit_film.py` | builds every shot's prompt for a film folder (free) and checks the right people, pictures, setting and look reached each one |
| `docshots-edge.mjs` | opens each of the 41 screens in headless Edge and photographs it; `PF_QA=1` also fails on any console error, `PF_A11Y=1` runs an accessibility scan (axe-core), `PF_PERF=1` prints page size, `PF_OVERFLOW=1 PF_WIDTH=1100` checks the layout at a window width, and `?n=300` makes the sample film 300 shots long |
| `make_look_docs.py` | rewrites the look library in the guide from `styles.json` |
| `make_handoff_sample.py`, `resolve_check.py` | a sample hand-off with real clips, and an import check in a running DaVinci Resolve Studio |
| `live_test.py` | one real picture on a real provider (prices first; `--yes` to spend) |
