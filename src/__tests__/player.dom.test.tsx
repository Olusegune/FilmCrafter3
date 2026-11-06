// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";

vi.mock("@tauri-apps/api/core", () => ({ invoke: vi.fn(), convertFileSrc: (p: string) => p }));

import { needsSeek, PAUSED_TOLERANCE, PLAYING_TOLERANCE, seekForSelection, shotToShow } from "../playerMath";
import { Clip } from "../Studio";

const SHOTS = [{ id: "S01-01", start: 0, end: 4 }, { id: "S01-02", start: 4, end: 9 }, { id: "S02-01", start: 9, end: 12 }];

describe("what the player shows", () => {
  it("shows the shot under the playhead, whatever is selected, so scrubbing changes the picture", () => {
    expect(shotToShow(SHOTS, "S01-01", 5)?.id).toBe("S01-02");
    expect(shotToShow(SHOTS, "S02-01", 1)?.id).toBe("S01-01");
    expect(shotToShow(SHOTS, null, 10)?.id).toBe("S02-01");
    expect(shotToShow(SHOTS, "S01-02", 4)?.id).toBe("S01-02");                       // a cut belongs to the shot that starts there
    expect(shotToShow(SHOTS, "S01-01", 3.999)?.id).toBe("S01-01");
  });

  it("falls back to the selected shot only when the playhead is in no shot", () => {
    expect(shotToShow(SHOTS, "S01-02", 12)?.id).toBe("S01-02");
    expect(shotToShow(SHOTS, "S01-02", 99)?.id).toBe("S01-02");
    expect(shotToShow(SHOTS, null, 99)).toBeNull();
    expect(shotToShow(SHOTS, "nope", 99)).toBeNull();
    expect(shotToShow([], "S01-01", 0)).toBeNull();
  });

  it("puts the playhead on a shot selected somewhere else, and leaves it alone when it is already inside", () => {
    expect(seekForSelection(SHOTS, "S02-01", 1)).toBe(9);
    expect(seekForSelection(SHOTS, "S01-02", 6)).toBeNull();
    expect(seekForSelection(SHOTS, "S01-02", 9)).toBe(4);
    expect(seekForSelection(SHOTS, "gone", 1)).toBeNull();
  });
});

describe("when a video must be moved", () => {
  it("follows every scrub step while paused, but tolerates small drift while playing", () => {
    expect(needsSeek(2, 2.05, false)).toBe(true);
    expect(needsSeek(2, 2 + PAUSED_TOLERANCE / 2, false)).toBe(false);
    expect(needsSeek(2, 2.05, true)).toBe(false);
    expect(needsSeek(2, 2 + PLAYING_TOLERANCE + 0.01, true)).toBe(true);
    expect(needsSeek(5, 1, true)).toBe(true);
    expect(needsSeek(5, 1, false)).toBe(true);
  });

  it("never moves a video to a time that is not a number, and clamps below zero", () => {
    expect(needsSeek(1, NaN, false)).toBe(false);
    expect(needsSeek(NaN, 1, false)).toBe(false);
    expect(needsSeek(0.5, -3, false)).toBe(true);
    expect(needsSeek(0, -3, false)).toBe(false);
  });
});

describe("the clip in the player", () => {
  let pos = 0;
  let paused = true;
  const sets: number[] = [];
  const play = vi.fn(() => { paused = false; return Promise.resolve(); });
  const pause = vi.fn(() => { paused = true; });
  beforeEach(() => {
    pos = 0; paused = true; sets.length = 0; play.mockClear(); pause.mockClear();
    Object.defineProperty(HTMLMediaElement.prototype, "currentTime", { configurable: true, get: () => pos, set: (v: number) => { pos = v; sets.push(v); } });
    Object.defineProperty(HTMLMediaElement.prototype, "paused", { configurable: true, get: () => paused });
    HTMLMediaElement.prototype.play = play as never;
    HTMLMediaElement.prototype.pause = pause as never;
  });
  afterEach(() => cleanup());

  it("shows the frame at the playhead for every small scrub step while paused", () => {
    const { rerender } = render(<Clip src="a.mp4" offset={1} playing={false} />);
    for (const t of [1.04, 1.08, 1.12, 1.16, 1.2]) rerender(<Clip src="a.mp4" offset={t} playing={false} />);
    expect(sets).toEqual([1, 1.04, 1.08, 1.12, 1.16, 1.2]);
    rerender(<Clip src="a.mp4" offset={0.4} playing={false} />);                        // and backwards
    expect(pos).toBe(0.4);
    expect(play).not.toHaveBeenCalled();
  });

  it("does not stutter a playing video for small drift, and pulls it back for a jump", () => {
    pos = 3;
    const { rerender } = render(<Clip src="a.mp4" offset={3.02} playing />);
    rerender(<Clip src="a.mp4" offset={3.1} playing />);
    expect(sets).toEqual([]);
    rerender(<Clip src="a.mp4" offset={6} playing />);
    expect(sets).toEqual([6]);
    expect(play).toHaveBeenCalled();
  });

  it("pauses when playback stops", () => {
    paused = false;
    const { rerender } = render(<Clip src="a.mp4" offset={1} playing />);
    rerender(<Clip src="a.mp4" offset={1} playing={false} />);
    expect(pause).toHaveBeenCalled();
  });

  it("goes to the playhead once a newly loaded file knows its length, in case the first request was lost", () => {
    const { container, rerender } = render(<Clip src="a.mp4" offset={2} playing={false} />);
    rerender(<Clip src="b.mp4" offset={2.5} playing={false} />);
    pos = 0;                                                                              // the new file loaded at its start
    sets.length = 0;
    fireEvent.loadedMetadata(container.querySelector("video")!);
    expect(sets).toEqual([2.5]);
  });
});
