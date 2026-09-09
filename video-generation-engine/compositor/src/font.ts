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
 * NOTE: only a Regular weight is vendored. Asking for 700/800 makes
 * Chromium synthesise bold, which smears Devanagari matras. The stamp
 * therefore uses 400 and gets its impact from size, not weight. If a
 * heavier stamp is wanted, vendor NotoSansDevanagari-Bold.ttf.
 */
export const DEVANAGARI = "NotoSansDevanagariBundled";

const handle = delayRender("loading vendored Noto Sans Devanagari");

const face = new FontFace(
  DEVANAGARI,
  `url(${staticFile("NotoSansDevanagari-Regular.ttf")}) format("truetype")`
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
