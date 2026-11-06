/** What the player shows and when a video must be moved: kept apart from the screen so it can be tested. */

export type Span = { id: string; start: number; end: number };

/**
 * The shot the picture should show. It is the shot under the playhead, always: scrubbing back and forth must change the picture. A selected shot is shown only when the playhead is in no shot at
 * all (before the first or after the last), so a selection can never hold the picture on one shot while the time moves on.
 */
export function shotToShow<T extends Span>(shots: T[], selectedId: string | null | undefined, time: number): T | null {
  const under = shots.find((s) => time >= s.start && time < s.end);
  if (under) return under;
  return (selectedId ? shots.find((s) => s.id === selectedId) : undefined) ?? null;
}

/** How far a playing video may drift from the clock before it is pulled back (setting it every frame would stutter). */
export const PLAYING_TOLERANCE = 0.15;
/** Paused, the picture must be the frame at the playhead: any difference over about half a frame is a seek. */
export const PAUSED_TOLERANCE = 0.02;

/** True when the video element must be moved to `target` seconds. */
export function needsSeek(current: number, target: number, playing: boolean): boolean {
  if (!Number.isFinite(target) || !Number.isFinite(current)) return false;
  return Math.abs(current - Math.max(0, target)) > (playing ? PLAYING_TOLERANCE : PAUSED_TOLERANCE);
}

/** The shot to move the playhead to when a shot is selected somewhere else, or null when it is already inside that shot. */
export function seekForSelection(shots: Span[], selectedId: string, time: number): number | null {
  const s = shots.find((x) => x.id === selectedId);
  if (!s) return null;
  return time >= s.start && time < s.end ? null : s.start;
}
