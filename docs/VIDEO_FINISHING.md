# Video finishing

Free and local (ffmpeg only). Engine: `analysis/filmcrafter_engine/videofinish.py`. Screen: `src/FinishPanel.tsx` inside the Export sheet. Native command: `video_finish`. Nothing is sent anywhere or billed, and the original file is never changed. New files go in `<film>/restore` and `<film>/finish`, with ledgers `restore.json` and `finish.json`. Inputs must be inside the film folder.

## Flicker measurement

Decodes the video at 256x144 (first 30 s of a longer one), and measures how far each frame's brightness sits from the average of its two neighbours, over the whole picture and in a grid of tiles. Slow fades and drifts score near zero; jumps above 14 levels are counted as cuts or flashes on purpose and listed in the note, not scored. The result is a number, a word (Calm, Noticeable, Strong) and a confidence (low under 12 frames).

Checked on synthetic clips with a moving subject: steady, a slow fade and a hard cut all read Calm; random brightness jitter of +-3% reads Noticeable and +-12% reads Strong.

Limits: brightness only (it does not measure fine texture "boiling"); it cannot tell a strobe light in the story from flicker; the thresholds were tuned on synthetic clips, not on a library of real AI-video flicker.

## Calmer copy

ffmpeg `deflicker` (averaging over 7-11 frames) plus a light temporal denoise, re-encoded at CRF 14 with the audio copied. The video is measured again and the gain is reported as numbers; if the copy is not measurably calmer the panel says to keep the original. On the synthetic flicker clip the score fell from 7.25 to 0.38. Real footage may improve less. Deflicker cannot fix a flicker that is a real change in the picture's content.

## Looks and profiles

Looks: none, clean (light denoise + gentle sharpen), film grain (moving fine grain). Profiles: Web (H.264 CRF 20), Master (H.264 CRF 12), ProRes 422 HQ, H.265, Small (720p). All carry the same Rec. 709 colour labels as the film export. A delivery copy is encoded from an existing export (so it is one more generation of compression: keep Master or ProRes as the archive).

## Not built

Frame-by-frame AI video restoration or interpolation, per-shot restoration inside the film, audio restoration, HDR, and any profile that needs a hardware encoder.
