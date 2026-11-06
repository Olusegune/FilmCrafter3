# Mixer automation: volume curves, groups, markers, crossfades

Sound & Music > Scenes > **Volume curves and groups**. Free and local; nothing is sent anywhere and nothing is deleted. Code: `analysis/filmcrafter_engine/audiomix.py` (settings in `audio/mix.json`), `audiocues.py` (cue fields), `voiceover.py` and `proaudio.py` (the same curves in the voice mix and the export), screen `src/MixerAutomation.tsx`.

## What it does

- **Volume curves.** One curve per lane (Voices, Foley, Effects, Ambience, Music) and one for the **whole film**. A curve is a list of points: a time on the film, a level in dB (-60 to +12) and a shape for the stretch up to the next point: *Straight* (linear in dB), *Eased* (smooth start and end) or *Step* (holds, then jumps at the next point). Before the first point and after the last the level is held. Up to 200 points per curve. Times snap to the film's frames (24 fps unless the film says otherwise).
- **Cue curves.** A cue can carry its own curve (`auto`, up to 50 points), counted in seconds **from the start of that sound**, so it stays right if the cue is moved.
- **Groups.** A name (up to 40 characters, up to 20 groups) with one level and one mute. A cue joins a group through its `group` field. Muting a group leaves its cues out of the mix; removing a group gives the cues their own levels back (the cue keeps the name).
- **Markers.** Named points on the film's timeline (up to 200). They are written to the audio export's cue sheet (`MARKER` rows) and to the timeline file as OpenTimelineIO markers.
- **Crossfade.** Takes two planned sounds with a file in the same shot or the same scene and overlaps them: the second starts earlier by the chosen time, the first fades out and the second fades in over it. Both must be longer than the fade.

## Where each curve applies

| Curve | Preview of a scene or the film | Voice mix (`mix_into`) | Audio export stems | Audio export mixes |
|---|---|---|---|---|
| Lane (sound lanes) | yes | not used | yes | yes |
| Voices | on the voices only, never the song | yes | yes (dialogue stem) | yes |
| Whole film | yes, on everything | not used | **no** (stems are the mix before the master stage) | yes |
| Cue curve, group | yes | not used | yes | yes |

Order inside the mixer: cue curve and cue gain, group level, lane curve, ducking, the sum, the whole-film curve, then the limiter and loudness target (the raw stem path skips the last three). A film with no plan but a whole-film curve is still processed; a film with neither is left alone.

## Files from before

A `mix.json` or cue file from an earlier version has no curves, groups or markers and sounds exactly as before. Damaged entries (wrong types, unknown lanes) are ignored on read rather than stopping the mix. A refused change (bad lane, level out of range, too many points, a crossfade between cues in different places) changes nothing.

## Tested, and not

Tested with real audio through the real mixer: a ramp changes the level by the expected dB at the expected times; step and eased shapes; the whole-film curve moves the song as well as the sound and a stem stays before it; cue curves count from the cue's start; the voices curve moves the voices and not the song; group level and mute; a crossfade measured by frequency (each sound alone outside the overlap, both at about half in the middle); markers in the cue sheet and read back by the real OpenTimelineIO library; the screen against mocked answers. **Not tested:** how it sounds to a person; a curve edited by dragging (the screen edits numbers); an editor opening the markers; very long films.
