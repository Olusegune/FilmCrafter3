# Timing, dub-fit and ADR (0.42.0)

Sixth slice of the SonicStage plan. **Status: built and tested with real audio, real ffmpeg and the real mixer, on synthetic recordings. Nobody has listened to a fitted take or an ADR retake, and the line-up suggestion has only been checked against synthetic sound.**

Where: Line Studio (open a clip on the timeline) > **Timing and ADR > Open timing and ADR...** It needs a recording attached to the shot.

## Placement in frames

Move a line earlier or later by **whole frames** (-10, -1, +1, +10, or put it back). Time is exact: it uses the film's frame rate as two whole numbers (24, 23.976 as 24000/1001, 25, 29.97 and the rest; 24 when the film does not say) and shows a timecode inside the shot (hh:mm:ss:ff, non-drop). The offset is a record in `voice/sync.json`; it is applied when the film is made (the renderer passes it to the mixer, which places the line that much earlier or later; the next line in the shot does not move). A line can start before its picture (a J cut). The limit is 5 seconds either way. The recording is never changed. A line that would run past the end of its shot is flagged.

Because the render project is rebuilt from the film, a moved line reaches the finished film the next time the film is made; the screen does not re-render anything for you.

## Dub-fit

If a line is a little too long for the space it has (the shot's length minus where the line starts minus 0.1 s of air), a **fitted take** is made with a pitch-preserving tempo change (ffmpeg `atempo`) and kept **beside the other takes**: the original stays, nothing is attached until you choose the take. A change up to **8%** is called natural, up to **15%** audible (listen first), and more than that is **not offered**: shorten the line, lengthen the shot or record it again. (You can insist after a warning.) The result is checked for length and silence before it is kept, and the same fit is never made twice. Pitch is kept; a test measures it.

## Lining up with the picture

**Line up with the picture's sound** compares the loudness shape of the shot's own sound (or a guide file you name) with the recording over +/-2 seconds and suggests how many frames to move it, with a match percentage and whether it is confident. It only suggests; you apply it. It compares loudness shapes, **not words**: there is no word-level alignment model here, and the sound a video model made is only a useful guide if it says the same thing at the same pace. When it is not confident it says so.

## ADR

Mark a line as **needing ADR** with a reason (a dog barks, a plane passes). `adr_list` also lists recordings the audio inspector found problems in that a retake could fix (clipping, steady noise, dropouts, clicks, a long silence, a recording longer than its shot): each reason is a place to listen, not a verdict. **Record an ADR take** (the in-app recorder) or **Add an ADR recording...** (a file): it becomes a **new take** beside the others (your original is kept untouched in `voice/_adr`, a copy is made at the film's sound format), is marked with who performed it, and is chosen like any take. Nothing is replaced.

## Where it lives

`voice/sync.json`; `voice/_adr/<hash>`; takes in `voice/_generated/<shot>-ad<hash>.wav` (ADR) and `<shot>-df<hash>.wav` (fitted), each with a `.json`. Engine `analysis/filmcrafter_engine/adrsync.py`; shell command `film_adrsync` (get, nudge, fit_plan, fit_make, align, adr_mark, adr_list, adr_take; no key is given to it); screen `src/TimingAdr.tsx`. The take list and `use_take` in `cast_voice` accept the new kinds; `voiceover.to_render` and `mix_into` apply the offset.

## Not built / not tested

- **Word-level alignment** (no alignment model), **audio-first generation and lip-sync handoff** (the sound plan already routes shots; this slice does not change it), **cue markers and timecode export** (that belongs to the pro export slice), **pitch-shifted dub-fit** (tempo only), a **playback-while-recording ADR booth** (the recorder does not play the picture).
- The film-level timecode of a line (this shows time inside the shot). Drop-frame timecode (29.97 counts at 30, non-drop).
- Not tested by ear: fitted takes, ADR retakes; real recordings against a real picture sound; the panel with a screen reader or at 125% / 150% scaling.

## Tests

`analysis/tests/test_adrsync.py` (23: frames and timecode at the common rates, round trips, the film's frame rate, a line's timing, moves by frames and limits, runs-past flag, **the real mixer places a moved line 12 frames later or earlier**, fit plan classes, fitted take length and pitch and the original untouched, no duplicates, refusal of changes that sound wrong, choosing a fitted take and archiving the old recording, line-up in both directions, an unrelated sound not confidently matched, applying a suggestion, no picture sound, path safety, ADR marks and list, ADR takes kept beside the others, no duplicates, bad recordings refused, choosing an ADR take, the command line) and `src/__tests__/component/timingadr.dom.test.tsx` (11).
