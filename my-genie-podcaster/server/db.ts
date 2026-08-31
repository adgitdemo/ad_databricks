/**
 * Lakebase (Postgres) access for durable podcast storage.
 *
 * The AppKit `lakebase()` plugin owns the connection pool and OAuth refresh;
 * we capture its `query` function during `onPluginsReady` (see server.ts) so
 * the storage layer can issue parameterized SQL. Data is stored under the
 * app's service principal and scoped per user via an `owner_id` column.
 */
import type { QueryResult, QueryResultRow } from 'pg';

export type QueryFn = <T extends QueryResultRow = Record<string, unknown>>(
  text: string,
  values?: unknown[],
) => Promise<QueryResult<T>>;

/**
 * Dedicated schema for this app's tables. Postgres 15+ does not grant CREATE on
 * the built-in `public` schema to non-owners, but the app SP (granted
 * CAN_CONNECT_AND_CREATE) may create its own schema and own everything in it.
 */
export const SCHEMA = 'podcast';

let queryFn: QueryFn | null = null;

/** Wire in the Lakebase query function (called once at startup). */
export function setDb(fn: QueryFn): void {
  queryFn = fn;
}

/** The Lakebase query function; throws if the plugin isn't initialized yet. */
export function db(): QueryFn {
  if (!queryFn) throw new Error('Lakebase is not initialized (call setDb first).');
  return queryFn;
}

/** True once a Lakebase pool has been wired in. */
export function hasDb(): boolean {
  return queryFn !== null;
}

/** Create the podcast tables if they don't exist (app SP has CAN_CONNECT_AND_CREATE). */
export async function initSchema(): Promise<void> {
  const q = db();
  await q(`CREATE SCHEMA IF NOT EXISTS ${SCHEMA}`);
  await q(`
    CREATE TABLE IF NOT EXISTS ${SCHEMA}.podcasts (
      id                UUID PRIMARY KEY,
      owner_id          TEXT NOT NULL,
      owner_email       TEXT,
      title             TEXT NOT NULL,
      genie_space_id    TEXT NOT NULL,
      genie_space_name  TEXT NOT NULL,
      status            TEXT NOT NULL,
      error             TEXT,
      created_at        TIMESTAMPTZ NOT NULL,
      updated_at        TIMESTAMPTZ NOT NULL,
      conversation_id   TEXT,
      genie_url         TEXT
    )
  `);
  // Add newer columns to a pre-existing table (no-op when already present).
  await q(`ALTER TABLE ${SCHEMA}.podcasts ADD COLUMN IF NOT EXISTS conversation_id TEXT`);
  await q(`ALTER TABLE ${SCHEMA}.podcasts ADD COLUMN IF NOT EXISTS genie_url TEXT`);
  await q(`
    CREATE INDEX IF NOT EXISTS podcasts_owner_created_idx
      ON ${SCHEMA}.podcasts (owner_id, created_at DESC)
  `);
  await q(`
    CREATE TABLE IF NOT EXISTS ${SCHEMA}.segments (
      podcast_id        UUID NOT NULL REFERENCES ${SCHEMA}.podcasts (id) ON DELETE CASCADE,
      idx               INTEGER NOT NULL,
      question          TEXT NOT NULL,
      summary           TEXT NOT NULL DEFAULT '',
      details           TEXT NOT NULL DEFAULT '',
      sql               TEXT,
      query_description TEXT,
      row_count         INTEGER,
      reasoning         TEXT,
      data              JSONB,
      status            TEXT NOT NULL,
      error             TEXT,
      audio_status      TEXT,
      audio_error       TEXT,
      PRIMARY KEY (podcast_id, idx)
    )
  `);
  // Ensure audio_error exists on tables created before it was added (no-op otherwise).
  await q(`ALTER TABLE ${SCHEMA}.segments ADD COLUMN IF NOT EXISTS audio_error TEXT`);
  await q(`
    CREATE TABLE IF NOT EXISTS ${SCHEMA}.user_preferences (
      owner_id    TEXT PRIMARY KEY,
      voice       TEXT NOT NULL,
      updated_at  TIMESTAMPTZ NOT NULL
    )
  `);
}
