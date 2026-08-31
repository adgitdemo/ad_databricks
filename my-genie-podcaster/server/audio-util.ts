/**
 * Small, dependency-free audio helpers (kept separate from tts.ts so the pure
 * logic is unit-testable without loading the Kokoro model / onnxruntime).
 */

/**
 * Strip markdown / decorative punctuation that a TTS engine would otherwise try
 * to vocalize or stumble over — asterisks, underscores, backticks, heading and
 * blockquote marks, table pipes — and turn bullets and dash separators into
 * natural pauses. Real intra-word hyphens (e.g. "year-over-year") are kept, so
 * pronunciation of hyphenated words is unaffected.
 */
export function cleanForSpeech(text: string): string {
  return text
    .replace(/[*_`#>~|]/g, ' ') // emphasis / code / heading / quote / table chars
    .replace(/^\s*[-–—]\s+/gm, '') // leading list bullets ("- item")
    .replace(/\s[-–—]+\s/g, ', ') // a dash used as a separator → short pause
    .replace(/-{2,}/g, ' ') // stray runs of hyphens
    .replace(/[ \t]{2,}/g, ' ') // collapse repeated spaces
    .replace(/ +([,.!?;:])/g, '$1') // drop space before punctuation
    .replace(/\n{2,}/g, '\n') // collapse blank lines
    .trim();
}

/** Concatenate PCM sample chunks into a single contiguous Float32Array. */
export function concatFloat32Arrays(chunks: Float32Array[]): Float32Array {
  let total = 0;
  for (const c of chunks) total += c.length;
  const out = new Float32Array(total);
  let offset = 0;
  for (const c of chunks) {
    out.set(c, offset);
    offset += c.length;
  }
  return out;
}
