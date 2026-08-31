#!/usr/bin/env node
/**
 * Pre-downloads the Kokoro-82M weights into the local cache (`.hf-cache`) so the
 * Databricks App can synthesize speech without runtime egress to Hugging Face.
 *
 *   npm run setup:model
 *
 * Run this once before deploying to a network-restricted workspace; the
 * `.hf-cache` directory is then uploaded with the app bundle. Voices ship inside
 * the kokoro-js package, so no separate voice download is needed.
 */
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { KokoroTTS } from 'kokoro-js';
import { env } from '@huggingface/transformers';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
env.cacheDir = process.env.KOKORO_CACHE_DIR
  ? path.resolve(process.env.KOKORO_CACHE_DIR)
  : path.join(ROOT, '.hf-cache');

console.log(`Downloading Kokoro-82M into ${path.relative(ROOT, env.cacheDir)} …`);
const tts = await KokoroTTS.from_pretrained('onnx-community/Kokoro-82M-v1.0-ONNX', {
  dtype: 'q8',
  device: 'cpu',
});
// Warm a short synthesis so the full path (weights + voice) is exercised.
await tts.generate('Kokoro is ready.', { voice: 'af_heart' });
console.log('Done. Kokoro model cached and ready for the app.');
