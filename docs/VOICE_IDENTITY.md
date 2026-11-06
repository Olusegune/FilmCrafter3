# Voice identity (0.38.0)

Second slice of the SonicStage plan. **Status: built and tested with faked inputs; no real ElevenLabs call was made and nobody has used the new panel on a real film.**

A character's voice identity is the profile in the Production Bible, the voice they were given, and what this release adds: a lock that notices when the approved voice changes, your own listening ratings, a side-by-side casting comparison, and a cast library for using a character again in another film. Nothing here chooses, changes, sends or pays for a voice; everything is free.

Where: **Sound & Music > Voices > (a character)**, under "Suggest voices": **Voice identity**.

## Identity fields

The profile already had description, age range, accent, timbre, pace, emotional range, delivery and notes. Added (same profile, same save, same history; old films read as before): **language, pitch range, vocal weight, texture, breathiness, speaking rhythm, articulation, vocal habits, pronunciation notes**. The writing assistant is still asked only for the original eight fields.

## The lock

**Lock this voice** records which voice, speech model and reference voice (speech to speech) the character has now. From then on the panel says in plain words if the voice changed, if the model changed while the voice stayed the same, if the reference voice changed, or if the voice was taken off. The lock changes nothing and approving is still your separate act; an approved voice is still protected from silent replacement by the existing guard in `cast_voice` (changing it needs an explicit yes). Locking again replaces the lock; unlocking stops the watch. Both keep the old lock in the history. An approved voice that is not locked is shown as "Approved, but not locked".

## Listening ratings and accents

After you listen, record how convincing the accent was and how natural the voice sounded (1 to 5 each, either one) with a note. **FilmCrafter does not judge an accent.** The status is what your ratings add up to for the voice the character has now: "accepted" (average 4 or more), "not convincing" (2 or less), "mixed" or "not rated", and the panel says it is your judgement, not a measurement. Ratings are kept per voice in `voice/identity.json` (last 200).

## Casting comparison

**Compare voices from my library** searches your ElevenLabs library (free, using the profile's accent as the search) and lines the best fits up with: why each fits (from the labels ElevenLabs gives it: gender, age, accent and descriptive words), a free sample to hear, an estimate of what hearing it say a line would use of your plan, a licence reminder (ElevenLabs' own voices are covered by your plan; cloned or community voices need their owner's terms checked), where it runs (all candidates are online ElevenLabs voices; none are local), and what you rated it before. A voice's labels say nothing about how it performs emotion or how real its accent is, so those are not claimed. "Give this voice" asks first if the character's voice is approved.

## Cast library

**Keep (character) for other films** stores the profile and a reference to the voice in your ElevenLabs account in `~/.filmcrafter/cast_library.json` (no audio). **Use for (character)** in another film applies the profile and voice. It is never approved or locked automatically. A cloned voice carries a reminder and needs the owner's agreement confirmed again; an approved voice is replaced only after a yes.

## What is not here yet

- Accent verification by machine. Greenroom Local's accent test is also a listening rating sheet, so this matches it; there is no automatic check.
- Local voices as candidates (none are installed in FilmCrafter apart from speech to speech's reference sample).
- Pronunciation notes are saved and shown to the writing assistant but not yet applied when a line is spoken.
- Retiring a voice with history across projects (a revoked reference stays refused; the library has no remove button yet).

## Tests

`analysis/tests/test_voiceid.py` (21: profile fields, lock states, changed voice/model/reference, history, rating rules and statuses, caps, comparison ranking/cost/licence/bad candidates, library save/use/guards, command line; the network is switched off for every test) and `src/__tests__/component/voiceidentity.dom.test.tsx` (9).
