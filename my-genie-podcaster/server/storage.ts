/**
 * Durable podcast persistence in Lakebase (Postgres).
 *
 * Replaces the previous local-JSON store: podcasts and their segments now
 * survive app redeploys and are queried per user via `owner_id`. Audio bytes
 * live in a UC Volume (see audio-store.ts); this module stores only metadata
 * plus each segment's audio status.
 */
import type {
  Podcast,
  PodcastSegment,
  PodcastSummary,
  QueryData,
  UserPreferences,
} from '../shared/types';
import { db, SCHEMA } from './db';

interface PodcastRow {
  id: string;
  owner_id: string;
  owner_email: string | null;
  title: string;
  genie_space_id: string;
  genie_space_name: string;
  status: string;
  error: string | null;
  created_at: Date;
  updated_at: Date;
  conversation_id: string | null;
  genie_url: string | null;
}

interface SegmentRow {
  idx: number;
  question: string;
  summary: string;
  details: string;
  sql: string | null;
  query_description: string | null;
  row_count: number | null;
  reasoning: string | null;
  data: QueryData | null;
  status: string;
  error: string | null;
  audio_status: string | null;
  audio_error: string | null;
}

function iso(value: Date | string): string {
  return value instanceof Date ? value.toISOString() : new Date(value).toISOString();
}

function rowToSegment(r: SegmentRow): PodcastSegment {
  return {
    question: r.question,
    summary: r.summary,
    details: r.details,
    sql: r.sql ?? undefined,
    queryDescription: r.query_description ?? undefined,
    rowCount: r.row_count ?? undefined,
    reasoning: r.reasoning ?? undefined,
    data: r.data ?? undefined,
    status: r.status as PodcastSegment['status'],
    error: r.error ?? undefined,
    audioStatus: (r.audio_status as PodcastSegment['audioStatus']) ?? undefined,
    audioError: r.audio_error ?? undefined,
  };
}

function rowToPodcast(p: PodcastRow, segments: SegmentRow[]): Podcast {
  return {
    id: p.id,
    title: p.title,
    genieSpace: { id: p.genie_space_id, name: p.genie_space_name },
    ownerId: p.owner_id,
    ownerEmail: p.owner_email ?? undefined,
    createdAt: iso(p.created_at),
    updatedAt: iso(p.updated_at),
    status: p.status as Podcast['status'],
    error: p.error ?? undefined,
    conversationId: p.conversation_id ?? undefined,
    genieUrl: p.genie_url ?? undefined,
    segments: segments.sort((a, b) => a.idx - b.idx).map(rowToSegment),
  };
}

/** Upsert only the `podcasts` row (metadata/status), not its segments. */
export async function writePodcastMeta(podcast: Podcast): Promise<void> {
  await db()(
    `INSERT INTO ${SCHEMA}.podcasts
       (id, owner_id, owner_email, title, genie_space_id, genie_space_name,
        status, error, created_at, updated_at, conversation_id, genie_url)
     VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12)
     ON CONFLICT (id) DO UPDATE SET
       title = EXCLUDED.title,
       status = EXCLUDED.status,
       error = EXCLUDED.error,
       updated_at = EXCLUDED.updated_at,
       conversation_id = EXCLUDED.conversation_id,
       genie_url = EXCLUDED.genie_url`,
    [
      podcast.id,
      podcast.ownerId,
      podcast.ownerEmail ?? null,
      podcast.title,
      podcast.genieSpace.id,
      podcast.genieSpace.name,
      podcast.status,
      podcast.error ?? null,
      podcast.createdAt,
      podcast.updatedAt,
      podcast.conversationId ?? null,
      podcast.genieUrl ?? null,
    ],
  );
}

/** Upsert a single segment row. */
export async function writeSegment(
  podcastId: string,
  idx: number,
  s: PodcastSegment,
): Promise<void> {
  await db()(
    `INSERT INTO ${SCHEMA}.segments
       (podcast_id, idx, question, summary, details, sql, query_description,
        row_count, reasoning, data, status, error, audio_status, audio_error)
     VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14)
     ON CONFLICT (podcast_id, idx) DO UPDATE SET
       question = EXCLUDED.question,
       summary = EXCLUDED.summary,
       details = EXCLUDED.details,
       sql = EXCLUDED.sql,
       query_description = EXCLUDED.query_description,
       row_count = EXCLUDED.row_count,
       reasoning = EXCLUDED.reasoning,
       data = EXCLUDED.data,
       status = EXCLUDED.status,
       error = EXCLUDED.error,
       audio_status = EXCLUDED.audio_status,
       audio_error = EXCLUDED.audio_error`,
    [
      podcastId,
      idx,
      s.question,
      s.summary,
      s.details,
      s.sql ?? null,
      s.queryDescription ?? null,
      s.rowCount ?? null,
      s.reasoning ?? null,
      s.data ? JSON.stringify(s.data) : null,
      s.status,
      s.error ?? null,
      s.audioStatus ?? null,
      s.audioError ?? null,
    ],
  );
}

/** Insert or update a podcast and all of its segments. */
export async function writePodcast(podcast: Podcast): Promise<void> {
  await writePodcastMeta(podcast);
  for (let idx = 0; idx < podcast.segments.length; idx++) {
    await writeSegment(podcast.id, idx, podcast.segments[idx]);
  }
}

/**
 * Fail any podcasts left mid-generation by an app restart. Generation runs in
 * the process that received the request (as that user), so it cannot resume
 * after a restart — mark the orphaned rows as errored so the UI stops polling
 * them forever and shows a re-createable state. Returns the number fixed.
 */
export async function failInterruptedPodcasts(): Promise<number> {
  const q = db();
  await q(
    `UPDATE ${SCHEMA}.segments SET status = 'error',
       error = COALESCE(error, 'Interrupted by an app restart.')
     WHERE status IN ('pending', 'generating')`,
  );
  const res = await q(
    `UPDATE ${SCHEMA}.podcasts SET status = 'error',
       error = 'Generation was interrupted by an app restart. Please create the podcast again.',
       updated_at = now()
     WHERE status = 'generating'`,
  );
  return res.rowCount ?? 0;
}

export async function readPodcast(id: string): Promise<Podcast | null> {
  const q = db();
  const podcasts = await q<PodcastRow>(`SELECT * FROM ${SCHEMA}.podcasts WHERE id = $1`, [id]);
  const p = podcasts.rows[0];
  if (!p) return null;
  const segments = await q<SegmentRow>(
    `SELECT * FROM ${SCHEMA}.segments WHERE podcast_id = $1`,
    [id],
  );
  return rowToPodcast(p, segments.rows);
}

export async function removePodcast(id: string): Promise<boolean> {
  // Segments cascade via the FK; report whether a row was actually removed.
  const res = await db()(`DELETE FROM ${SCHEMA}.podcasts WHERE id = $1`, [id]);
  return (res.rowCount ?? 0) > 0;
}

/** List podcasts owned by `ownerId` (per-user scoping). */
export async function listPodcasts(ownerId: string): Promise<PodcastSummary[]> {
  const res = await db()<
    PodcastRow & { question_count: string; done_count: string }
  >(
    `SELECT p.*,
       (SELECT count(*) FROM ${SCHEMA}.segments s WHERE s.podcast_id = p.id) AS question_count,
       (SELECT count(*) FROM ${SCHEMA}.segments s WHERE s.podcast_id = p.id AND s.status = 'done') AS done_count
     FROM ${SCHEMA}.podcasts p
     WHERE p.owner_id = $1
     ORDER BY p.created_at DESC`,
    [ownerId],
  );
  return res.rows.map((p) => ({
    id: p.id,
    title: p.title,
    genieSpace: { id: p.genie_space_id, name: p.genie_space_name },
    createdAt: iso(p.created_at),
    status: p.status as PodcastSummary['status'],
    questionCount: Number(p.question_count),
    doneCount: Number(p.done_count),
  }));
}

/** Read a user's saved playback preferences, or `null` if none stored yet. */
export async function getUserPreferences(ownerId: string): Promise<UserPreferences | null> {
  const res = await db()<{ voice: string }>(
    `SELECT voice FROM ${SCHEMA}.user_preferences WHERE owner_id = $1`,
    [ownerId],
  );
  const row = res.rows[0];
  return row ? { voice: row.voice } : null;
}

/** Upsert a user's playback preferences. */
export async function setUserPreferences(
  ownerId: string,
  prefs: UserPreferences,
): Promise<void> {
  await db()(
    `INSERT INTO ${SCHEMA}.user_preferences (owner_id, voice, updated_at)
     VALUES ($1, $2, now())
     ON CONFLICT (owner_id) DO UPDATE SET
       voice = EXCLUDED.voice,
       updated_at = EXCLUDED.updated_at`,
    [ownerId, prefs.voice],
  );
}
