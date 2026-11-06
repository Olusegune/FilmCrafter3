# Virtual production: plan, status and the cutout studio

The brief has three systems: **Virtual Production Studio** (green screen, transparent assets, matting, compositing), **WorldLock** (a persistent spatial scene) and **DirectorCam** (planned cameras and blocking). They are built in thin, tested slices. This page says what is done, what is not, and what each choice rests on.

## Audit of the repository (what was found, 0.47.0)

- Shell: Tauri 2 (Rust `src-tauri/src/lib.rs`, one command per engine area with a fixed action list the security test checks); screens in React and TypeScript; engine in Python (`analysis/filmcrafter_engine`), one JSON line per result. The film folder is the source of truth; records are written with `safeio`.
- Engine packages in the product: **numpy, Pillow, ffmpeg (through imageio-ffmpeg), soundfile**. **Not present:** OpenCV, SciPy, scikit-image, PyTorch, ONNX Runtime, any segmentation or matting model, any 3D library, Blender. A new heavy dependency is never added silently; optional adapters for them are installed on purpose, with size and licence shown.
- Existing, reused or left alone: layers, overlays, blend modes, a simple colour key and masks in `composite.py` (per layer, applied at export), colour studio, lighting, colour match, continuity checks, Production Bible (characters, places), shot list with camera fields, ledger and paid-operation gate. None of it knew about alpha cutouts, a persistent set, or a camera in space.
- The Cinematic Fidelity Engine named in the brief is not a module in this repository (there is a fidelity sheet and quality checks); integration with it is a later slice and will say what it actually connects to.
- No Pulseframe or Greenroom code is touched. The picture algorithms are in `keying.py`, which has no film, file-of-the-film or network dependency, so Pulseframe can reuse it as it stands (copy the file; extraction into a shared package is not attempted yet).

## Slices

| Slice | Contents | State |
|---|---|---|
| 1 (0.47.0) | Cutout studio: plate check, chroma key with despill and decontamination, edge refine, RGBA PNG and mask export, stills compositing with transform, contact shadow, colour match; plate prompt (words only) | **Done, tested on synthetic plates with known answers; not yet tried on a real photograph** |
| 2 | Production Mode selector on shots (Full scene, Green screen, Transparent, Layered); video: frame sequences, temporal alpha, PNG sequences with alpha, transform keyframes, compositing over footage | Not started |
| 3 | WorldLock package (versioned set, stable ids, undo/redo) and 2.5D set builder (layers at depths, parallax, saved cameras) | Not started |
| 4 | Continuity inspector on the set (object and prop state over shots, screen direction) | Not started |
| 5 | True 3D set (glTF import, hierarchy, lights, cameras, render of several views); Blender as an optional backend | Not started |
| 6 | DirectorCam: shot plan from a story beat on a set, blocking, eyeline and screen-direction checks, conditioning assets for providers | Not started |
| 7 | AI-assisted reconstruction from reference images (inventory, draft layout, optional image-to-3D adapters), approval and set locking | Not started |
| 8 | Fidelity integration, performance, recovery and export validation | Not started |

Nothing in slices 2 to 8 exists yet: no placeholder screens were added for them.

## Slice 1: the cutout studio

Rail > More > **Cutouts** (any screen of a film; it opens in the timeline Studio). Three steps in one dialog.

1. **Pictures.** Bring in a *plate* (a subject in front of a green or blue screen), a *background* or a *foreground*. The file is copied into `vp/sources/`; the original is never touched; the same picture twice is kept once. **Words for a clean plate** writes the text to ask an image or video maker for an evenly lit screen with no green on the subject. It sends nothing.
2. **Cut out.** **Check the screen** reads the border of the plate for the screen colour and how even it is, and says in numbers whether a key is likely to work. **Cut out** keys the plate. Settings: screen colour, similarity (how far from the screen colour still counts as screen), edge softness (0 = worked out from the picture), shrink and grow the edge, feather, remove screen colour from the subject, fill holes, clean the colour of the edge. Each cutout keeps the settings that made it and what the key found, as a straight-alpha RGBA PNG (`vp/cutouts/<id>/cutout.png`) and its mask. **Export PNG** copies it to `exports/virtual-production/` and reads the file back to confirm it really has transparent pixels.
3. **Compose.** Pick a background (or a plain colour) and a size, add cutouts bottom to top, each with its place (the *feet* are what is placed, not the edge of the picture), size, turn, flip, contact shadow and colour match. **Save and render** writes a PNG under `vp/renders/`.

### How it works, and what it does not do

- The key measures each pixel's colour distance from the screen colour in the chroma plane (Cb, Cr, BT.709) only, so a darker or lighter patch of the same screen still counts as screen. Between "screen" and "subject" the transparency is a straight ramp whose end is taken from the plate (the weaker-coloured fifth of the subject decides), which is what keeps hair and soft edges.
- Along the edge a pixel is a mix of subject and screen. The screen's share is removed from the colour in linear light (decontamination), then the screen's channel is limited (despill), so no green or blue fringe is left.
- Compositing is in linear light with premultiplied alpha, so edges get no dark or light halo. A contact shadow is the subject's feet outline, flattened and blurred: it grounds the subject; it is not a render of the real light. Colour match pulls the subject half way toward the picture's mean and spread; it is a pull, not a relight.
- It **does not know what a person is.** There is no segmentation or matting model, so it cannot cut a subject out of a picture with no screen, it cannot track a subject through video, and green that is on the subject (a green jacket on a green screen) is keyed out with the screen. A plate whose screen is uneven or noisy gives a poor key; `Check the screen` is there to say so before time is spent. Models for those cases (a segmentation model, a video matting model) would be optional adapters installed on purpose; none is included or downloaded.
- Hair is kept as far as the plate allows: very fine strands against a noisy screen can be lost, and no hair-specific refinement exists beyond the soft ramp and decontamination.
- Transparent H.264 MP4 does not exist and is not offered. Stills only so far: no video, no PNG sequences, no keyframes.

## Tested, and not

Tested on synthetic plates made for the tests, whose true transparency and true subject colour are known (a subject with soft hair-like edges and green spill mixed over a noisy, uneven green screen in linear light): the key's transparency against the truth on solid parts, background and soft edges; strands found; brightness changes in the screen not leaking into the subject; green fringe reduced by more than 90%; edge colour recovered much closer to the true colour; the composite over white and over black against the true result, and better than naive compositing; placing, scaling, rotating, flipping; the feet anchor; opacity and layer order; the shadow only at the feet; colour match; RGBA PNG round trip; the whole film flow (import, check, key, export, compose, render) on real files; refusals; nothing deleted; paths that lead outside the film never followed. The screens are tested against mocked answers and against the real engine's answers.

**Not tested:** a real photograph or real generated plate; hair on a real subject; video; how the shadow and colour match look next to real footage; large plates for speed (a 40-megapixel limit protects memory but timing was not measured).
