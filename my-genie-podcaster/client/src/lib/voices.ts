/** Voice options for the podcast narrator (must exist in Kokoro-82M). */
export const DEFAULT_VOICE = 'af_heart';

export const RECOMMENDED_VOICES: ReadonlyArray<{ id: string; label: string }> = [
  { id: 'af_heart', label: 'Heart — US, female' },
  { id: 'af_bella', label: 'Bella — US, female' },
  { id: 'am_michael', label: 'Michael — US, male' },
  { id: 'am_fenrir', label: 'Fenrir — US, male' },
  { id: 'bf_emma', label: 'Emma — UK, female' },
  { id: 'bm_george', label: 'George — UK, male' },
];
