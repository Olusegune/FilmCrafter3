# Speech to speech: perform a line yourself (0.37.0)

**Status: experimental.** The engine, the records, the safety checks and the screens are built and tested with a stand-in for the voice-conversion program, and the real Install and a real conversion have been run once through the engine (2026-11-06, see "What was and was not tested"). Nobody has listened to a converted take yet, and the screens have not been used with the real model.

## What it does

You act a line in your own voice (record it in the app, or choose a recording). FilmCrafter changes only the voice into the character's voice, on this computer, and keeps your timing, pauses and feeling as far as the model can. The result is a **new take** of that line, next to the spoken takes in Line Studio. It is attached to the shot only when you press **Use this take**.

- **Local and free.** Nothing is uploaded, no key is used, nothing is paid for.
- **Nothing is overwritten.** Your recording is copied into the film under its content hash and never changed. A converted take is a new file; the same performance and reference voice give the same take, so nothing is made twice. Choosing a take archives the one it replaces in `voice/_removed`.
- **Marked as synthetic.** Every converted take's record says `synthetic: true`, who performed it, which model changed the voice and its licence, and which reference voice and consent were behind it.

## Using it

Line Studio (open a clip on the timeline) > **Perform it yourself**.

1. **Install** (once). The button shows the model, licence (MIT), the size (several gigabytes; the exact figure is not known until installed) and the hardware notes, and downloads nothing until you confirm. Everything goes into `~/.filmcrafter/voiceconv`, outside any film. Deleting that folder removes it.
2. **Sound like.** Choose the voice the character should end up with:
   - a take already spoken in the character's cast voice (needs no permission: it is synthetic), or
   - a recording of a real voice, 3 to 60 seconds. This needs the owner's agreement ticked, whose voice it is, and what it may be used for.
3. **Perform.** Record, or choose a recording (up to 5 minutes).
4. **Change it into the character's voice.** About a minute on most computers.
5. **Compare** your performance and the converted take, then **Use this take**.

Permission can be taken back at any time. A revoked reference voice is never used again and the record of it stays.

## Where things are kept

| Path | What |
|---|---|
| `voice/revoice.json` | each character's reference voice, its consent, and a log of conversions |
| `voice/_reference/<person>/` | the reference voice sample (copied in) |
| `voice/_performances/` | your performances (copied in, never changed) |
| `voice/_generated/<shot>-rv<hash>.wav` + `.json` | the converted take and its record |
| `~/.filmcrafter/voiceconv/` | packages and model files (not in a film) |

Note: film backups skip `voice/_generated` (as they do for spoken takes), so a converted take is not in a backup. It is rebuilt exactly from the performance and reference voice, which are backed up. Run the conversion again.

## Safety rules the engine enforces (each has a test)

- Install refuses without `confirmed`. A conversion never downloads anything: the model library runs offline, and the model files are fetched only by the Install step.
- A real voice is refused without `consent`, the voice's owner and the permitted use. A reference voice that is revoked, missing, or **changed after consent was given** (its SHA-256 no longer matches) is refused.
- Replacing an approved character's reference voice needs an explicit yes.
- Files named relative to the film cannot leave it (`..` and drive paths are refused). Shot ids and character names are validated.
- A result that is empty, silent, or a very different length from the performance is refused and nothing is kept.
- The program runs as a separate process with a fixed argument list (no shell), its own package folder and a request file that is deleted afterwards.

## What was and was not tested

Tested (automated, stand-in for the model): install gating, consent and revocation, tamper check, take creation and immutability, caching, take list and choosing, archive of the replaced recording, bad-output refusal, path safety, the command line, and the screens (install confirmation, consent form, convert, A/B compare, error display).

**Real run through the engine (2026-11-06, Windows 11, processor only, no fakes).** Install (pip into `~/.filmcrafter/voiceconv/site` plus the model files) worked: 3.0 GB on disk, `torch 2.6.0+cpu`, `torchaudio 2.6.0+cpu`, `chatterbox-tts 0.1.7`. Test audio was two Windows text-to-speech voices (not human recordings): a male voice saying a line (8.0 s, median pitch 92 Hz) converted to a female reference voice (8.7 s, 178 Hz). The conversion took 33.9 s including model load, produced an 8.0 s, 24 kHz file (peak 0.79) with median pitch 157 Hz, i.e. moved most of the way to the reference. Asking again was served from the cache in 0.08 s. The three files are on the owner's Desktop (`listening test`) for a listening check.

**Not tested:** how the converted voice sounds to a person (a pitch measurement is not a quality judgement); human recordings and real accents; the microphone recorder in this flow; the screens driving the real model; Install through the app's own Install button; Windows scaling and screen-reader use of the new panel.

Greenroom Local's own record (`docs/SPEECH_TO_SPEECH.md` there): a real run on a Windows 11 processor converted an 8.09 s male recording into a female reference voice in 36 s including model load; timing was kept to 0.01 s and the median pitch moved from 94.5 Hz towards the target (148.8 Hz against 180.5 Hz). That worker script is not in Greenroom's repository, so FilmCrafter's `vc_worker.py` was written against Chatterbox's public voice-conversion interface (`ChatterboxVC.from_pretrained` and `generate(audio, target_voice_path=...)`); the real run above shows it works with chatterbox-tts 0.1.7.

## Known limits

- One model (Chatterbox voice conversion, MIT, by Resemble AI). Identity similarity, pitch and strength controls are not offered because this model does not expose them.
- Installation pins `torch==2.6.0`, `torchaudio==2.6.0` and `chatterbox-tts==0.1.7` (what Greenroom used) from PyTorch's CPU index plus PyPI. pip cannot restrict a package to one index, and no hashes are pinned, so installation trusts both indexes.
- Windows only for now. CPU runs by default; a graphics card is used if the installed PyTorch supports it (the CPU build does not).
