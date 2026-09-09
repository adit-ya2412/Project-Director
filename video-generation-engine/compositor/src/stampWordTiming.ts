/**
 * When each WORD of a multi-word stamp drops in — scheduled against the
 * window the renderer actually resolved, not a fixed table.
 *
 * Spike rhythm (`EmphasisOverlay.tsx`, EVERY / 3rd / SUV): 0 / +4 / +14
 * frames. K14.5 shipped that as `WORD_DELAYS_FRAMES` with a 4th word at
 * +24 and +10 per word after it, fixed regardless of how long the stamp
 * is actually on screen.
 *
 * REVIEW FINDING 3 (2026-09-10): the stamp's hold is `STAMP_HOLD_S`
 * 0.86s in `backend/app/renderer/compositor.py` — about 26 frames at
 * 30fps, and `collect_emphasis_overlay_cues` clamps it SHORTER when the
 * cue sits near the end of its shot or the end of the film. Against a
 * fixed table a 4th word appeared ~1.8 frames before the exit and a 5th
 * or 6th (frames 34, 44) never rendered at all. The emphasis prompt asks
 * for a 2-4 word phrase but nothing enforces it, so a longer stamp lost
 * its tail silently — no error, no dropped cue, just words that are
 * never seen.
 *
 * The fix keeps the nominal table whenever it FITS and compresses it
 * proportionally when it does not, so:
 *   - a 1-3 word stamp at the pinned hold is untouched (0 / 4 / 14 —
 *     the spike rhythm this device reproduces survives exactly),
 *   - every word of a longer stamp, and of a stamp whose hold was
 *     clamped short, is scheduled inside the window with room to
 *     finish its entry.
 * It was preferred over clamping the authored word count (which
 * silently truncates copy the writer chose) and over extending
 * `STAMP_HOLD_S` (which is spike-pinned, is hashed into the render
 * fingerprint and the overlay cache key, and would make stamps linger
 * against the retention rule that exits are snaps).
 *
 * Per-GRAPHEME stagger inside one word (`gi * 3` in `Stamp.tsx`) is
 * unchanged and is not budgeted here: it is the pre-K14 single-word
 * look, and a long single word could always outrun its own hold.
 */

export const WORD_DELAYS_FRAMES = [0, 4, 14, 24] as const;

// Words past the table extend by the same step as 4 -> 14.
export const WORD_DELAY_STEP_FRAMES = 10;

// The exit snap in `Stamp.tsx`: opacity 1 -> 0 over the last 3 frames.
export const EXIT_FRAMES = 3;

// Frames a word needs after its onset to reach full opacity (the
// grapheme spring crosses cs 0.35 in about this many frames). A word
// scheduled later than this before the exit is a word nobody reads.
export const MIN_WORD_ENTRY_FRAMES = 4;

export const nominalWordDelayFrames = (index: number): number => {
  if (index < WORD_DELAYS_FRAMES.length) return WORD_DELAYS_FRAMES[index];
  const last = WORD_DELAYS_FRAMES[WORD_DELAYS_FRAMES.length - 1];
  return last + (index - (WORD_DELAYS_FRAMES.length - 1)) * WORD_DELAY_STEP_FRAMES;
};

/**
 * Onset delay per word, in frames, for `wordCount` words held for
 * `windowFrames` (`endFrame - startFrame`). Never returns a delay that
 * leaves a word less than `MIN_WORD_ENTRY_FRAMES` before the exit snap.
 */
export const wordDelaySchedule = (wordCount: number, windowFrames: number): number[] => {
  const n = Math.max(0, Math.floor(wordCount));
  if (n <= 1) return n === 1 ? [0] : [];

  const nominal: number[] = [];
  for (let i = 0; i < n; i += 1) nominal.push(nominalWordDelayFrames(i));

  const budget = Math.max(
    0,
    Math.floor(windowFrames) - EXIT_FRAMES - MIN_WORD_ENTRY_FRAMES,
  );
  const last = nominal[n - 1];
  if (last <= budget) return nominal;

  // Proportional compression: the relative rhythm survives, the last
  // word lands on the budget, and ordering stays monotone.
  const scale = last > 0 ? budget / last : 0;
  return nominal.map((delay) => Math.min(budget, Math.round(delay * scale)));
};
