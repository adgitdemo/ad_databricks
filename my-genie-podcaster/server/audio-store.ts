/**
 * Durable audio storage in a Unity Catalog Volume.
 *
 * Narration WAVs are content-addressed by (voice, summary text) inside a
 * per-podcast folder, so re-synthesizing the same text/voice reuses the same
 * object and an edited summary produces a new one.
 *
 * We talk to the Volume through the SDK Files API using the app's service
 * principal — deliberately NOT the AppKit `files()` plugin, which would mount
 * public `/api/files/*` routes over the whole volume. Keeping audio access
 * behind our own owner-checked route preserves per-user isolation. Bytes
 * survive app redeploys (unlike the old local disk cache).
 *
 * The Volume base path comes from `DATABRICKS_VOLUME_AUDIO`
 * (e.g. `/Volumes/<catalog>/<schema>/<volume>`). When it is unset (local dev
 * without a Volume) storage is a no-op and audio is synthesized on demand.
 */
import { createHash } from 'node:crypto';
import { getExecutionContext } from '@databricks/appkit';

function baseDir(): string | null {
  const raw = process.env.DATABRICKS_VOLUME_AUDIO?.trim();
  if (!raw) return null;
  return raw.replace(/\/+$/, ''); // strip trailing slashes
}

/** True when a UC Volume is configured for durable audio storage. */
export function audioConfigured(): boolean {
  return baseDir() !== null;
}

/** Service-principal Files API client. */
function files() {
  return getExecutionContext().client.files;
}

/**
 * Absolute Volume path for a segment's audio in a given voice, or `null` when
 * no Volume is configured.
 */
export function audioPath(
  podcastId: string,
  idx: number,
  voice: string,
  summary: string,
): string | null {
  const base = baseDir();
  if (!base) return null;
  const key = createHash('sha1').update(`${voice}\n${summary}`).digest('hex').slice(0, 16);
  return `${base}/${podcastId}/${idx}-${key}.wav`;
}

/**
 * Store WAV bytes at `fullPath` (creates parent dirs implicitly).
 *
 * NOTE: the typed SDK `files.upload` is broken in this version — its
 * implementation sends an empty request body, producing 0-byte files. We issue
 * the raw authenticated PUT ourselves so the actual bytes are written.
 */
export async function putAudio(fullPath: string, wav: Buffer): Promise<void> {
  const { config } = getExecutionContext().client;
  const headers = new Headers({ 'Content-Type': 'application/octet-stream' });
  await config.authenticate(headers);
  const url = new URL(`/api/2.0/fs/files${fullPath}`, await config.getHost());
  url.searchParams.set('overwrite', 'true');
  const resp = await fetch(url, { method: 'PUT', headers, body: new Uint8Array(wav) });
  if (!resp.ok) {
    const detail = await resp.text().catch(() => '');
    throw new Error(`Volume upload failed (${resp.status}): ${detail.slice(0, 200)}`);
  }
}

/** Read WAV bytes at `fullPath`, or `null` if missing/empty/unreadable. */
export async function getAudio(fullPath: string): Promise<Buffer | null> {
  try {
    const res = await files().download({ file_path: fullPath });
    if (!res.contents) return null;
    const bytes = await new Response(res.contents).arrayBuffer();
    // Treat a 0-byte object as missing so callers fall back to (re)synthesis —
    // this also self-heals any empty files left by the old broken upload path.
    if (bytes.byteLength === 0) return null;
    return Buffer.from(bytes);
  } catch {
    return null;
  }
}

/** Best-effort delete of every audio object for a podcast. */
export async function deletePodcastAudio(podcastId: string): Promise<void> {
  const base = baseDir();
  if (!base) return;
  const dir = `${base}/${podcastId}`;
  try {
    for await (const entry of files().listDirectoryContents({ directory_path: dir })) {
      if (entry.path) await files().delete({ file_path: entry.path }).catch(() => {});
    }
    await files().deleteDirectory({ directory_path: dir }).catch(() => {});
  } catch {
    // Folder may not exist (no audio generated yet) — nothing to clean up.
  }
}
