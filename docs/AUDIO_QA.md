# Audio quality inspector (0.41.0)

Fifth slice of the SonicStage plan. **Status: built and tested on synthetic audio with known faults, through the real ffmpeg loudness meter. It has not been run on a real film's recordings, and every limit below is a plain number chosen for this tool, not an industry standard.**

Where: **Sound & Music > Scenes > Check the sound**. Free, local and **read-only**: it reads sound files and writes nothing (a test hashes the whole film before and after).

## What it measures

For each sound file: peak and **true peak**, **loudness** (LUFS, loudness range) from ffmpeg's EBU R128 meter, **clipping** (runs of flattened samples), **silence** (leading, trailing and inside), the **noise floor** (only where there are quiet moments between the loud ones), **dropouts** (5 to 300 ms of digital silence inside loud sound), **clicks** (sudden jumps in the waveform), **DC offset**, and whether the two channels **cancel when folded to mono**.

Across the film it checks:
- every recording and spoken line, as a voice (a long silence *inside* a recording, steady noise under it);
- every sound in an approved cue (clipping, clicks, dropouts, DC);
- a finished film file if you choose one (loudness against your target in Sound & Music, true peak);
- a recording **longer than its shot**;
- a cue that **starts or stops at full level with no fade** (a click risk at the edit), unless it loops or has a fade;
- a line recorded much **louder or quieter than the same person's others** (6 dB or more from their median, only when they have three or more lines; reported as a low-confidence note because a different room or a whispered line can cause it);
- **more than one voice, source or model** behind one person's lines (read from the sidecars of spoken takes).

Each finding says where it is, what it found in plain words, the number, and the limit it was compared with. Severities: **fix** (silent or unreadable, heavy clipping, three or more dropouts), **look** (worth a listen) and **note** (information).

## What it does not do

It gives **no quality score**. It does **not** measure how clear speech is, how good anything sounds, whether an accent or a voice is authentic, whether a mouth matches the words, or how loud the stems are against each other, and the screen says so. A finding means "listen here", not "this is wrong".

Known weak spots: the noise floor and click detectors are rules of thumb that can miss or over-report on real material (heavy music, whispered speech, deliberately distorted effects); a deliberate silence in a recording is reported as a long silence; voice consistency compares loudness only (no timbre, pitch or similarity model).

## Where it lives

Engine `analysis/filmcrafter_engine/audioqa.py` (`measure` is pure: a sound in, numbers out; `findings`, `inspect_file`, `film`); shell command `film_audioqa` (film, inspect; no key is given to it); screen `src/AudioCheck.tsx`. A file you name must be inside the film or chosen with a full path; the engine passes it to ffmpeg as an argument, never through a shell.

## Not tested

Real recordings, real music and ambience, a long film (the checks are capped at 60 recordings and 60 cue sounds, and a file over an hour is refused); the panel with a screen reader or at 125% or 150% scaling; whether the limits suit your sound.

## Tests

`analysis/tests/test_audioqa.py` (23: each measurement against a sound with a known fault and against a clean one, thresholds and severities, noise only where pauses exist, a long silence inside versus at the ends, real files and loudness through ffmpeg, a hot file's true peak, missing and unreadable files, recordings named by who and where, longer than the shot, louder or quieter lines, too few lines to compare, more than one voice or model, abrupt edits with and without a fade or a loop, a finished film inside or outside the film, nothing changed, the command line) and `src/__tests__/component/audiocheck.dom.test.tsx` (7).
