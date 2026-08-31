import { describe, it, expect } from 'vitest';
import { cleanForSpeech, concatFloat32Arrays } from './audio-util';

describe('cleanForSpeech', () => {
  it('removes markdown emphasis, code, and heading marks', () => {
    expect(cleanForSpeech('**Sales** are _up_ `sharply` # today')).toBe(
      'Sales are up sharply today',
    );
  });

  it('drops leading list bullets', () => {
    expect(cleanForSpeech('- first point\n- second point')).toBe('first point\nsecond point');
  });

  it('turns dash separators into a pause but keeps intra-word hyphens', () => {
    expect(cleanForSpeech('Revenue rose — a lot — this year')).toBe(
      'Revenue rose, a lot, this year',
    );
    expect(cleanForSpeech('year-over-year growth')).toBe('year-over-year growth');
  });

  it('treats a spaced dash run as a pause and collapses extra spaces, and trims', () => {
    expect(cleanForSpeech('  up   --  strongly  ')).toBe('up, strongly');
  });

  it('collapses a stray in-word hyphen run to a space', () => {
    expect(cleanForSpeech('foo----bar')).toBe('foo bar');
  });

  it('does not leave a space before punctuation', () => {
    expect(cleanForSpeech('Great *news* , indeed')).toBe('Great news, indeed');
  });
});

describe('concatFloat32Arrays', () => {
  it('returns an empty array for no chunks', () => {
    const out = concatFloat32Arrays([]);
    expect(out).toBeInstanceOf(Float32Array);
    expect(out.length).toBe(0);
  });

  it('preserves a single chunk', () => {
    const a = new Float32Array([0.1, -0.2, 0.3]);
    expect(Array.from(concatFloat32Arrays([a]))).toEqual(Array.from(a));
  });

  it('concatenates multiple chunks in order', () => {
    const a = new Float32Array([1, 2]);
    const b = new Float32Array([3]);
    const c = new Float32Array([4, 5, 6]);
    const out = concatFloat32Arrays([a, b, c]);
    expect(out.length).toBe(6);
    expect(Array.from(out)).toEqual([1, 2, 3, 4, 5, 6]);
  });

  it('skips empty chunks without affecting the result', () => {
    const out = concatFloat32Arrays([new Float32Array([1]), new Float32Array(0), new Float32Array([2])]);
    expect(Array.from(out)).toEqual([1, 2]);
  });
});
