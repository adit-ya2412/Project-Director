/**
 * F3: "Errors must be translated... Show a plain sentence, the technical
 * detail behind a disclosure, and the action where one exists — most real
 * failures had one." Backend errors are free-text strings (no error code
 * field anywhere in the schemas), so this is pattern-matching against the
 * real failure shapes recorded in docs/13_Implementation_Guide.md, with a
 * generic fallback for anything unrecognised — never silently swallowed.
 */

export interface TranslatedError {
  headline: string
  action: string | null
  raw: string
}

const PATTERNS: Array<{
  test: RegExp
  translate: (match: RegExpMatchArray, raw: string) => TranslatedError
}> = [
  {
    // "shot sc_03_sh_01's narration_span (0, 2) covers only whitespace -
    // nothing is actually spoken, so it cannot be timed against narration"
    test: /narration_span.*covers only whitespace/i,
    translate: (_m, raw) => ({
      headline:
        "One shot's narration line is blank, so it has nothing to time against the voiceover.",
      action: 'Edit the script so every shot has words to say, then retry this stage.',
      raw,
    }),
  },
  {
    // "...violated constraint 'no Nazi symbols used decoratively': <reason>"
    test: /violated constraint ['"]([^'"]+)['"]/i,
    translate: (m, raw) => ({
      headline: `The automatic image check objected: "${m[1]}" — and every attempt failed the same way.`,
      action: 'Review it at the generated-image gate: replace the image yourself, or edit the prompt and regenerate.',
      raw,
    }),
  },
  {
    test: /verbatim/i,
    translate: (_m, raw) => ({
      headline: 'A planning step produced narration that drifted from the script text.',
      action: 'Retry this stage — this has succeeded on a second attempt before with no changes needed.',
      raw,
    }),
  },
  {
    test: /span.*failure|span.*failed/i,
    translate: (_m, raw) => ({
      headline: 'A planning step could not line up part of the script with the shots.',
      action: 'Retry this stage.',
      raw,
    }),
  },
]

export function translateError(raw: string | null | undefined): TranslatedError | null {
  if (!raw || !raw.trim()) return null
  for (const p of PATTERNS) {
    const m = raw.match(p.test)
    if (m) return p.translate(m, raw)
  }
  // Generic fallback: still a plain-language framing, never the raw
  // exception text as the headline — the raw text is always available via
  // the disclosure this pairs with.
  return {
    headline: 'Something went wrong at this step.',
    action: null,
    raw,
  }
}
