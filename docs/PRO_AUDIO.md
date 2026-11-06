# Professional audio export (0.43.0)

Seventh slice of the SonicStage plan. **Status: built and tested by writing real files and reading them back, including with ffmpeg and the real OpenTimelineIO library. Nobody has opened an export in Pro Tools, Reaper, Resolve, Premiere or any other editor, and nobody has listened to the mixes.**

Where: **Sound & Music > Scenes > Audio for a sound editor > Open audio export...** Free and local: nothing is sent anywhere and no model is used. The film's own files are only read.

## What it writes

One folder, `exports/audio/<title> <time>/`:

- **stems/** one file per lane: dialogue, foley, effects, ambience, music (a lane with no sound gets no stem and the report says why; a lane you left out in your mix settings is skipped). Every file is the film's full length and starts at the same timecode, so they line up in any editor. They carry the film mix's own ducking, levels, fades and stereo balance, and **no limiter and no loudness change**: they are the mix *before the master stage*.
- **mixes/** `FINAL` (everything) and `M&E` (music and effects, no dialogue, for dubbing). Each is the sum of its stems times **one steady gain**, so applying that gain to the stems gives the mix exactly (a test checks this). The gain brings the mix to your loudness target (broadcast -23, US -24, online -16, streaming -14, or leave it) without any true peak going over your ceiling (-1 to -6 dBFS). There is **no limiter**: if the target cannot be reached without breaking the ceiling, the ceiling wins and the report says so.
- **cue sheet** (`.csv` and `.json`): every voice line and every sound, with its lane, name, scene, shot, timecode in and out (offset by your start timecode), level, balance, where it came from (imported, generated, recording, ElevenLabs, re-voiced, ADR), provider and model, licence source, commercial-use flag and note, and approval. Cells that could run as a spreadsheet formula are neutralised.
- **audio.otio**: an OpenTimelineIO timeline with a track per lane (more than one track where sounds overlap) and a clip per sound, each pointing at a **copy** of the original in `media/` (your originals are never touched). A looping sound is laid end to end over its span.
- **README.txt** and **report.json**: the settings, what was measured, what was read back, and what was **not** checked.

Formats: 44.1, 48 (default) or 96 kHz; 16-bit, 24-bit (default) or 32-bit float; **Broadcast WAV** (a `bext` chunk: description, originator, reference, date and time, the start timecode as a time reference in samples, the file's loudness for mixes, the coding history) or plain WAV; start timecode 00:00:00:00 or 01:00:00:00.

## How it was checked

After writing, every file is read back as other tools would: its sample rate, bit depth, channel count and length against the film's, that it is not silent, and the Broadcast chunk's time reference and originator. The tests also read the chunk with **ffmpeg** (an independent reader found `time_reference`, `originator_reference` and the description) and the timeline with the **real OpenTimelineIO library**, and check that each stem holds only its own lane, that the mix equals the stems times the gain, that the loudness lands on the target (measured with ffmpeg's EBU R128 meter), that a moved line sits where Timing and ADR put it, and that nothing in the film changed.

## What it does not claim

- **No editor has opened these files in this project's testing.** Broadcast WAV and OpenTimelineIO are standards and the files were validated against readers, but an editor may still ask for something different. Try one export in your editor before you rely on it.
- **Positions follow the film's shot list**, not the finished cut: shots in scene order at their lengths, each person's recordings in order with the usual gap and moved by the frames set in Timing and ADR (the same model as the Sound & Music preview). If you trimmed or re-timed shots in the Studio's cut, the finished film's picture may place them differently; the editor hand-off's tracks follow that cut.
- Timecode is at 24 frames a second, non-drop. No 2-pop, no M&E dialogue-fill, no surround or Atmos, no per-person dialogue stems, no iXML or AAF, no RF64 for files over 4 GB (a film is limited to 20 minutes).
- Nobody has listened to the mixes.

## Also in this release

The mix now has a separate **Foley** lane. Cues made from Foley events (Sound design) are marked as Foley, so they have their own stem and their own mute and "Foley only" preview; ordinary effects stay in Effects. Cues made before this release stay where they were.

## Where it lives

`analysis/filmcrafter_engine/proaudio.py`; shell command `film_proaudio` (plan, export; no key is given to it); screen `src/ProAudio.tsx`; the mixer gained a `raw_float` option for stems (`audiomix.mix_cues`) and cues a `foley` mark (`audiocues`).

## Tests

`analysis/tests/test_proaudio.py` (21) and `src/__tests__/component/proaudio.dom.test.tsx` (7). The OpenTimelineIO checks need the `opentimelineio` package (a test-only dependency, listed in `analysis/requirements.txt`); they are skipped without it.
