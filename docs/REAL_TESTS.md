# Real-world tests of the SonicStage work (2026-11-06)

The earlier slices were tested with synthetic sound and answers written by hand. This is what was measured with real speech, one small paid call and the real engine's output. **Nothing here was judged by ear**: a person still has to listen (see "Listening files").

## How

- **Real speech without a person:** two Windows text-to-speech voices (David, Zira) say the same sentence. They are real speech with real pauses, breaths and sharp pulses, which a synthetic tone is not. Windows' offline recognizer transcribes the results as a rough check that the words are still understandable (`scripts/real_speech_check/`; Windows only; the recognizer is weak: it misreads about one word in eight of clean text-to-speech, so only changes against that baseline mean anything, and it cannot judge neural voices at all).
- **One paid call:** three short lines on ElevenLabs (the owner's key, from Windows Credential Manager, never shown or saved; the owner allowed up to 5 USD). The performance plan was compiled for Eleven v4 and for Multilingual v2. Estimated 136 credits (61 + 36 + 39 characters); ElevenLabs reported 30 credits of use; the film's ledger had a 400-credit ceiling. Pay-as-you-go account.
- **The real engine's answers against the real screens:** 20 JSON answers made by the real engine (`scripts/make_engine_fixtures.py`) fed to the real components (`src/__tests__/component/enginecontract.dom.test.tsx`).

## What was found, and fixed

1. **The audio inspector over-reported on clean real speech.** First rules: David got a "true peak" and six "click" findings, Zira a "noise" and a "click". The clicks were the sharp pulses of a loud low voice (jumps of 0.15 to 0.17 against a local peak of 0.95), and the "noise floor" was a breath (10th percentile of the window levels: -40 dBFS in a recording whose pauses are not noise). Fixed: a click must also exceed 0.6 of the local peak and 8 times the median jump of the neighbouring blocks; the floor is the quietest 5% (and the limit is -45 dBFS). Measured afterwards: David gets only the true-peak note (correct: his peak is -0.2 dBFS), Zira none; noise added at -50, -45, -40 and -35 dBFS is found and the floor follows it (-53, -48, -43, -38); a real two-sample click injected into real speech is still found. Three regression tests use two short real-speech fixtures (`analysis/tests/data/real_speech_*.wav`).
2. Nothing else broke. In particular **the screens and the engine agree**: all eight contract tests passed with the real answers, with no `undefined`, `NaN` or missing field on any screen.

## What was measured

| Check | Result |
|---|---|
| Dub-fit, 5.5% faster ("natural") | 7.49 s to 7.08 s (predicted 7.10); pitch 89.3 to 89.5 Hz; recognizer error against the text 0.04 (original 0.125) |
| Dub-fit, 11.8% faster ("audible") | 7.49 s to 6.68 s (predicted 6.70); pitch 89.3 to 88.7 Hz; recognizer error 0.04 |
| Line-up, the same voice delayed by 0, 0.4 and 1.1 s | exact (0.000 s error) |
| Line-up, a *different voice* saying the same words, delayed by 0, 0.4 and 1.1 s | suggestion within 6 ms of where the speech actually starts, match 76%; the 0 s case was accurate but reported "not confident" (a borderline score), the others confident |
| Pro export of real dialogue, 48 kHz / 24-bit / Broadcast WAV, FINAL mix at -23 LUFS | every file read back with no problem; the FINAL mix measured -23.0 LUFS, true peak -6.1 dBFS (a -6.0 dB master gain); the dialogue stem's transcript is word for word the original's |
| Eleven v4 line with a plan (`[sighs] I did not THINK... [gasps] you [sad] would come back.`) | 5.12 s, -30.4 LUFS; the same words with no direction 2.24 s, -25.2 LUFS; compiled for Multilingual v2 (pause only) 2.32 s |

The tagged line is more than twice as long and 5 LU quieter than the plain one, so the model clearly acted on the direction (sigh, pause, gasp, softer delivery). No tag word ("sighs", "gasps", "sad") appears in any transcript, but the recognizer misreads even the plain neural line, so that is only weak evidence the tags were not spoken aloud. **Whether the sigh, the gasp and the sad turn sound right is for a listener**; `sad` was marked "not checked" and still is.

## What this does not show

- Nothing about how any of it sounds. The Windows recognizer cannot hear a sigh.
- Real human recordings, real room noise, music and ambience: all these voices are clean text-to-speech.
- The installed app driven by a person, an editor opening an export, and the in-app microphone recorder.
- Anything on a Mac.

## Listening files (on the owner's Desktop)

`FilmCrafter3 real tests / 2 ElevenLabs performance plan`: the three ElevenLabs lines with a note on what to listen for. (The speech-to-speech files from the earlier real run are in `FilmCrafter3 0.37.0 update / listening test`.)
