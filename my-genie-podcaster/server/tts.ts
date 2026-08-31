/**
 * Server-side Kokoro-82M text-to-speech.
 *
 * The model runs in-memory inside the Databricks App (onnxruntime, CPU) — loaded
 * once and reused across requests. Given text, it returns a WAV buffer. Voices
 * are bundled with kokoro-js (no network needed); the model weights are fetched
 * once from the Hugging Face Hub into a local cache dir (`.hf-cache`), so run
 * `npm run setup:model` before deploying to a network-restricted workspace.
 *
 * Synthesized audio is persisted durably in a UC Volume by callers (see
 * audio-store.ts); this module only turns text into WAV bytes.
 */
import path from 'node:path';
import { promises as fs } from 'node:fs';
import { KokoroTTS, TextSplitterStream } from 'kokoro-js';
import { env, RawAudio } from '@huggingface/transformers';
import { getExecutionContext } from '@databricks/appkit';
import { cleanForSpeech, concatFloat32Arrays } from './audio-util';

const MODEL_ID = 'onnx-community/Kokoro-82M-v1.0-ONNX';
export const DEFAULT_VOICE = 'af_heart';

/** Model files needed for the q8 build, relative to the model dir. */
const MODEL_FILES = [
  'config.json',
  'tokenizer.json',
  'tokenizer_config.json',
  'onnx/model_quantized.onnx',
];

/** kokoro-js types voices as a literal union; we carry them as strings. */
type KokoroVoice = NonNullable<Parameters<KokoroTTS['generate']>[1]>['voice'];

// Persist downloaded weights so restarts don't re-download.
env.cacheDir = process.env.KOKORO_CACHE_DIR
  ? path.resolve(process.env.KOKORO_CACHE_DIR)
  : path.resolve(process.cwd(), '.hf-cache');

let ttsPromise: Promise<KokoroTTS> | null = null;

/**
 * Cap on model load. Weights ship in `.hf-cache` so loading is local and fast;
 * if they're ever missing, `from_pretrained` would try to download from Hugging
 * Face with no timeout and hang forever — wedging every synthesis behind it (and
 * so any podcast's audio generation). Failing fast instead lets callers surface
 * an audio error and move on.
 */
const MODEL_LOAD_TIMEOUT_MS = 120_000;

/** Reject if `p` doesn't settle within `ms`. */
function withTimeout<T>(p: Promise<T>, ms: number, label: string): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    const timer = setTimeout(
      () => reject(new Error(`${label} timed out after ${ms / 1000}s`)),
      ms,
    );
    p.then(
      (v) => {
        clearTimeout(timer);
        resolve(v);
      },
      (err: unknown) => {
        clearTimeout(timer);
        reject(err instanceof Error ? err : new Error(String(err)));
      },
    );
  });
}

/** UC Volume directory holding the model files, or null (local dev / no Volume). */
function modelVolumeDir(): string | null {
  const base = process.env.DATABRICKS_VOLUME_AUDIO?.trim().replace(/\/+$/, '');
  return base ? `${base}/_models/${MODEL_ID}` : null;
}

/**
 * Make the model weights available on local disk before loading. The 88MB file
 * exceeds the workspace-file limit so it can't ship with the app; instead it
 * lives in the UC Volume and we fetch any missing files to the transformers
 * cache dir here. This avoids a runtime Hugging Face download, which on
 * network-restricted app compute hangs with no timeout. No-op in local dev
 * (no Volume configured) — there the existing `.hf-cache` or HF is used.
 */
async function ensureModel(): Promise<void> {
  const volDir = modelVolumeDir();
  if (!volDir) return;
  const localRoot = path.join(env.cacheDir as string, MODEL_ID);
  const files = getExecutionContext().client.files;
  for (const rel of MODEL_FILES) {
    const localPath = path.join(localRoot, ...rel.split('/'));
    try {
      await fs.access(localPath);
      continue; // already present
    } catch {
      // missing — fetch it from the Volume
    }
    const res = await files.download({ file_path: `${volDir}/${rel}` });
    if (!res.contents) throw new Error(`Kokoro model file missing in Volume: ${rel}`);
    const bytes = Buffer.from(await new Response(res.contents).arrayBuffer());
    await fs.mkdir(path.dirname(localPath), { recursive: true });
    await fs.writeFile(localPath, bytes);
    console.log(`[tts] fetched model file from Volume: ${rel} (${bytes.length} bytes)`);
  }
}

/** Load (once) and cache the Kokoro model instance. */
export function loadTTS(): Promise<KokoroTTS> {
  if (!ttsPromise) {
    ttsPromise = withTimeout(
      ensureModel().then(() =>
        KokoroTTS.from_pretrained(MODEL_ID, {
          dtype: 'q8', // small + CPU-friendly
          device: 'cpu',
        }),
      ),
      MODEL_LOAD_TIMEOUT_MS,
      'Kokoro model load',
    ).catch((err: unknown) => {
      ttsPromise = null; // allow retry after a failure/timeout
      throw err;
    });
  }
  return ttsPromise;
}

/**
 * Kick off model loading in the background so the first synthesis isn't cold.
 * Safe to call at startup; failures are logged and retried on first real use.
 */
export function warmUp(): void {
  loadTTS().catch((err: unknown) => {
    console.error('[tts] warm-up failed (will retry on first use):', err);
  });
}

// Serialize synthesis: a single ONNX session should not run concurrently.
let queue: Promise<unknown> = Promise.resolve();
function runExclusive<T>(fn: () => Promise<T>): Promise<T> {
  const next = queue.then(fn, fn);
  // Keep the chain alive regardless of individual outcomes.
  queue = next.then(
    () => undefined,
    () => undefined,
  );
  return next;
}

/** Upper bound on a single synthesis so a stall can never wedge generation. */
const SYNTH_TIMEOUT_MS = 240_000;

/**
 * Synthesize `text` in `voice` to a WAV buffer.
 *
 * A single `generate()` call caps input at ~510 phoneme tokens and silently
 * truncates the rest — enough to cut off a multi-sentence summary. So we split
 * into sentences and synthesize each within that limit, then concatenate the
 * per-sentence PCM into one WAV.
 *
 * IMPORTANT: we drive `stream()` with an explicitly-closed `TextSplitterStream`.
 * Passing a raw string to `stream()` in kokoro-js 1.2.1 creates an internal
 * splitter it never closes, so its async iterator blocks forever after the last
 * sentence — hanging synthesis (and any podcast's audio generation) indefinitely.
 */
export async function synthesize(text: string, voice: string): Promise<Buffer> {
  return runExclusive(() =>
    withTimeout(
      (async () => {
        const tts = await loadTTS();
        // Strip markdown/decoration so it isn't read aloud (e.g. "**", "_", "-").
        const spoken = cleanForSpeech(text);
        const splitter = new TextSplitterStream();
        splitter.push(spoken);
        splitter.close(); // terminate the stream so the iterator ends

        const chunks: Float32Array[] = [];
        let samplingRate = 0;
        for await (const { audio } of tts.stream(splitter, { voice: voice as KokoroVoice })) {
          chunks.push(audio.audio);
          samplingRate = audio.sampling_rate;
        }
        if (chunks.length === 0 || samplingRate === 0) {
          // No sentences emitted (e.g. only punctuation/whitespace) — fall back
          // to a direct generate so we still return valid WAV bytes.
          const audio = await tts.generate(spoken || text, { voice: voice as KokoroVoice });
          return Buffer.from(audio.toWav());
        }
        const merged = new RawAudio(concatFloat32Arrays(chunks), samplingRate);
        return Buffer.from(merged.toWav());
      })(),
      SYNTH_TIMEOUT_MS,
      'Kokoro synthesis',
    ),
  );
}
