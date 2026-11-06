# Music director: motifs, spotting, records

Sound & Music > Scenes > **Music director**. Free and local: nothing is generated, sent or charged here. Code: `analysis/filmcrafter_engine/musicdirector.py` (record in `audio/music.json`), screen `src/MusicDirector.tsx`, shell command `film_music`.

## What it does

- **Motifs.** A short musical idea the film comes back to, tied to a character, a place or a theme: name, who or where, mood, tempo, key, instruments, and a line in words ("four rising notes"). Up to 40. Nothing is composed: a motif goes into the words used to ask for music and into notes beside each cue.
- **Spotting.** For each scene you decide **Music (score)**, **Music in the world** (a radio, a band) or **Silence, on purpose**. A scored spot says from which shot to which shot, the energy at the start and end (0 to 5), the mood, tempo, instruments, where it enters and leaves, its motifs, a level and fades, and which library music covers it. Up to 6 spots per scene.
- **Suggest from the scene (free).** Reads only the words of the scene's written action with plain rules (no AI, nothing saved). It names the words it acted on (for example "chases", "cries"), the mood they point to, an energy, a starting shot, and the motifs of the people and place in the scene. When no word calls for music it proposes **silence** and says so. It judges words, not pictures or sound; you decide.
- **Words to ask for the music.** Builds one text (instrumental, mood, tempo, instruments, energy arc, motif descriptions, where it enters) and a length from the shots it covers. Nothing is sent: paste it into the music generator in Sound & Music, where the price is shown first.
- **Find in library.** Music already in your library that could cover the spot (reuse before generating). Sound effects are never offered; rejected music is never offered.
- **Records.** For each piece of music in the plan: who approved or revoked it, for which scenes, a licence note, and when, with the history kept (last 30 decisions). This records what *you* say. It does not check a licence and does not change what the library says about commercial use.
- **Put into the film.** Turns each approved, scored spot that has music into an ordinary music cue (anchored at the spot's first shot, as long as the spot, with its level and fades, ducking automatic), so the mixer, ducking, loudness, automation and the audio export all apply. Doing it again updates the same cue. Spots that are silence or music-in-the-world make no cue; spots without music are listed as waiting; music whose licence says commercial use is **not allowed** is never put in.
- **Report.** Scenes with no decision, motifs never used or used in only one scene, big jumps of energy between scored scenes, the share of the film that has music, and music in the plan with no recorded decision or with an unknown or disallowed commercial licence.

## Nothing is deleted

A removed motif or spot moves to a `removed` list in `audio/music.json` (last 200 kept). Removing a spot leaves the cue it made in the sound plan, where it can be removed or restored like any cue. A file of the wrong shape is refused and left exactly as it was; entries of the wrong kind inside a good file are ignored.

## Tested, and not

Tested with real films, real audio files, the real cue list and the real mixer: motifs and spots checked and refused when wrong; the suggestion on three scenes (a chase, a quiet scene of grief, a plain office scene that gets silence); the words built from the spot and its motifs; the library search; records and their history; a spot turned into a cue and *heard* in the real mix (music during the scene, none after); licence "no" blocked; the report; the screen against mocked answers and against the real engine's answers. **Not tested:** whether the words produce good music from any provider (no music was generated for this slice); how any of it sounds; whether the suggested moods fit a particular film. The word lists are small and English-only; a scene written in another language gets silence proposed.
