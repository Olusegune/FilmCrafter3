# Sound design: soundscapes and Foley (0.40.0)

Fourth slice of the SonicStage plan. **Status: built and tested with real audio through the real mixer, using synthetic tones. Nobody has listened to a designed scene, and no sound generation or paid call was made.**

Where: **Sound & Music > Scenes > (a scene) > Sound design > Open sound design...**

## What it adds

**A soundscape profile for each place.** The Production Bible already lists places. A place can now say whether it is inside or outside, the weather, the time of day, the room, its materials and surfaces, a reverb note, sounds that come back, and **ambience layers**: a name, a distance (near, middle, far), a level and a sound from the library. The profile belongs to the *place*, not to a shot. "Put into the film" makes **one scene-wide looping cue per layer**, so the ambience is the same in every shot of the scene whatever the camera does.

**Foley events.** One event is one motivated sound: what it is (impact, footsteps, door, stirring...), the thing that makes it, who does it, its material, its surface, how hard, how far away (near / middle / far), on which side (left / centre / right), when in the shot, which library sound covers it, and whether you approved it. **Suggest sounds** reads a shot's written action with plain rules (no AI, nothing sent, nothing saved) and proposes only sounds the action *names*: a drop, a slam, a stir, a step. At most six per shot, the most dramatic first, each with the words that motivated it. Quiet movement the action does not name gets no sound, and a person is named only when the same sentence names them. The timing is an estimate from where the action falls in the text: move each one to the moment you see it.

**Find in my library** looks through your sound library for a sound that fits (free; rejected sounds are never offered) so you reuse before you make anything.

## How it reaches the mix

Events and layers are plans. **Put into the film** turns the *approved* ones that have a sound into ordinary audio cues, so the existing mixer, ducking, mute lanes and loudness target apply. Doing it again updates the same cues (a changed event changes only its own cue); swapping a sound replaces it in the same cue; removing an event takes its cue out of the plan (the sound stays in the library, nothing is deleted). Events and layers without a sound are listed as waiting, never guessed.

**Distance and side** become a level (near 0 dB, middle -6 dB, far -14 dB, and a little louder or softer with how hard the sound is) and a **stereo balance** (left, centre, right). Cues gained a `pan` for this (old cues have none and stay in the centre; the centre is untouched and a panned sound never gets louder).

## What it is not

- **Not an acoustic simulation.** There is no room model, no occlusion and no reflections. Distance is a level; side is a balance. The reverb setting is a note for you and for making sounds; **the mixer does not add reverb yet**.
- **Not spatial audio.** It is a stereo balance. It is not Dolby Atmos or any multichannel format.
- **Not linked to a 3D set.** There is no WorldLock yet; places come from the Bible, and objects are named in words, not by an object id.
- **Not an automatic sound for every movement.** That is on purpose.

## Where it lives

`audio/sounddesign.json` in the film (profiles, events, removed events), written atomically. Cues are in `audio/cues.json` as before. Engine: `sounddesign.py`; the shell command is `film_sounddesign` (scene, profile_set, suggest, event_add, event_update, event_remove, candidates, to_cues; no key is given to it).

## Not tested

Anything by ear. Whether the suggested timing and the distance steps (0 / -6 / -14 dB) sound right on a real scene. Foley suggestions on real screenplays beyond the test scripts (the rules are plain keyword rules and will miss or over-read some wording). The panel with a screen reader, or at 125% or 150% scaling.

## Tests

`analysis/tests/test_sounddesign.py` (23: what is and is not suggested, the cut to a few, nothing saved by suggesting, level and balance, profile cleaning and stable layer ids, sound existence checks, event validation, removal, library search, cues made and updated in place, scene-wide ambience, a swapped sound, the scene view, **the real mixer**: a sound panned left or right is louder on that side, a far sound is quieter than a near one by the distance amount, old cues without a pan still mix in the centre, pan range, the command line) and `src/__tests__/component/sounddesign.dom.test.tsx` (9).
