/**
 * Orchestrates podcast creation: resolve the Genie space, then ask each
 * question in the background (reusing one conversation for context), parsing
 * each answer into a spoken summary + supporting details and persisting
 * progress after every step so the client can poll it.
 */
import { randomUUID } from 'node:crypto';
import type { WorkspaceClient } from '@databricks/sdk-experimental';
import type { CreatePodcastRequest, Podcast, PodcastSegment } from '../shared/types';
import {
  askForSummaryDetails,
  genieConversationUrl,
  parseSummaryDetails,
  resolveSpace,
} from './genie';
import { writePodcast, writePodcastMeta, writeSegment } from './storage';
import { DEFAULT_VOICE, synthesize } from './tts';
import { audioConfigured, audioPath, putAudio } from './audio-store';
import type { RequestUser } from './user';

/** Ids currently being generated in this process (guards double-processing). */
const inFlight = new Set<string>();

function nowIso(): string {
  return new Date().toISOString();
}

/**
 * Validate input, resolve the space, persist a pending podcast, and kick off
 * background generation. Returns the created podcast immediately.
 */
export async function createPodcast(
  user: RequestUser,
  req: CreatePodcastRequest,
): Promise<Podcast> {
  const questions = (req.questions ?? []).map((q) => q.trim()).filter(Boolean);
  if (!req.genieSpace?.trim()) throw new Error('A Genie space name or ID is required.');
  if (questions.length === 0) throw new Error('At least one question is required.');

  const space = await resolveSpace(user.client, req.genieSpace);

  const podcast: Podcast = {
    id: randomUUID(),
    title: req.title?.trim() || `${space.name} — ${new Date().toLocaleDateString()}`,
    genieSpace: space,
    ownerId: user.id,
    ownerEmail: user.email,
    createdAt: nowIso(),
    updatedAt: nowIso(),
    status: 'generating',
    segments: questions.map<PodcastSegment>((question) => ({
      question,
      summary: '',
      details: '',
      status: 'pending',
    })),
  };

  await writePodcast(podcast);
  // Fire and forget — generation continues after the HTTP response is sent,
  // using the user's OBO client captured at request time.
  void generateInBackground(user.client, podcast);
  return podcast;
}

async function generateInBackground(client: WorkspaceClient, podcast: Podcast): Promise<void> {
  if (inFlight.has(podcast.id)) return;
  inFlight.add(podcast.id);
  try {
    let conversationId: string | undefined;
    let anySucceeded = false;

    for (let idx = 0; idx < podcast.segments.length; idx++) {
      const segment = podcast.segments[idx];
      segment.status = 'generating';
      podcast.updatedAt = nowIso();
      await writePodcastMeta(podcast);
      await writeSegment(podcast.id, idx, segment);

      try {
        const answer = await askForSummaryDetails(
          client,
          podcast.genieSpace.id,
          conversationId,
          segment.question,
        );
        conversationId = answer.conversationId;
        // Capture the conversation + its Genie UI deep link on the first answer.
        if (!podcast.conversationId) {
          podcast.conversationId = conversationId;
          const host = client.config.host;
          if (host) {
            podcast.genieUrl = genieConversationUrl(host, podcast.genieSpace.id, conversationId);
          }
        }

        const { summary, details } = parseSummaryDetails(answer.rawText);
        segment.summary = summary;
        segment.details = details;
        segment.sql = answer.sql;
        segment.queryDescription = answer.queryDescription;
        segment.rowCount = answer.rowCount;
        segment.reasoning = answer.reasoning;
        segment.data = answer.data;
        segment.status = 'done';
        anySucceeded = true;
      } catch (err) {
        segment.status = 'error';
        segment.error = err instanceof Error ? err.message : String(err);
      }

      podcast.updatedAt = nowIso();
      await writeSegment(podcast.id, idx, segment);

      // Pre-synthesize the default-voice narration and store it durably so
      // Play streams ready-made audio (no synthesis wait on first click).
      // Only meaningful when a UC Volume is configured to persist it.
      const path = audioConfigured()
        ? audioPath(podcast.id, idx, DEFAULT_VOICE, segment.summary)
        : null;
      if (segment.status === 'done' && segment.summary.trim() && path) {
        segment.audioStatus = 'generating';
        podcast.updatedAt = nowIso();
        await writeSegment(podcast.id, idx, segment);
        try {
          const wav = await synthesize(segment.summary, DEFAULT_VOICE);
          await putAudio(path, wav);
          segment.audioStatus = 'ready';
          segment.audioError = undefined;
        } catch (err) {
          segment.audioStatus = 'error';
          segment.audioError = err instanceof Error ? err.message : String(err);
          console.error(`[podcast ${podcast.id}] audio pre-gen failed for #${idx}:`, err);
        }
        podcast.updatedAt = nowIso();
        await writeSegment(podcast.id, idx, segment);
      }
    }

    podcast.status = anySucceeded ? 'ready' : 'error';
    if (!anySucceeded) podcast.error = 'All questions failed. See individual segments.';
    podcast.updatedAt = nowIso();
    await writePodcastMeta(podcast);
  } catch (err) {
    podcast.status = 'error';
    podcast.error = err instanceof Error ? err.message : String(err);
    podcast.updatedAt = nowIso();
    await writePodcastMeta(podcast).catch(() => {});
  } finally {
    inFlight.delete(podcast.id);
  }
}
