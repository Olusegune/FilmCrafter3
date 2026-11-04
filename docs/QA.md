# QA report: FilmCrafter 0.35.1 (2026-11-04)

## Agent Studio whole-pipeline extreme pass

The 0.35.1 cycle ran the complete local matrix after adding whole-film production manifests and department model routing. Final results after correcting the two findings were: TypeScript build passed; **732 screen/Vitest tests** passed; 15 Rust shell tests passed; engine phases passed with **1,765 unit**, **337 regression**, **235 security**, **61 acceptance**, **729 integration** and **2 end-to-end** tests (3,129 engine passes total; optional tests skipped where their dependency is absent). The secret scan, Bandit medium/high scan, `pip-audit`, and production `npm audit` all passed with no findings. Agent Studio's focused set is **9 engine tests**, **4 component tests**, and **2 real-browser Playwright checks** including WCAG A/AA scanning and compact-desktop reflow.

Hostile cases added in this cycle: a damaged `agent-studio.json` recovers without changing `project.json`; overlong provider/model names and control characters are bounded and cannot become filesystem paths; an accepted whole-film manifest is atomically replaced and leaves no temporary files; image, video, voice, music and SFX choices survive in the manifest; the review screen renders characters, wardrobe, sets, score, SFX and motion-graphics suggestions together. Paid work remains outside the Agent Studio command allow-list.

The run found and fixed: (1) the audio-provider API returns `{providers: [...]}` but Agent Studio expected a bare list, leaving score/SFX choices empty; (2) Hype Williams was incorrectly represented as a geographic “Music video” region and is now categorized Global; (3) the sound-generation sheet could log a harmless null-response error under test and is now tolerant; (4) the intake was too dense, so department model selection is a compact disclosure with an Automatic/choice-count summary, while approved projects show their routing choices in the brief; (5) long generated production descriptions now wrap instead of widening the review layout.

Not performed: real paid image/video/voice/music/SFX calls, subjective judgement of generated creative quality, a screen-reader session, or a physical Windows display at 125%/150%. These require credentials, spend authorization, human taste, or hardware inspection. The installer remains unsigned until an Authenticode certificate is configured.

What has been tested, how, what it found, and what has **not** been tested. It is written to be re-run: every number below comes from a command in the last section.

## Automated checks (all passing)

| Check | Result |
|---|---|
| Engine tests (Python, `pytest`): story, bible, shots, make, blocking, looks, principles, render with a mock provider, interchange, security, golden film, end-to-end | **1,976 passed**, 8 skipped (optional-dependency tests), 0 failed |
| Screen tests and logic (`vitest`): every screen's markup and arithmetic, the guide, the shortcuts, the looks | **549 passed** |
| App shell (`cargo test`) | **9 passed** |
| The shell's allow-lists match the engine's actions and the frame shapes (a test across Rust, Python and TypeScript) | passing |
| Secrets scan (`rafter secrets .`) | none found |
| The guide lists every look the app has (a test reads `styles.json`) | passing |

Not run: `rafter run` (the remote code-analysis scan; it needs an API key). This release's changes read and write only the film's own folders; the one place that reads a secret is a throw-away test script outside the repository.

## Every screen opened in a real browser engine

All **41** screens of the screenshot harness (Home, New film, the story workspace, Cast & World, Rules & style, Shots and its tabs, Blocking, the Studio and its inspector, Make, Export, the Supervisor, the Continuity check, the writing-help sheets, the Direction library, the Look picker and the rest) were opened in headless Edge with console errors and uncaught exceptions recorded: **none from FilmCrafter's own code**. (The testing browser's Grammarly extension throws one error of its own; it is filtered by reading, not hidden.)

Interaction was tried, not only rendering: dragging a person and a camera on the Blocking plan (it moves and saves), clicking through the kind of film, the look, the genre feel and the animation principles (state follows the clicks), and the Studio inspector's Advanced fold.

## Accessibility scan (automated)

`PF_A11Y=1 node scripts/docshots-edge.mjs` runs axe-core (WCAG 2.1 A and AA) on every one of the 41 screens: **0 findings** after this cycle's fixes (7 kinds were found first, listed below). Automated rules catch only part of accessibility (roughly names, roles, contrast and structure); it is not a substitute for a keyboard-only or screen-reader walk-through, which has not been done.

## Voiceover (new in 0.15.0)

34 engine tests: file names to shots and people (odd spellings, the longer name winning, unknown names asked about, never guessed), bad files refused with a reason, attaching, lengthening a short shot, replacing and removing without deleting, the render request for Seedance 2 (audio sent, who speaks named, the recording beating native speech), the exported film playing the recording at its shot, the hand-off folder, and a film from elsewhere unable to point outside itself. A security review (path containment, size and length limits, no shell) found two hardening gaps that are fixed. **Not tested:** a real provider run with a recording (needs your permission and a spend cap), two people speaking in one shot, long films with hundreds of recordings.

## Measured, and decided against (0.16.0)

- **A long-running engine process.** Each engine call starts Python and answers in about 0.18 to 0.22 s (shots, make status, voiceover, blocking on a 58-shot film), of which about 0.24 s is importing the modules once. A resident process would save a fifth of a second per call, which no one would feel, and adds a process to supervise and restart. Not built. Reconsider if real use shows lag.
- **Removing the music-era code.** A reachability check from the app shell's commands finds 90 of the 93 engine modules still reachable; of the three it did not reach, two (`animation_principles`, `styleguard`) are in use (imported with an alias the check does not follow) and one (`model_audit`) is a developer tool. The music-era code is not dead: the app can still open PULSEFRAME projects. Removing it would mean dropping that, which is your call, not a clean-up.

## Film audit (every shot's prompt)

`python scripts/audit_film.py "<film folder>"` (free; nothing is sent) was run on the repaired Summit Sprout film: 58 shots, 45 with people, **0 problems** for pictures. For video it also passes (spoken lines are meant to reach video, so the quoted-speech check is for pictures only). Before this release the same film failed in four ways (see the table below). Screenplay layouts tested: numbered scene headings, forced `@Name` cues, title pages with author and contact lines, `(V.O.)`, `(O.S.)`, `(CONT'D)`, scripts with no scene headings, PDF-extracted text.

## Layout at the smallest window

All screens at 1100 px (the app's minimum width) and 1280 px: nothing outside the window, no sideways scrolling (`PF_OVERFLOW=1 PF_WIDTH=1100`). Tested in a browser engine, not in the installed window; nothing was tested below 1100 px (the app does not allow it), at 125% or 150% display scaling, or on a second monitor.

## Large film

A synthetic 300-shot film: the engine (breakdown 2.2 s; sync 1.0 s; shots view, make status, continuity, hand-off and blocking each 0.1 s or less) and the screens (`?n=300` in the harness; `PF_PERF=1` prints sizes). Select & review, Make and Shots draw in under 3 s with 2,100 to 4,900 page elements and 40 to 84 MB of script memory, no errors. Scenes fold in Select & review (a film over 60 shots opens with only its first scene open), so a 300-shot film is one scene of tiles and a list of headings.

## Real runs

- **Kie.ai, 2026-10-10:** the same shot in photoreal, 3D, 2D hand-drawn and two stop-motion versions (one with a filmmaker's approach applied), and a 4-second video: 7 pictures and 1 video, about $0.96. The looks were distinct, the blocking held, the video stayed on-model.
- **DaVinci Resolve Studio 21.1:** the hand-off imported through Resolve's scripting API: the Final Cut XML, the EDL and the OpenTimelineIO file each give the six clips and 20.0 seconds.

## What testing found and fixed this cycle

| Found by | Problem | Fixed |
|---|---|---|
| Real Kie.ai run | A film with no pictures yet could not make its first picture (the automatic models need a reference) | text-only model of the same family is used when there is nothing to edit |
| Real Kie.ai run | Subtitles drawn into pictures, from quoted speech in the prompt | the prompt says who speaks, never the words |
| Resolve import | The EDL named clips after the original files, so Resolve placed one clip six times | the EDL names each clip after its copy in the hand-off folder |
| Use (user report), real screenplay | An all-capitals title was read as a speaker (shot 1 "Title speaks", scenes off by one); action shots had no people; people with long picture names were never sent; one person could take every picture slot | all four fixed; a test for each |
| Use (user report) | A shot with no people could not make its picture on GPT Image 2.5 Flare ("Needs an image"): the fallback to a text-to-image twin only covered Nano Banana | every image-to-image model falls back to its text twin; the audit tool checks it |
| Film audit | A pronoun action shot ("She wrinkles her nose") had no one in it; numbered scene headings were not scenes; a forced @Name was not a speaker | all three fixed; tested |
| Whole-app pass (0.21.0) | A dialogue shot with no recording sent the film's silent soundtrack to Seedance as "the voice" and told it to speak along to it (probably why the first videos were mute) | films send no audio without a recording; tested |
| Whole-app pass | The File menu said "New Music Video" and most items did nothing from the film screens; the one-file save packed only the render project (no story, cast, shots or recordings) | a film-aware menu and a `.filmpack` of the whole film; round trip tested |
| Whole-app pass | Joining two shots lost the joined shot's recording; a deleted shot's recording stayed filed under an id a new shot could be given | recordings move or are put aside; tested |
| Film audit | Scene blocking kept a ghost character from an old breakdown and put it into prompts | blocking follows the shots; tested |
| Whole-app pass | Installer and app descriptions said "music video"; FilmCrafter registered `.pulse` and Producer files (PULSEFRAME's) with the old waveform icon | FilmCrafter's own icon, `.filmcrafter` and `.filmpack` only |
| Use (user report, with pictures) | A friend drawn in another character's clothes: the previous shot's picture was sent as a reference to a shot of other people; "two friends" had no friends in the shot | the reference is sent only for people the shots share; plurals mean the scene's numbered friends; tested |
| Clean-up | A Word (.docx) screenplay was silently cut after 6,000 characters | read whole; tested |
| Use (user report) | Choosing 21:9 in the Shape list gave 16:9 again: the shape was saved on the render project only and the next sync rebuilt it from the film | the film's shape is set from every place it can be chosen; tested |
| Use (user report) | The voiceover could not be found: it was only on the Shots screen, which Simple mode hides | opens from the Studio's bar and the Export screen as a sheet |
| Use (user report) | The Export format list had no 21:9 (nor 4:3, 4:5, 3:4, 9:21), and did not start on the film's shape | one format per frame shape, shared by three screens, tested against the engine |
| Accessibility scan | Film strip blocks' names did not contain their visible text | name now matches the text |
| Accessibility scan | The Studio's inspector tab list held a button that is not a tab | Advanced sits beside the tab list |
| Accessibility scan | Three selects (Aspect, Quality, Lip-sync) had no name | named |
| Accessibility scan | Select tiles' labels differed from their visible text | named by what they show |
| Accessibility scan | Direction cards were a radio containing buttons and a fold | a real radio, its label, the fold beside it |
| Accessibility scan | The lighting strip was a "picture" holding buttons; a Lighting summary held a checkbox | group role; the tick moved out of the summary |
| Screen sweep | Duplicate React key on Clean up; a dropdown given a null value on New film | both fixed |
| Screen sweep | Two panels (shot references, acting beats) crashed on a reply with a part missing | made tolerant; sample data corrected |
| Screen sweep | The film screen could be blanked by a progress reply with a part missing | made tolerant, tested |
| Screenshots | The Studio's top bar overflowed under the inspector on a film | Director Mode moves into More when the bar is full |
| Screenshots | A "Can't play" message in film mode spoke of a song | worded for the soundtrack |
| Frame-shape work | Changing Aspect in the Studio would have been undone by the next sync | the film keeps its shape; the Studio changes both |
| Looks work | Photorealistic looks would have had "photograph" reworded away like drawn looks | every photoreal look is exempt, from the data |

## What 0.19.0 changed, and how it was checked

- **Screen sweep** (47 screens, 1100 px and 1280 px wide): no console errors, 0 accessibility findings, no overflow. Run after the clapperboard, waveform and big-film changes.
- **Home clapperboard:** looked at in a browser (arm open and board scaled up mid-loop); structure and reduced-motion tested. Not seen in the installed app.
- **Waveform:** drawn from a generated test WAV in the browser harness (decode, bars, collapsing when a file can't be decoded); the peak arithmetic is unit tested. The `asset:` fetch inside the installed Tauri app is **not** tested.
- **Big films:** on the 300-shot harness film, relayout fell from about 115 ms to about 34 ms with off-screen cards skipped. Measured in a headless browser, not on a real film.
- **Nano Banana 2.1:** a read-only key check (no generation, no spend) showed the Kie key valid (17,451.6 credits) and `gemini-nano-banana-2.1` available to the Google key; no fal key was found. Kie's manifest was fetched live: model id `nano-banana-2-1`, 10 reference pictures, 1K/2K/4K, 15 shapes. Three engine tests cover the default, the list and which endpoints see pictures. **No picture has been made with it yet.** fal's 2.1 is untested; thinking level and web-search grounding are not passed on.
- **Minimum window height** 700 to 660 for 150% display scaling on a 1080p screen: reasoned from the screen arithmetic, not tried on a real 125% or 150% display.

## What 0.20.0 added, and how it was checked

- **Drop on a person, Undo, the recorder** (structure, WAV encoding, silence trimming, next-unvoiced-line, who is under the pointer): unit tested; the recorder's layout and the blocked-microphone message were seen in the browser harness. **Not tested:** a real microphone, Windows' microphone permission in the installed app, the drag-over highlight and drop-on-a-name (they only exist in the real window).
- **ElevenLabs voices** (`cast_voice`): 17 engine tests with every ElevenLabs request faked: no key means nothing is asked; the plan is read only when the plan view asks; a library voice is kept; a designed voice is heard before it is kept and a preview id cannot be a path; cloning refuses without consent, a non-audio file or a 30 MB+ file, and sends nothing then; a line is never spoken without a confirmed yes; a repeat is free; a busy service is retried but a refusal or a used-up plan is not; your own recording replaces a spoken one and the spoken one is kept. **Not tested against the real ElevenLabs** (no key stored here): the request shapes follow ElevenLabs' published reference (`/v1/text-to-voice/design`, `/v1/text-to-voice`, `/v1/voices/add`, `/v1/text-to-speech/{id}`, `/v1/user/subscription`, `/v2/voices`).
- **Home card padding:** seen in the browser harness; a test keeps it from growing back.

## Performance Director screens (2026-10-30)
Checked on the harness, no provider: 16 jsdom component tests, 3 browser tests, and the axe scan over the two new scenes (no violations). Visual fixes found by looking: oversized text boxes made the Scenes tab long, and the beat editor ran too tall (details are now folded behind a summary line). Not checked: the sheets in the installed desktop app, or with a real film's breakdown.

## The four finishing touches (2026-11-05)
Engine, on real films and pictures: every episode gets its own film (outline text, the season's presets then the episode's own length as your own last preset), asked again it makes only what is missing and never rewrites a film that exists (a line added by hand survives; a deleted film is made again), no plan or no film means a refusal and nothing made, and the season code contains no render, provider or network call. The screen-colour finder finds a green screen lit unevenly (dark on one side, bright on the other) and returns a green, finds a blue one, says so plainly for a grey picture and for a picture whose middle is green but whose edges are not, reads a clip's first frame, changes nothing, and refuses text layers and unknown layers. The vertical export is a separate file at 1080x1920 and the wide film is byte for byte what it was. Home pictures (Rust): the first shot's chosen keyframe is used, a missing file is skipped, and a hand-edited record pointing outside the render folder, at an absolute path, a drive, a non-picture, a backslash escape or a non-text value gives no picture and no crash. Browser, on the harness: a card with a picture and one without; a picture that fails falls back; the ready screen, the vertical version, exporting again, a draft not called ready, and no accessibility violations; the season button asks first, Cancel makes nothing, and the plan is unchanged afterwards; the screen colour is found, set and said. Not checked: a real season on a real project, the ready screen after a real export in the installed app, and a real camera clip's screen colour.

## Video clips and the extreme QA pass (2026-11-05)
**Video clips,** with real encoded video through the real export: a green screen with sensor noise, compressed and chroma-subsampled like footage, is removed and the film shows through where it was, the subject stays, and no green fringe is left at its edge (looked at as a picture, not only measured); a clip begins at its own start point (red for a second then blue: from 1.0 it is blue); a short clip ends unless looped and plays again when looped; the film before a clip is up and after it has ended is as it was; clips mix with text, shapes and blend modes in one export; a missing clip file stops only the overlay pass, with a reason, and the film is still made. Refused with a plain reason and nothing added: a text file named .mp4, an audio-only .mp4, a program file, a missing file, a folder, a file over the limit, a ninth clip. A project file edited by hand to point a clip at a file outside the project, or at a non-video, is refused when the film is made. **Extreme QA.** Seeded hostile input (nasty text, huge and tiny numbers, NaN and infinity, lists and nested objects where a value belongs, path and shell and script text, the null character, 20,000-character strings) at: the layer checks (1,500 random settings, 400 random adds, updates of what was added), the compositing values, the preset actions, the motion graphics' words, the layer templates, and 30 of the engine's doors with every free action each has. Every answer is a result or a plain sentence, the project files stay readable, and what is saved is inside its range. Every harness screen was opened at 1100x700, 1440x900 and 820x800 and checked for script errors, failed pictures, controls without a name, text running out of its box and sideways scroll; the five scenes whose harness wrapper is a fixed width are excluded from the sideways check at the narrow size only. Keyboard: Tab and Shift+Tab never leave an open sheet; Escape closes it and focus returns to the button that opened it; every control on Home shows a focus. Dependencies: `npm audit` reports no vulnerabilities; no dependency was added this session. Not checked: the installed app on a second computer, real camera footage (the clips here are made and compressed to behave like it), pip and cargo dependency audits (the tools are not installed here), and the music-video-era screens (unchanged).

## Preset setup and the first-launch question (2026-11-05)
With the real engine: a length chosen on Home is kept as your own last preset and beats the 90 seconds a vertical preset aims for when applied; choosing again replaces it and no leftover remains; lengths under 5 or over 7200 seconds, non-numbers and episode counts outside 1 to 60 are refused and nothing is recorded; the setup preset cannot be forged through the list; older records load. On the harness: the setup sheet (length, episodes, Advanced) at a laptop size; the question is asked once, each answer goes where it says, Not now and Escape close it for good, Help me choose reopens it, someone with films is never asked, and the question has no accessibility violations. Not checked: the installed app, and a real first launch (the harness stands in for the stored answer).

## The Home screen (2026-11-05)
Checked on the harness at 1280x720, 1440x900 and 820 px wide: the three ways to begin and the presets are visible without scrolling at a laptop size; nothing is cut off sideways at the narrow width; the six featured pictures load, and a picture that fails falls back to a plain tile; a card opens by mouse and by keyboard (Enter, Escape), with a visible focus; the gallery lists all 35, searches and filters; 60 recent films show 8 until asked; no films shows a kind message; the gallery and a preset's details have no accessibility violations. With the real engine: remembering a preset on a new film writes only the preset record (the film's own file is byte-for-byte unchanged and no render project appears), unknown or malformed ids are refused, at most five are kept, applying clears what was applied, and an older record loads as before. Not checked: the installed app; dropping a file on the real window (the drag and drop code is as it was); recents thumbnails (a film's own picture is not used yet: the card shows a strip).

## Compositing (2026-11-05)
Checked with real exports: a fill layer multiplied or screened over the film at 6 s gives the colour the arithmetic of the mode predicts (to within what an encoder changes), the film before it is up is the film, and a blended circle changes the picture only inside the circle. Normal and blended layers (text, a soft-light tint, a screened shape) go through one export together. A blend mode, being the only user value that reaches the ffmpeg filter graph by name, is taken from a fixed list: strings with filter syntax in them are refused. A green screen in shadow is removed as the lit screen is; a mask's soft edge falls off in steps; a layer with neither mask nor key keeps its old cached picture. On the harness: 5 browser tests on the Mix and effects section and the axe scan. Not checked: real green-screen footage (layers are still pictures, so there is no video to key yet), the installed app, and the look of each blend mode in the player against the finished film.

## Motion graphics (2026-11-04)
Checked with real exports on a small film: a lower third put down at 4 s leaves the picture untouched before it and changes thousands of pixels once it has settled; two uses of one template are two groups and each is removed alone; a bad moment or a full project is refused and changes nothing; every built-in template passes the same checks as a layer you make yourself; a glow adds a faint halo in the colour asked for without moving the text, a blur softens the edges, and glow 0 / blur 0 give the very same cached picture as before. The eight previews were looked at as pictures. On the harness (no provider): 2 jsdom tests, 4 browser tests, and the axe scan over the new scene (no violations). Not checked: the movement of each title in a played film beyond the one frame compared; the installed app's sheet (needs the new installer).

## Presets, the vertical version and the series plan (2026-11-04)
Checked with the real engine on a small film: applying a stack sets the look, acting, grade, frame shape and the preference records and nothing else, with no provider called; a choice of yours is kept; undo restores and leaves alone what changed since; a vertical export is a 1080 x 1920 separate file, the original's frames and records are unchanged, and the chosen part of each shot lands where it should; a ten-episode plan is made from one idea without spending. Not checked: how the presets look and feel on a real film end to end (the 35 are my reading of your pack: please judge the settings each one stacks), the vertical version on a real 16:9 film with a person in frame (the choice is a number per shot, not a face-following crop), still-image takes in the vertical version (they use the middle), batch-making episodes and per-episode generation budgets (not built: they are the paid part), the platform delivery registry (not built: platform limits change and need checking against current sources); the preset thumbnails are concept illustrations, not frames from your films.

## The Smart Editor (2026-11-03)
Checked with real exports: a clip that runs 0.8 s past its words is suggested for tightening and accepting it shortens the cut by exactly the frames promised; a listener with spare picture is suggested more time and accepting adds exactly that; a pause you asked for or a beat you wrote is kept and reported; the preview is two real clips, the second shorter, and saves nothing; one undo puts the cut back. Not checked: whether the suggestions are good filmmaking on a real film (the rules are simple readings, not taste: this needs your eye on real scenes), the speech-length estimate against real recorded voices (it assumes about 155 words a minute), the previews in the installed app, and styles beyond the three built. Not built: continuity checks, transitions, camera-movement advice, selective regeneration, and the other seven editing styles.

## Preview copies and recovery (2026-11-03)
Checked with real ffmpeg: a 1280x960 take gets a 540-line copy, a small take none; the exported film is frame-for-frame the same with and without copies; a damaged edit record comes back from its backup with the damaged bytes kept, and with no backup every read and write stops with a plain message. Not checked: the player scrubbing a real 4K take (the copy is made and offered; smoothness was not measured), how long a copy takes for a long clip, and the button in the installed app.

## The rest of the Studio follows the cut (2026-11-03)
Checked on the harness: after a delete the shot's card and the shot count change, and Undo brings them back; unit tests cover where each shot sits for a trimmed shot, a shot cut in two, a shot with no clip and a hidden track, and where voices and sound start (a shot's own time zero). Not checked: playing a trimmed shot in the real player against a real take (the offset arithmetic is covered, not watched); a shot cut in two whose halves were moved apart (the player assumes they run on); layers and captions after a ripple (they stay where they were and are flagged only when they fall past the end).

## The cut lane (2026-11-02)
Checked on the harness (a made-up film and a small stand-in for the engine; the engine's own tests prove every edit frame by frame): clips, handles, keys, undo and redo, markers, a locked track, dragging with Esc to cancel, and the accessibility scan. Not checked: dragging a clip body, Alt-drag to roll, and ripple from the toolbar in a real browser (the same engine calls are covered in unit tests); the lane in the installed desktop app; a very long film.

## Editing the cut: time, operations and export (2026-11-01)
Checked with real ffmpeg on 64x64 footage whose every frame carries its own number: a film that was never edited exports every frame in its place; a split changes nothing seen; a trim shows exactly the frames asked for and leaves black where the picture was taken from; a ripple trim shortens the film by exactly the frames given up (5.5 s from 6 s for 12 frames); a ripple delete brings later shots forward; hidden and locked tracks behave; 600 random edits never broke the sequence's rules. Not checked: the on-screen controls (not built yet), a long film's render time, trims on image takes (they have no source time), audio alignment of a trimmed clip against real recorded voices (the arithmetic is covered, a listening check is not), frame rates other than 24.

## Color Studio and Storybook looks (2026-10-31)
Checked with real ffmpeg on small pictures and a small exported film: each grade number moves the exported picture the way its name says; a natural picture goes to RGB and back within 4 levels (a pure-colour test chart clips by design, because colours outside the RGB range cannot be kept); a real `.cube` is applied through `lut3d` with Windows paths; the preview frame agrees with the exported film within 6 levels; a missing LUT stops the export with a plain message. Not checked: the installed app's own ffmpeg (checked on the development machine only), HDR or log footage (refused by design), a long film's render time, and the Storybook looks with a real image or video model (the wording is tested, the pictures are not).

## Performance Director steps three to five and the old-code removal (2026-10-30)
Checked: new engine tests (kinds, prompt wording, honest model labels, delivery hint, arc flags, the allow-lists), 19 component tests, 4 browser tests and the accessibility scan; the full Python suite (2211 passed after the removal), vitest, clippy, cargo test and all browser tests passed after removing the song-first code. Not checked: a real provider run (acting quality is labelled *unverified* on purpose), the installed app on a real film.

## Layout and accessibility sweep (2026-10-15, 0.25.4)

`PF_OVERFLOW=1 PF_QA=1 PF_WIDTH=1000 (and 1280) node scripts/docshots-edge.mjs home film cast castsound soundfx soundscene soundstyle shots make select studio export dirliball compose library supervisor`: nothing outside the window, no page scrolling sideways, no console errors. `PF_A11Y=1` (axe-core, WCAG 2.1 A and AA) on 14 of those screens: 0 findings. The one defect found by eye was the Direction library's squashed cards (fixed). Not covered: 125% and 150% Windows scaling (a person must look), and dialogs, which the harness draws inline rather than as modals.

## Release checks for 0.25.3 (2026-10-14, the last whole runs on the release code)

Engine 1975 passed, 8 skipped, 0 failed in the last whole run (6 min 15 s), plus one test added afterwards (the learned sound-effect price: 1976); screens 549 passed; `cargo test --lib` 9 passed; `rafter secrets` none; `npm audit --omit=dev` 0 vulnerabilities. New since 0.25.0: `test_damage_records` (a damaged shot record is reported and kept, a good backup is used, no temp files or locks left), the learned-price test in `test_audiogen`, the class-name collision guard in the screen tests, and the corrected clone and lip-sync-document wiring tests. Not re-checked by a person: the installed app, the new Edit shot cards and the voice dialogs at 125% and 150% Windows scaling.

## Real runs of 0.25.0 (2026-10-14, the owner's ElevenLabs credits, a throwaway film, cap 150 credits)

Done with the engine from the released code on a **throwaway film** (not a real project), the key read from the Windows Credential Manager and never printed. Total ElevenLabs credits **reported** by ElevenLabs: **39** (our estimates added up to 91).

| What | Result |
|---|---|
| Sound effect, 2 s ("a kettle clicking off in a quiet kitchen") | Worked: a 2.04 s file was saved to the library as *generated*, pending approval, `commercial use: not known`; ledger entry completed; **ElevenLabs reported 11 credits** (estimate 22). Asking again was free and sent nothing. |
| Sound effect, 4 s, same words | Worked: 4.05 s; **reported 22 credits** (estimate 44). So on this account a sound effect cost about **5.5 credits per second**, half of the help-centre figure the app uses. The app keeps the higher figure as a safe upper bound and always calls it an estimate; it is not changed from two data points. |
| Voice scene (two short lines, Eleven v4, a premade library voice, cap 60) | Worked: both lines spoken and attached, no failures; the scene's price was shown first (25 characters, about 25 credits); **reported 4 and 2 credits** for 18 and 7 characters. The reported amounts are well below the app's characters-times-multiplier estimate; what ElevenLabs' `character-cost` header measures is not documented, so the app shows it only as "reported" and keeps the estimate apart. |
| Table read of the scene | Both lines found in order (1.2 s and 0.96 s), none silent. |
| Model list refresh (free) | ElevenLabs answered with 9 speech models; its stated credit multipliers (v4 1.0, v4 Turbo 0.5, Flash 0.5) matched the app's built-in ones. |
| Lip-sync test (Kie 200 of 300 credits, ElevenLabs 3 of 50) | Run on a throwaway film: Take A (Seedance 2, picture + recording) did **not** follow the voice's timing by a crude mouth-motion measure; Take B (Kie lip-sync pass) moved the mouth toward the words but is not proven good. Full table in `docs/LIPSYNC_VALIDATION.md`. Files for judging are on the owner's Desktop. |
| Not run | Music (ElevenLabs Music or Suno through Kie.ai) and a person's judgement of any generated audio or video. |

## What 0.25.0 (creative production expansion) added, and how it was checked

- **Whole-suite results on the branch `stage-a-sound-bible`:** engine **1971 passed, 8 skipped, 0 failed** (6 min 9 s); screens (`vitest`) **548 passed**; `tsc` clean; `cargo test --lib` 9 passed; `rafter secrets` none found; `npm audit --omit=dev` 0 vulnerabilities.
- **New engine tests (no provider, no network):** `test_audiolib` 12, `test_bible_sound` 5, `test_voicedirect` 25, `test_audiocues` 15, `test_audiogen` 18, `test_audiomix` 14 (real audio and ffmpeg; one through `export.build`; a ten-minute film for memory), `test_outdated` 9, `test_registry` 14, `test_preupdate` 4.
- **What the audio tests measure:** where a cue lands and at what level; fades and loops; the depth of the dip under a voice (within 2.5 dB of the setting); peaks under the ceiling; loudness within 2.5 LU of a target; memory under 150 MB for a ten-minute film; the planned sound present in an exported film and a suggested-only cue absent; the sound file's hash unchanged.
- **What the paid-path tests prove (all providers faked):** nothing is sent without `confirmed`, the rights acknowledgement and (for unpublished prices) the accepted unknown cost; an unclear outcome is never retried and blocks the identical request; a refusal, a busy provider and no connection are each recorded as what they are; a sound made before is reused free; non-audio replies are not kept; only parameters the registry lists are sent.
- **Not tested:** any real ElevenLabs sound-effect, music or seed request; any real Kie.ai Suno task (its reply format was read from the documentation); the real lip-sync (see `docs/LIPSYNC_VALIDATION.md`); the Edit timeline lanes and the new screens in the installed app (browser harness with mocked data only); a clean-machine update (the updater is not built).

## What 0.24.0 (Phase 0) added, and how it was checked

- **Paid-voice safety** (`test_voice_paid_safety.py`, 33 tests, every provider call faked, no network): each paid action refused by the engine unless confirmed and sends nothing; consent and spending are separate; design needs the unknown-cost acceptance; cancelled means no request; estimates and reported amounts never added; an ambiguous 5xx / timeout is `uncertain` and never re-sent; creation is never retried; 429 retried a bounded number of times; crash leftovers settled truthfully; identical request blocked until the person resolves it; limits; six processes writing entries at once keep every entry; no credential in the ledger; a film with no ledger works as before.
- **Safe I/O** (`test_safeio.py`, ~26 tests incl. a six-process hammer and a folder that refuses writes): absent / valid / damaged / unreadable cases kept apart; the damaged bytes are preserved; `.bak` only ever holds a good file; a failed write leaves the old file; `film.json` and the voice files adopted. `test_render_lock.py`: the render queue's lock under contention (the Windows race was reproduced on the old code, 1 run in 8).
- **Film backups** (`test_filmbackup.py`, 10 tests): snapshot contents (no media, no render project), skipped when unchanged, restore verified first, an undo snapshot, nothing deleted, the ledger never rolled back, a tampered or unreadable snapshot refused with nothing changed, an unsafe path refused, only 30 kept, a damaged film.json reported and recovered from its `.bak`.
- **Opening files** (`test_film_pack.py`, +7): hostile paths, links, too many items, expansion bomb, too little disk, a file lying about its size, a normal film still opens. `test_cast_voice.py`: a sample must really be audio, is written whole; the engine says which models take tags.
- **Screens** (`voiceusage.test.ts` and updated `voice.test.ts`, `ui.test.tsx`): the confirmation words, the usage line (reported vs estimated), each screen asks before it sends the flags, the update check is off in both the engine and the screen, the asset scope is not the whole home folder (a Rust test reads `tauri.conf.json`).
- **Not tested:** the installed app (nothing was installed); the narrowed media scope on a real Windows install with a film on another drive (the code adds opened folders at run time, which compiles and is unit-tested only for the configured scope: see the smoke checklist in the Phase 0 report); real ElevenLabs behaviour for any of the new paths (no paid call was made); the usage panel was checked in the browser harness only.

## What 0.22.0 added, and how it was checked

- **Voice lanes and the line studio:** structure and arithmetic unit tested (who speaks in what order, where two people sit in one shot, the engine's and the screen's list of tag-reading models kept equal, the price asked before the first spoken line); seen in the browser harness (4 lanes, filled and dashed clips; the studio opens; a feeling chip writes `[tired]` into the line; the price shows). **Not tested:** the lanes in the installed app on a long film, and drag-and-drop onto a clip (it only exists in the real window).
- **Takes:** engine tests with ElevenLabs faked (every version kept; switching sends nothing and archives, not deletes; a take from another line or a path is refused; the shot's written dialogue never gains a tag).
- **Real ElevenLabs run** (Eleven v4, a library voice, five short lines, voice design): a spoken line was attached and marked; a repeat was free; a directed take (`[sighs]`) and a second take were made; switching back cost nothing; a voice design returned three options. **Not done for real:** cloning, keeping a designed voice, the plan line (the key lacks `user_read`).

## What 0.23.0 changed, and how it was checked

- **Film strip | Edit:** seen in the browser harness (Film strip: no resize handle, no lanes, no layer button, cards at 112 px, timeline 328 px high); the layout memory is unit tested (a film starts in the Film strip, each film keeps its own mode, damaged storage is ignored). **Not tested:** dragging in Edit mode after the change (the code for it is untouched), and a real long film in the Film strip.
- **Voices in the Video tab:** seen in the harness (two cards for a two-speaker shot, one opens the editor inline); the summary wording and the wiring are unit tested. **Not tested:** the inline editor in the installed app's real panel width.

## Lip-sync: what was checked and what was not (0.23.1)

- **Checked, free:** on the real Summit Sprout film, for a voiced shot (S07-06), the app builds the Seedance 2 request with the recording as a reference-audio clip (now 4 s, the shot's length, instead of the 1.6 s line, which Kie would refuse: it takes 2 s or more), three character reference pictures, `generate_audio: false` and a prompt that says who speaks along to the audio. The golden path's own rules were kept: one test shot first (the Make film screen prefers a speaking one), voices before video.
- **Found and fixed:** a recording under 2 s was sent as it was; the clip is now padded to the shot's length (two unit tests).
- **NOT checked, and cannot be without spending:** whether Seedance 2 moves the mouth in time with reference audio. Kie's documentation does not say it does. The film has no approved keyframes yet. One take is estimated at about 164 Kie credits. The dependable alternative, the lip-sync pass on a finished take, has not been run either.

## What 0.28.0 added, and how it was checked (2026-10-21)

- **Sheet matching (which of a person's pictures go to which shot).** Engine unit tests (`test_sheetmatch.py`, 6 + an integration test through `make.sync`): near words are understood (anxious finds worried; sprints finds running), identity pictures are chosen first and at most four, an expression, pose or outfit picture goes only to a shot whose words fit (and at most one of each kind), an outfit needs its own words not one shared word ("red coat" is not sent for "a red dress"), a rebuild leaves no stale picture, and a film with no sheets is unchanged. **Not tested:** on a real film with real sheets, or how a video model uses the extra references.
- **Action choreography.** Engine unit tests (`test_choreography.py`, 32): every kind and every ending gives a valid plan (camera words from the lists, lengths 1.5 to 6 s, no unfilled placeholders); the same request gives the same plan and a variation another; a contact is never more than three action shots in a row without a cut to a reaction or detail; the momentum ends with the winner; who was hurt is carried forward and only for the person hit; people and counts are checked; editing keeps the plan valid; **applying adds new shots after the scene (or a chosen shot) and every existing shot file is byte-identical afterwards**; a plan is applied once; plans are listed and removed aside; the module cannot spend or send, and its wording has no gore. Screen: words and wiring unit tested (`choreo.test.ts`), the sheet seen in the browser harness (kinds, a plan of four shots, centred over the screen). **Not tested:** how the planned shots render on a real video model, or by a person who directs action.
- **A visible Materials button** next to Guide and Costs (wiring tested, seen in the harness).
- **Player.** Scrubbing, previous and next shot and the rounded gold volume bar were driven in the browser harness; the no-sound-file clock is covered by code review and a source-text test only (the harness film has a mock soundtrack that cannot play).
- **Dialogs, spending token, finished-film check, Costs, Guide, materials import** (0.26 to 0.27): see the changelog; each has its own tests.

## Yellow tint, noise and waxy skin (after 0.28.0): what was checked

- **Prompt wording** (`test_picturecare.py`, 6): on by default and off per film; the line asks for neutral white balance, real skin and a clean image; a warm shot (golden hour, candlelight, sunset, fireplace, sepia, or a warm look) keeps its warmth; the negative prompt gets the words once and not for warm shots; it reaches the real request for both a picture and a video model; it gives way to the hands line but not to loose extras when a prompt is too long. An existing anatomy test was updated: a model with a negative prompt now always gets a clean-image negative unless picture care is off.
- **Whole-film cast** (`test_colormatch.py`, 5 new, with real ffmpeg clips): an all-yellow film is found where matching shots to each other sees nothing; a neutral film has no cast and a small cast is left alone; removing the cast moves a yellow shot clearly towards neutral (measured on exported pixels) while a cool shot stays cool; denoise and grain are off until asked and are plain ffmpeg filters that run in a real export; the picture-care switch is a setting of the film.
- **Screen:** the Colour match sheet shows the new options (seen in the browser harness with mock data; wording and wiring unit tested).
- **NOT checked:** on a real film from a real model. Whether the new wording actually reduces the yellow cast or the waxy look in a given model's pictures is unknown until a film is made with it; the post-export cast removal is a measurement-and-offset, so a film with a deliberately warm palette needs the strength lowered or the option left off.

## Changing assets (after 0.28.1): what was checked

- **Engine** (`test_bible.py`): a picture is replaced in the same place keeping its label and kind unless changed; the old file stays in the folder; the original the person chose is untouched; a refused replace (not a picture, not on the entry, a bad id) changes nothing; a picture can be renamed and retyped; ids from outside are never paths. The engine and the shell agree on the action list (security test).
- **Screens** (`refeditor.test.ts`, 3 + 1): which references are edited in Cast & World (made from the Bible) and which in the library; Edit opens in the card; Replace, Remove, Add and retype are there; Cast & World has replace and the kind pick-list. Seen in the browser harness: Edit opens the form in the card, Remove drops a file from the list, Save closes it.
- **Found while testing:** a stale dev server from another project was answering on the test port and served old code; the check was repeated against the right one. Not a product bug.
- **NOT checked:** replacing a Cast & World picture end to end in the installed app (the file chooser is a Windows dialog and could not be driven here), and that a replaced picture is the one the next render uses (the Bible to library step is covered by the existing tests, not re-run with a real render).

## Messy backgrounds (after 0.28.3): what was checked

- **Diagnosis from the film's own record:** the shot's request had a one-line setting, a place with no description, layout or picture, and nine references (eight character sheets and the previous shot). This is a reading of the record, not a proof that each of these caused the artefacts in the picture.
- **Engine** (`test_placecare.py`, 9): places that shots happen in are listed with what they lack; a description, a layout note or a picture each count; a first description comes from the story's action lines only (no dialogue), never replaces one that exists and does nothing the second time; the wording asks for a soft background only for people shots that are not wide and have no chosen focus; fine patterns are asked to stay soft in every request and in the negative; one person gets up to four sheets and two or more people two each, the first (best) ones.
- **Screens:** wording and wiring unit tested (`placecare.test.ts`); the notice above the pictures and a way to Places.
- **NOT checked:** whether the new wording and the two-sheet limit actually give a cleaner background on the real model (gpt-image 2.5): that needs new pictures made and looked at by a person.

## Sound on tracks, the next step and readiness (unreleased): what was checked

- **Tracks** (`test_editortracks.py`, 9): each person gets a track and the second speaker follows the first; a J cut starts a voice before its picture and an L cut lets it run on, cut where the shot and its tail end; a shot with no recording adds no track; approved effects and music get their own tracks and a loop fills its time end to end; a cue that is not approved is not on a track; clips on one track never overlap and a trimmed one keeps its place in the sound; the hand-off writes the tracks into OTIO (audio tracks, gaps, copied files) and Final Cut XML (well-formed, negative lanes, every clip reference defined); a quiet film gives no tracks; Premiere/Resolve gets a third timeline with one audio track per voice and kind (real ffmpeg clips).
- **Readiness** (`test_readiness.py`, 7): no shots, the next step is the story; a short shot is a fix with a half-second length and applying it clears it; steps follow the order a film is made in; lines without a voice point at the voice screen; the paid step names the price sheet; reading changes no file; the module has no network, payment or speaking code; command line.
- **Screens** (`pacing.test.ts`, `readinessWords.test.ts`): the list only reads and its one change is a shot's length with a put-back; the bar is in the film view. Seen in the browser harness: the bar under the header, the list sheet.
- **Read-back and stems** (`test_editortracks.py`, 3 more): a finished hand-off reads back clean, and the check names a missing sound and an EDL that disagrees; each stem is as long as the film, silent before the line and carrying the voice after it. **Real film:** the hand-off of the owner's SUMMIT SPROUT film (58 shots, 342 s; copied, never the original) was written and read back with the real OpenTimelineIO library (the EDL through its cmx_3600 adapter too); it found that very long titles overran Windows' path limit, now fixed by shorter names. That film has no voice recordings, so its tracks come from the synthetic tests; the real library also reads the synthetic tracks back (voice at the right second, the right length).
- **Timing and price** (`test_audioplan.py`, 3 more; `timing.test.ts`): voices laid out like the mix (J cut, gap, L cut), an estimate marked as one, a run-over warned, and the gap equals the mix's; the video price is shown, absent when no model is chosen, and absent (not guessed) when it cannot be worked out.
- **A real paid test (ElevenLabs, 3 credits charged, far under the approved $5):** on a throwaway copy, a second person was given a line in the shot that had none; the Sound plan said *needs a voice*; the line was spoken with a real ElevenLabs voice through the app's own confirmed, ledgered path (the film's own credit limit refused it first, as designed, until raised on the copy); the plan then said *laid over at export* with the real recording's length (1.28 s) in the timing strip; the hand-off wrote *Voice Ben* and *Voice Lila* tracks plus two stems, read back clean, and the real OpenTimelineIO library placed Lila at 4.0 s (her shot's start). No Kie spend was needed.
- **NOT checked:** DaVinci Resolve is not installed on this PC (searched Program Files, the Start menu and the registry), so the import into it could not be tried; the hand-off opened in DaVinci Resolve, Premiere Pro, Final Cut Pro or After Effects (no editor was available; the files are well-formed and the structure follows the formats, but an import is the real test, and Final Cut XML audio on lanes under the first clip is the part most likely to need adjusting); the Lengthen and Put it back buttons in a running app; After Effects has no direct route (use the EDL or the finished film).

## Sound plan and hide pictures (unreleased): what was checked

- **Sound plan** (`test_audioplan.py`, 11): V.O. and O.S. marks are kept on the line; each shot gets a route and a reason (none, voice-over, needs a voice, audio-in, laid over, native) following what the model can take; too-short shots and crowds are warned; lines needing a voice are counted and priced offline; tries follow the tier and a per-film setting; the report changes no file; Apply only turns voice-over shots from automatic to off and never overrides your choice; the module contains no network, payment or speaking code.
- **Screens** (`pacing.test.ts`): the Sound plan spends nothing, is reached from the Shots screen and goes to a shot; the hide-pictures choice is one stored value both panels follow. Seen in the browser harness: the Sound plan sheet (a shot needing a voice first, a voice-over with its recommendation, the Mark button).
- **NOT checked:** the Hide pictures link in the real shot panel (no harness scene) and in the installed app; the Sound plan against a real film with a real model's abilities (the tests use stand-in models); whether a voice-over shot set to off actually yields a cleaner silent video on a real model; the new Tauri command only through clippy, not by running the app. Not added on purpose: a new voice provider, voice cloning, or any change to how existing projects generate.

## Composition and pacing (after 0.28.4): what was checked

- **Composition** (`test_composition.py`, 11): the shot size is read from the framing words; people and the way they face are read from the blocking words (both phrasings the app writes); one person is placed opposite the way they face so there is look room; two people take opposite thirds and the screen sides in the blocking are kept; a wide shot gets a horizon on a third (and a low angle moves it); every size gives sentences with reasons and points inside the frame; it reaches a real request, can be switched off for the film, is left out when a storyboard panel is attached and when nobody is in a medium shot, and is dropped before the hands line when a prompt is too long; the guide for a film's shot and the switch work and the command line refuses a bad id.
- **Pacing** (`test_pacing.py`, 10): each kind of finding is raised for a built-to-fit film and not for the cases it should skip (an insert, action); findings are ordered faults first with a reason and a tip; transitions are flagged only above the share; reading changes no file; an empty film is refused.
- **Screens** (`pacing.test.ts`, 6): bar sizing, words, wiring and read-only guards; Seen in the browser harness: the Pacing sheet (8 bars, the fault first), the Composition box on the Camera tab (grid, one point, the sentences).
- **NOT checked:** whether the composition wording changes where a real model puts people (it only asks); the thresholds in the pacing report (2.5 words a second, four in a row, a third of the cuts) are sensible rules of thumb, not measured on a real film; and neither has been tried by a person on a real film.

## Depth of field and J and L cuts (after 0.28.4): what was checked

- **Depth of field** (`test_dof.py`, 4): each level names what is sharp and the aperture it matches; the choice reaches a real request and replaces the automatic soft background (and outlasts the general picture-care line when a prompt is too long); a shot keeps its choice, only the listed levels are accepted, the choice reaches the production plan the renderer reads.
- **J and L cuts** (`test_voiceover.py` plus `test_dof.py`): with real audio, a plain line starts with its shot and is cut at the shot's end; a lead moves the start earlier by the amount; a tail carries on past the shot's end by the amount; a lead can never push a line before the start of the film; negative values are no lead or tail. Values are kept 0 to 2 s, one change keeps the other, no other shot changes, and the export hands the lead and tail to the voice mix.
- **Screens** (`dofcut.test.ts`, 3): the depth-of-field list with apertures and the automatic default; the two sliders only for a shot with dialogue; no paid or sending call. Seen in the browser harness: the options and the two sliders.
- **NOT checked:** an exported film with a J or L cut listened to by a person (the engine test measures where the sound starts and ends, not how it feels); whether a real model follows the aperture wording; the editor hand-off (Resolve) does not carry the lead and tail, so a film cut in an editor has the lines at their shots.

### A look for one scene or one shot (unreleased, after 0.31.1)

| Kind | Engine (`analysis/tests`) | Screen (`src/__tests__`) and shell |
|---|---|---|
| **Unit** | `test_stylebible` (17, one of them runs the real command as 8 processes at once): shot beats scene beats film; an older project without the keys is unchanged; an unknown look, a genre feel or a non-text value is ignored; the film's notes still apply; set, read and clear; a project with no look, or an early text look, can still get one | `stylestale.test.ts` (5: the look a shot is played in; a take is compared with the shot's own look; picking the inherited look clears), `shotlook.test.tsx` (8: the options, the first option's wording for scene or film, the saved call for that shot only, the picker opened from the Look chip) |
| **Integration** | the look reaches the compiled prompt; each queued job records the effective look; the app's real call (`python -m filmcrafter_engine.stylebible`) with 8 changes at the same moment, none lost | `cargo test`: choosing the film's look keeps the scene and shot looks |
| **Regression** | remaking the render project from the film (`make.sync`) used to drop every scene and shot look | picking the look a shot already inherits used to store a pointless own look |
| **Security** | a bad shot id (`../x`, `..`, empty, a slash, a space, 80 characters, a number), a bad scene number, an unknown look, a genre feel and a folder that is not a project are refused and nothing is written; a damaged project file is left exactly as it was | none |
| **Money** | changing a look never calls `enqueue` or `run` and never touches `jobs.json` (a test makes either call fail the run) | the save call asks the app for the look only: no render, no price |

Whole suites after this change: `pytest` **2,187 passed**, 6 skipped (after the BytePlus provider); `vitest` **658 passed** (83 files); `playwright` **63 passed** (7 look tests, 45 accessibility, 11 first-run); `cargo test` **14 passed**; `cargo clippy -D warnings`, `tsc --noEmit` and `npm run build` clean. `rafter secrets .` finds one test fixture in `src/docshots/main.tsx` (a placeholder, unchanged); `rafter run` could not run (the plan's scan allowance for the period was used up).

Bugs found by this pass and fixed: (1) **`make.sync` wiped the scene and shot looks** each time the render project was rebuilt from the Bible (a failing test first); (2) a shot picked in the look it already inherited was stored as its own look and got the gold chip; (3) the app could make a `project.json` out of a folder that was not a project; (4) choosing another film look in the picker replaced the whole look setting, dropping scene and shot looks (found earlier, test in `cargo test`); (5) the picture check and the take review judged a shot in its own look against the film's look.

**Browser checks (added after the first QA pass):** the new screens were looked at in a real browser (the screenshot harness: scenes `shotlook`, `shotlook-own`, `shotlookpicker`); that found the look-changed note's warning icon squeezed and centred against three lines of text, and the panel tag wrapping the title. jsdom component tests (7 for the panel and the picker) and Playwright tests in Edge (7: set and clear a look on the Shot tab and the header chip follows, a shot with its own look, the chip's picker, Escape, no render button, axe on both screens) found that the panel folded shut when its look was cleared, and that the picker for one shot handed back the film's notes. An axe-core scan of **all 43 harness scenes** finds no WCAG 2.1 A or AA violation (`e2e/a11y.spec.ts`).

**NOT checked:** the whole Studio in a browser (its `?mock` preview needs a `mock-data/` folder that is not in the repository), so the Look chip and panel were seen in the harness's inspector, not inside the running app; a real provider drawing a shot in a different look from its neighbours; the installer; people using a screen reader or only a keyboard (an automated scan finds roughly a third of accessibility problems).

### Picture sizes: Seedream 5 Pro and 4.5 (unreleased, after 0.31.1)

| Kind | Engine (`analysis/tests`) | Screen (`src/__tests__`) |
|---|---|---|
| **Unit** | `test_picture_size` (20): the K words (1K, 2K, 4K, auto_1.5K); the size plan for Kie's basic or high and fal's exact width and height; the size stays inside what fal accepts for 7 shapes; video models and other quality words untouched; a Director Mode pin still wins | `modelpickersize.test.tsx` (the *up to 2K* mark on the card and the list) |
| **Regression** | Nano Banana Pro (1K, 2K, 4K) asked for 4K at every tier, a draft included | none |
| **Money** | a price learned at the basic size is never shown for a bigger one; a bigger size with no price says so and is counted at a high price; queued big pictures count at their own price; fal is priced on the pixels asked for; each job records its size | none |

What was checked against the providers' own published schemas on 2026-10-30 (not a render): Kie lists Seedream 5.0 Pro (text and image) with `quality` basic (1K) or high (2K) and Seedream 4.5 with basic 2K / high 4K; fal lists Seedream 5.0 Pro with `image_size` up to about 4.6 million pixels and Seedream 4.5 up to `auto_4K` (4096 on a side). **NOT checked:** a real picture at these sizes from either provider; what a 2K or 4K Seedream picture costs on Kie or fal (fal's price list needs your key; Kie shows a price only after a render); whether fal's `{width, height}` form is accepted for these models in practice (the schema allows it); whether Kie's `high` really returns 2K / 4K pixels.

### BytePlus ModelArk (Seedream direct) (unreleased, after 0.31.1)

| Kind | Engine (`analysis/tests`) | Screen (`src/__tests__`) and shell |
|---|---|---|
| **Unit** | `test_byteplus` (28): every size inside the published pixel range for 9 shapes and 4 tiers; the tier to level map; the published prices, the exact 2.61-million-pixel step, the extra-reference fee; the manifest's reference limits (10 or 14); the catalog and its *up to 2K / 4K* marks | `byteplus.test.ts` (the name and the automatic model); `cargo test`: the key slot, the name and no free pass |
| **Integration** | the request body BytePlus documents (endpoint, Bearer header, `b64_json`, `watermark` false, `output_format` only for the 5.x models); references as lower-case base64 pictures, a list for several, at most the model's limit, a JPEG copy for a large file; queued, sent, finished and counted at the exact price, with the HTTP call replaced | none |
| **Security** | no key: nothing is sent; `http://`, `ftp://`, `data:`, a missing file and a file that is not a picture are refused before any request; 401, 429, 400, 500, a non-JSON error page, a moderation refusal, an empty answer, a timeout (said to be possibly billed) and a connection error, none of them showing the key; a refused send costs nothing and the job records no key; the health check makes no call | none |
| **Regression** | a price such as 4.5 cents was shown and counted as 4 | none |

**NOT checked:** a real picture from BytePlus (endpoint, key header, sizes and the `b64_json` reply are from their documentation, read 2026-10-30, and the tests replace the HTTP call); Seedream 5.0 Flash's size limits (BytePlus lists its levels as Pro's, and the same range is assumed); a BytePlus account's regional or sign-up requirements; what a refused picture or a long wait really costs; BytePlus's own rate limits.

### First-run UX pass (unreleased, after 0.31.1)

Looked at in a real browser (Edge, the screenshot harness), screen by screen: Home, New film, the story workspace, Make, Export, Studio, Choose your picture model and Connections (Settings). Most were already built around one orange next step, prices shown first and "Let FilmCrafter choose"; the problems found and fixed: (1) **the Studio's top-bar icons covered the inspector's title** at every window width (the bar's content is wider than its column; a fixed padding had been left for one icon, there are now three); (2) **Connections** was one flat list in no order with a wrapping "Not connected" and rows that changed width; (3) **the rail** showed fifteen buttons, every advanced tool equal to the path; (4) **a critical accessibility fault**: the Interface size dropdown had no name. Tests: `e2e/ux.spec.ts` (11), `keyrows.dom.test.tsx` (8), and the accessibility scan now includes Settings. Playwright: **63 passed**.

**NOT checked:** the real Studio with real data (its browser preview needs the `mock-data/` folder that is not in the repository), so the header and rail were checked on the harness's made-up film; people using the app for the first time (the most important test of "intuitive"); a screen reader or keyboard-only use by a person; macOS and other window scales; the narrow-window (under 1100 px) layout; the other screens (Cast & World, Shots, Compose, Sound plan and the rest) were not reviewed for flow in this pass.

### A look of its own reaches the characters (unreleased, after 0.31.1)

`test_stylebible` (26, 10 new): the prompt of a shot or scene in a look of its own keeps who the people are but draws them in the look, tags the references as content-only, and no longer says "identical skin tone, face, hair and clothes"; a shot in the film's look is written exactly as before; keeping the cast changes only the world; the shot before is used fully only when it is in the same look; the option is saved, read and cleared per shot and refused for bad ids and non-projects. `shotlook` component and browser tests cover the option and the new wording. **NOT checked:** a real model's picture. The cause (the prompt and the reference labels pulling the characters back to the film's look) was found by reading the compiled prompt, and the fix changes the words and the reference labels; how strongly a given model then restyles the characters is not known until a real keyframe is made. If a model still keeps the characters' old rendering, the next step is a reference sheet made in the new look (one per character per look).

## Not tested (be honest about these)

- **A human walk-through of the installed app** (in particular the Guide, bringing materials in from a real storyboard, the Action scene sheet, and the player's Play on a film with no sound file). Everything above was driven by tests, a headless browser and scripts. Nobody has used the installed Windows app end to end for a real film.
- **Premiere Pro and Final Cut Pro** importing the hand-off (Resolve only).
- **macOS** (no Mac), **code signing and the updater** (no certificate; Windows warns about the installer).
- **Providers other than Kie.ai** (fal, Google, OpenAI; Google's Nano Banana 2.1 is reachable with your key but has not made a picture) for pictures and video; a **whole multi-shot film** with character pictures; the **hands and faces check** with a real vision model.
- **New frame shapes** (21:9, 9:16...) on a real provider: whether a model returns that shape depends on the model.
- **Long videos**, **low-end machines**, **screen readers** and **keyboard-only use** by a person (the automated scan above is the only accessibility test).
- **Money limits under failure** (a provider charging for a job that then fails) beyond what the mock provider tests cover.

## How to re-run everything

```
python scripts/test_all.py                          # engine, screens, shell, security in one table
npx vitest run ; npx tsc --noEmit                   # screens and types
cargo test --manifest-path src-tauri/Cargo.toml     # the shell
npm run dev                                         # then, in another terminal:
PF_QA=1 node scripts/docshots-edge.mjs              # all 40 screens, fails on any console error
python scripts/make_look_docs.py                    # after adding a look
python scripts/live_test.py                         # one real picture (prices first; --yes to spend)
python scripts/make_handoff_sample.py "<folder>" && python scripts/resolve_check.py "<folder>"   # the Resolve import check
```
