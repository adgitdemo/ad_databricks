/**
 * REST API for the podcast platform, mounted on the AppKit Express app.
 */
import express, { type Application, type Request, type Response } from 'express';
import type { CreatePodcastRequest, UserPreferences } from '../shared/types';
import { createPodcast } from './podcast-service';
import { listSpaces } from './genie';
import {
  getUserPreferences,
  listPodcasts,
  readPodcast,
  removePodcast,
  setUserPreferences,
} from './storage';
import { DEFAULT_VOICE, synthesize } from './tts';
import { audioPath, deletePodcastAudio, getAudio, putAudio } from './audio-store';
import { requestUser } from './user';

/** Wrap an async handler so rejections become 500s instead of crashing. */
function asyncHandler(fn: (req: Request, res: Response) => Promise<void>) {
  return (req: Request, res: Response) => {
    fn(req, res).catch((err: unknown) => {
      const message = err instanceof Error ? err.message : String(err);
      // Log the real error server-side; return a generic message so internal
      // detail (SQL, stack, host paths) never leaks to the client.
      console.error(`[api] ${req.method} ${req.path} failed:`, message);
      if (!res.headersSent) res.status(500).json({ error: 'Internal server error' });
    });
  };
}

/**
 * Send a WAV buffer, honoring a `Range` request so the browser can seek within
 * a segment. Falls back to a full 200 response when no (valid) range is given.
 */
function sendWav(req: Request, res: Response, wav: Buffer): void {
  res.setHeader('Content-Type', 'audio/wav');
  res.setHeader('Accept-Ranges', 'bytes');
  // Audio is owner-checked and content-addressed by (voice, summary), and a
  // segment's summary never changes once done — so it's safe to let the user's
  // own browser cache it. This makes replays and prefetches start instantly.
  // `private` keeps it out of shared/proxy caches (no cross-user leakage).
  res.setHeader('Cache-Control', 'private, max-age=86400');

  const range = req.headers.range;
  const match = /^bytes=(\d*)-(\d*)$/.exec(range ?? '');
  if (match && (match[1] || match[2])) {
    const last = wav.length - 1;
    const start = match[1] ? Number(match[1]) : 0;
    const end = match[2] ? Math.min(Number(match[2]), last) : last;
    if (start > end || start > last) {
      res.setHeader('Content-Range', `bytes */${wav.length}`);
      res.status(416).end(); // Range Not Satisfiable
      return;
    }
    const chunk = wav.subarray(start, end + 1);
    res.status(206);
    res.setHeader('Content-Range', `bytes ${start}-${end}/${wav.length}`);
    res.setHeader('Content-Length', chunk.length);
    res.end(chunk);
    return;
  }

  res.setHeader('Content-Length', wav.length);
  res.end(wav);
}

export function registerRoutes(app: Application): void {
  const api = express.Router();
  api.use(express.json({ limit: '1mb' }));

  // List available Genie spaces the signed-in user can access (OBO).
  api.get(
    '/genie/spaces',
    asyncHandler(async (req, res) => {
      res.json(await listSpaces(requestUser(req).client));
    }),
  );

  // List the signed-in user's own podcasts.
  api.get(
    '/podcasts',
    asyncHandler(async (req, res) => {
      res.json(await listPodcasts(requestUser(req).id));
    }),
  );

  // Create a podcast (runs Genie as the signed-in user) and start generation.
  api.post(
    '/podcasts',
    asyncHandler(async (req, res) => {
      const body = req.body as CreatePodcastRequest;
      try {
        const podcast = await createPodcast(requestUser(req), body);
        res.status(201).json(podcast);
      } catch (err) {
        res.status(400).json({ error: err instanceof Error ? err.message : String(err) });
      }
    }),
  );

  // Fetch one of the user's podcasts (client polls this while "generating").
  api.get(
    '/podcasts/:id',
    asyncHandler(async (req, res) => {
      const podcast = await readPodcast(String(req.params.id));
      // 404 (not 403) when it isn't the caller's — don't reveal existence.
      if (!podcast || podcast.ownerId !== requestUser(req).id) {
        res.status(404).json({ error: 'Podcast not found' });
        return;
      }
      res.json(podcast);
    }),
  );

  // Stream a segment's narration WAV. Served from the UC Volume when already
  // synthesized (instant); otherwise synthesized on demand, stored, then sent.
  api.get(
    '/podcasts/:id/audio/:segment',
    asyncHandler(async (req, res) => {
      const podcast = await readPodcast(String(req.params.id));
      const segIndex = Number(req.params.segment);
      const segment = podcast?.segments[segIndex];
      if (
        !podcast ||
        podcast.ownerId !== requestUser(req).id ||
        !segment ||
        segment.status !== 'done' ||
        !segment.summary.trim()
      ) {
        res.status(404).json({ error: 'No audio available for this segment' });
        return;
      }
      const voice = typeof req.query.voice === 'string' ? req.query.voice : DEFAULT_VOICE;
      const path = audioPath(podcast.id, segIndex, voice, segment.summary);
      try {
        let wav = path ? await getAudio(path) : null;
        if (!wav) {
          wav = await synthesize(segment.summary, voice);
          // Persist for next time (best-effort — don't fail playback on write error).
          if (path) {
            await putAudio(path, wav).catch((err: unknown) => {
              console.error(`[api] failed to persist audio ${path}:`, err);
            });
          }
        }
        sendWav(req, res, wav);
      } catch (err) {
        res.status(400).json({ error: err instanceof Error ? err.message : String(err) });
      }
    }),
  );

  // Read the signed-in user's playback preferences (defaults when unset).
  api.get(
    '/preferences',
    asyncHandler(async (req, res) => {
      const prefs = await getUserPreferences(requestUser(req).id);
      res.json(prefs ?? { voice: DEFAULT_VOICE });
    }),
  );

  // Save the signed-in user's playback preferences (voice), reused next time.
  api.put(
    '/preferences',
    asyncHandler(async (req, res) => {
      const body = req.body as Partial<UserPreferences>;
      const voice = typeof body.voice === 'string' && body.voice.trim() ? body.voice : DEFAULT_VOICE;
      await setUserPreferences(requestUser(req).id, { voice });
      res.json({ voice });
    }),
  );

  // Delete one of the user's podcasts.
  api.delete(
    '/podcasts/:id',
    asyncHandler(async (req, res) => {
      const podcast = await readPodcast(String(req.params.id));
      if (!podcast || podcast.ownerId !== requestUser(req).id) {
        res.status(404).end();
        return;
      }
      await removePodcast(podcast.id);
      // Best-effort cleanup of the stored audio objects.
      await deletePodcastAudio(podcast.id).catch(() => {});
      res.status(204).end();
    }),
  );

  app.use('/api', api);
}
