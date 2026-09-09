import { continueRender, delayRender, staticFile } from "remotion";

/**
 * Load the SAME font file the captions use — backend/vendor/fonts/
 * NotoSansDevanagari-Regular.ttf, staged into public/.
 *
 * Not a system font and not Google Fonts, deliberately. `captions.py`
 * passes libass an explicit `fontsdir=` with a comment about avoiding
 * "host-fontconfig non-determinism"; only Nirmala.ttc is installed on
 * this machine, so a CSS request for "Noto Sans Devanagari" would
 * silently fall back to a different typeface than the captions use.
 * Bundling keeps the stamp and the captions in one voice AND keeps the
 * render reproducible, which is the same property I5 protects.
 *
 * NOTE (corrected 2026-09-09): an earlier version of this comment said
 * only a Regular weight was vendored and a Bold had to be downloaded.
 * That was wrong — see the FontFace call below. The file is a variable
 * font with the whole 100-900 range in it; real weights were always one
 * descriptor away.
 */
export const DEVANAGARI = "NotoSansDevanagariBundled";

const handle = delayRender("loading vendored Noto Sans Devanagari");

// The vendored file is MISNAMED. `NotoSansDevanagari-Regular.ttf` is the
// full VARIABLE font (Noto Sans Devanagari v2.006, Monotype): it carries
// an `fvar` table with a `wght` axis from 100 to 900 and named instances
// all the way to Bold (700) and Black (900). Measured 2026-09-09 with
// fontTools; the filename is the only thing that says "Regular".
//
// A `FontFace` with no weight descriptor defaults to "400", which caps
// the browser at the Regular instance and makes any heavier request
// SYNTHETIC bold — the smearing that ruins Devanagari matras. Declaring
// the real axis range is therefore the whole of K6: nothing to download,
// nothing to vendor, just stop lying to the font matcher.
const face = new FontFace(
  DEVANAGARI,
  `url(${staticFile("NotoSansDevanagari-Regular.ttf")}) format("truetype")`,
  { weight: "100 900" }
);

face
  .load()
  .then((loaded) => {
    document.fonts.add(loaded);
    continueRender(handle);
  })
  .catch((err) => {
    // Never hang the render on a font failure — fail visibly instead.
    console.error("bundled font failed to load", err);
    continueRender(handle);
  });
