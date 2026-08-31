/**
 * Types shared between the Express server and the React client.
 *
 * A "podcast" is a set of user questions answered by a Genie space. For each
 * question Genie is asked to return a spoken-friendly SUMMARY plus supporting
 * DETAILS; the podcast player narrates the summaries with Kokoro-82M.
 */

export type PodcastStatus = 'generating' | 'ready' | 'error';
export type SegmentStatus = 'pending' | 'generating' | 'done' | 'error';

/** A preview of a Genie query's result set. */
export interface QueryData {
  columns: string[];
  rows: string[][];
  totalRows?: number;
  truncated?: boolean;
}

/** One question and its Genie-derived answer. */
export interface PodcastSegment {
  question: string;
  /** Spoken-friendly narration (the part read aloud). */
  summary: string;
  /** Supporting figures / breakdown (shown on screen, not narrated). */
  details: string;
  /** Generated SQL, if Genie produced a query attachment. */
  sql?: string;
  /** Genie's description of the query. */
  queryDescription?: string;
  /** Row count of the query result, if available. */
  rowCount?: number;
  /** Genie's step-by-step reasoning ("thoughts": understanding, data sources, steps). */
  reasoning?: string;
  /** Preview of the actual query result rows. */
  data?: QueryData;
  status: SegmentStatus;
  error?: string;
  /**
   * State of the pre-generated narration audio (default voice), stored in the
   * UC Volume. When `ready`, Play streams it instantly with no synthesis wait.
   */
  audioStatus?: 'pending' | 'generating' | 'ready' | 'error';
  /** Why pre-generation of the narration audio failed (when `audioStatus` is `error`). */
  audioError?: string;
}

export interface GenieSpaceRef {
  id: string;
  name: string;
}

/** A full podcast episode with all segments. */
export interface Podcast {
  id: string;
  title: string;
  genieSpace: GenieSpaceRef;
  /** Owner identity (from the signed-in user); used to scope access. */
  ownerId: string;
  ownerEmail?: string;
  createdAt: string;
  updatedAt: string;
  status: PodcastStatus;
  error?: string;
  segments: PodcastSegment[];
  /** Genie conversation id shared by all questions in this podcast. */
  conversationId?: string;
  /** Deep link to open this podcast's conversation in the Genie UI. */
  genieUrl?: string;
}

/** Lightweight shape used for the list view. */
export interface PodcastSummary {
  id: string;
  title: string;
  genieSpace: GenieSpaceRef;
  createdAt: string;
  status: PodcastStatus;
  questionCount: number;
  doneCount: number;
}

/** Request body for creating a podcast. */
export interface CreatePodcastRequest {
  /** Genie space name or ID. */
  genieSpace: string;
  title?: string;
  questions: string[];
}

/** An available Genie space (for the picker). */
export interface GenieSpaceOption {
  id: string;
  title: string;
  description?: string;
}

/** Per-user playback preferences, persisted in Lakebase and reused next time. */
export interface UserPreferences {
  /** Preferred narration voice id (Kokoro voice). */
  voice: string;
}
