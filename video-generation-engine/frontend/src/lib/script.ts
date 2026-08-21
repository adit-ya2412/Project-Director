import type { BreakSuggestion } from "./types";

/** Insert punctuation at original-script offsets, right-to-left so earlier
 * marks do not shift later ones. Mirrors `apply_break_suggestions` in
 * `backend/app/script/suggestions.py`. */
export function applyBreakSuggestions(
  script: string,
  suggestions: Pick<BreakSuggestion, "offset" | "mark">[],
): string {
  const sorted = [...suggestions].sort((a, b) => b.offset - a.offset);
  let out = script;
  for (const item of sorted) {
    if (item.offset < 0 || item.offset > out.length) continue;
    out = out.slice(0, item.offset) + item.mark + out.slice(item.offset);
  }
  return out;
}

export function scriptCheckKey(script: string, style: string): string {
  return `${style}\n${script}`;
}
