# Vocal performance plans (0.39.0)

Third slice of the SonicStage plan. **Status: built and tested without speaking anything. No ElevenLabs call was made, so nobody has heard what a compiled line sounds like.** Several of the tags it can write have not been confirmed to do what they say; the screen labels them "not checked".

In Line Studio, **Direct the performance > Plan the performance...** plans one line: what the person wants, how the feeling changes *inside* the line, where the breaths, laughs and efforts fall, how the body affects the voice, the pace, pauses and stressed words. It is free, and the plan is yours to edit.

## How it works

The plan is model-independent. It is turned into words only for the model that will speak the line (the character's own model, shown on screen), and **only what that model can really be asked for is carried**.

- **Positions are gaps between words.** "Before the first word", "after *not*", "after *back* (the end)". Feeling changes, sounds and pauses all use them. A position that is not in the line is dropped, never moved to the nearest one.
- **Eleven v4 / v4 Turbo / v3** read `[tags]` as direction: a feeling change becomes `[sad]` at its gap; a sound becomes `[gasps]`, `[laughs]`, `[grunts]`...; stressed words are written in capitals; a pause becomes `...`; a body state (out of breath, straining, pain, tiredness) becomes a leading tag when it is strong enough. The suggested speed also follows pace, tiredness and breathlessness.
- **Other models** (Multilingual v2, Flash) would speak `[tags]` aloud, so none are used. Pauses are kept. Everything else is listed under **"This model cannot carry"** with the reason, and the screen suggests Eleven v4 or recording the line and using speech to speech.
- **Things a voice model cannot be asked for reliably** (speaking with food in the mouth, while drinking, shivering, in the rain) are said to be uncarried for every model; they need a recording, speech to speech or a sound effect.
- A feeling in your own words ("tired but trying to smile") is passed on as written and marked "not checked".
- Tags typed into the line are set aside: the plan works from the plain words and writes its own.

## What applying does

**Use as the spoken version** needs a saved, **approved** plan made for the line's current words, and sets the compiled words as the line's *spoken version* (the same thing Line Studio's "Save as the spoken version" does). It speaks nothing and costs nothing; your written line is never changed. You then press **Speak this** as before, with its price and its yes. A plan made for words that have since changed is flagged and cannot be applied.

## Which tags have been checked

The list of feelings and sounds comes with a `verified` mark taken from Greenroom Local's notes of what did what it says on a real run: whisper, laugh, sigh, gasp, cry, cough, out of breath. The rest (grunt, groan, strain, wince, pant, chuckle, giggle, sob, whimper, inhale, breath catch, throat clearing, sniffle, and every named feeling except whisper) are common conventions not yet confirmed in FilmCrafter. Treat the first spoken version as a try and retake it.

## Where it lives

`voice/performplan.json` in the film: `lines > shot > person > { plan, base_text, updated }`. Written atomically. The engine module is `performplan.py`; the shell command is `film_performplan` (get, set, apply, clear; no key is given to it).

## Not built yet

- Word-level control inside models that do not take tags, and any control over how loudly or how long a sound lasts (intensity is saved but no tag format for it is confirmed, so it is not sent).
- Having the writing assistant propose a plan from the script and the character (it would be paid; the plan format is ready for it).
- Linking the plan to the visual acting beats (`acting.py`, `performance.py`).
- Applying a plan to speech to speech: a recording carries its own performance.

## Tests

`analysis/tests/test_performplan.py` (20: cleaning and limits, positions, compiling for tagged and untagged models, the body, uncarriable things, unchecked tags, length limit, saving without touching the line, applying rules, stale plans, clearing, the command line; the network is switched off) and `src/__tests__/component/performanceplanner.dom.test.tsx` (7).
