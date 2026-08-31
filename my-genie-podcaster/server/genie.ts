/**
 * Genie client helpers.
 *
 * These take a WorkspaceClient scoped to the signed-in user (on-behalf-of), so
 * Genie queries run with that user's permissions. We call the Genie
 * Conversation API directly (not the AppKit `genie()` plugin) because the plugin
 * is bound to space aliases configured at startup, whereas this app lets the
 * user target an arbitrary Genie space (by name or ID) at request time.
 */
import type { WorkspaceClient } from '@databricks/sdk-experimental';
import type { GenieSpaceOption, GenieSpaceRef, QueryData } from '../shared/types';

/** Genie space IDs are long hex-ish strings with no spaces. */
const SPACE_ID_RE = /^[0-9a-fA-F]{16,}$/;

/**
 * Build a deep link that opens a Genie conversation in the workspace UI:
 *   https://<host>/genie/rooms/<spaceId>/chats/<conversationId>?o=<workspaceId>
 */
export function genieConversationUrl(
  host: string,
  spaceId: string,
  conversationId: string,
): string {
  const base = /^https?:\/\//.test(host) ? host : `https://${host}`;
  const url = new URL(`/genie/rooms/${spaceId}/chats/${conversationId}`, base);
  const workspaceId = process.env.DATABRICKS_WORKSPACE_ID;
  if (workspaceId) url.searchParams.set('o', workspaceId);
  return url.toString();
}

/** Poll timeout for a single Genie message (ms). Genie can be slow on cold warehouses. */
const MESSAGE_TIMEOUT_MS = 180_000;
const POLL_INTERVAL_MS = 1_500;

/** Pieces of a Genie "agent" message we consume (incl. reasoning + result data). */
interface GenieAnswer {
  conversationId: string;
  messageId: string;
  /** The answer text (ANSWER-purpose text attachments only). */
  rawText: string;
  sql?: string;
  queryDescription?: string;
  rowCount?: number;
  /** Genie's step-by-step reasoning ("thoughts"). */
  reasoning?: string;
  /** Preview of the actual query result rows. */
  data?: QueryData;
}

/** The Genie API surface off a (user-scoped) WorkspaceClient. */
type GenieService = WorkspaceClient['genie'];

// --- Raw message shapes (fields the typed SDK omits, e.g. `thoughts`). ---
interface RawThought {
  thought_type?: string;
  content?: string;
}
interface RawQueryAttachment {
  query?: string;
  description?: string;
  statement_id?: string;
  thoughts?: RawThought[];
  query_result_metadata?: { row_count?: number };
}
interface RawTextAttachment {
  content?: string;
  purpose?: string;
}
interface RawAttachment {
  attachment_id?: string;
  text?: RawTextAttachment;
  query?: RawQueryAttachment;
}
interface RawMessage {
  status?: string;
  error?: { error?: string };
  attachments?: RawAttachment[];
}

const THOUGHT_LABELS: Record<string, string> = {
  THOUGHT_TYPE_UNDERSTANDING: 'Understanding',
  THOUGHT_TYPE_DATA_SOURCING: 'Data sources',
  THOUGHT_TYPE_STEPS: 'Steps',
  THOUGHT_TYPE_DESCRIPTION: 'Approach',
};

/** Format the agent's `thoughts` into a readable reasoning block. */
function formatReasoning(thoughts: RawThought[] | undefined): string | undefined {
  if (!thoughts?.length) return undefined;
  const parts: string[] = [];
  for (const t of thoughts) {
    const content = t.content?.trim();
    if (!content) continue;
    const label = THOUGHT_LABELS[t.thought_type ?? ''] ?? 'Note';
    parts.push(`${label}:\n${content}`);
  }
  return parts.length ? parts.join('\n\n') : undefined;
}

/**
 * Resolve a user-supplied space name or ID to a concrete space.
 * Tries a direct lookup when the input looks like an ID, then falls back to a
 * case-insensitive title match across all spaces the caller can see.
 */
export async function resolveSpace(
  client: WorkspaceClient,
  input: string,
): Promise<GenieSpaceRef> {
  const genie = client.genie;
  const trimmed = input.trim();

  if (SPACE_ID_RE.test(trimmed)) {
    try {
      const space = await genie.getSpace({ space_id: trimmed });
      return { id: space.space_id, name: space.title };
    } catch {
      // Not a valid ID after all — fall through to name search.
    }
  }

  const wanted = trimmed.toLowerCase();
  let pageToken: string | undefined;
  const seen: GenieSpaceOption[] = [];
  do {
    const resp = await genie.listSpaces({ page_token: pageToken });
    for (const s of resp.spaces ?? []) {
      seen.push({ id: s.space_id, title: s.title, description: s.description });
      if (s.space_id === trimmed || s.title.toLowerCase() === wanted) {
        return { id: s.space_id, name: s.title };
      }
    }
    pageToken = resp.next_page_token;
  } while (pageToken);

  const sample = seen
    .slice(0, 8)
    .map((s) => `"${s.title}"`)
    .join(', ');
  throw new Error(
    `No Genie space matches "${input}". Available spaces include: ${sample || '(none visible)'}.`,
  );
}

/** List Genie spaces the caller can access (for the space picker). */
export async function listSpaces(client: WorkspaceClient): Promise<GenieSpaceOption[]> {
  const genie = client.genie;
  const out: GenieSpaceOption[] = [];
  let pageToken: string | undefined;
  do {
    const resp = await genie.listSpaces({ page_token: pageToken });
    for (const s of resp.spaces ?? []) {
      out.push({ id: s.space_id, title: s.title, description: s.description });
    }
    pageToken = resp.next_page_token;
  } while (pageToken);
  return out;
}

/** Build the instruction wrapper that makes Genie emit SUMMARY + DETAILS. */
export function wrapQuestion(question: string): string {
  return [
    'Please answer the question in exactly two labeled sections.',
    '',
    'First output a line beginning with "SUMMARY:" followed by 3 to 6 sentences of plain,',
    'natural spoken English meant to be READ ALOUD in a podcast. This is the only part that is',
    'narrated, so it must sound like a person talking:',
    '  - Give the ANALYSIS and INSIGHTS: the takeaway, the trend, what is driving it, and why it',
    '    matters. Compare to targets or prior periods where relevant.',
    '  - Use only SUMMARIZED, ROUNDED numbers, spelled naturally (e.g. "about five and a half',
    '    times", "up from roughly one times a month ago", "around eighty thousand dollars").',
    '  - Do NOT read out SQL, column names, table names, raw query results, row-by-row values,',
    '    long precise decimals, dates as ISO strings, or any code. No lists, tables, or markdown.',
    '',
    'Then output a line beginning with "DETAILS:" followed by the specific supporting numbers and',
    'breakdown (exact figures, per-item values). This part is shown on screen, not read aloud.',
    '',
    `Question: ${question}`,
  ].join('\n');
}

/** Split a Genie response into spoken summary + supporting details. */
export function parseSummaryDetails(rawText: string): { summary: string; details: string } {
  const text = rawText.trim();
  // Match "SUMMARY:" and "DETAILS:" allowing markdown emphasis/backticks around
  // the label — including after the colon (e.g. "**SUMMARY:**"), so no stray
  // asterisks leak into the narrated text.
  const summaryMatch = text.match(/[*_`#\s]*summary[*_`\s]*:[*_`\s]*/i);
  const detailsMatch = text.match(/[*_`#\s]*details[*_`\s]*:[*_`\s]*/i);

  if (
    summaryMatch?.index !== undefined &&
    detailsMatch?.index !== undefined &&
    summaryMatch.index < detailsMatch.index
  ) {
    const summaryStart = summaryMatch.index + summaryMatch[0].length;
    const summary = text.slice(summaryStart, detailsMatch.index).trim();
    const details = text.slice(detailsMatch.index + detailsMatch[0].length).trim();
    if (summary) return { summary, details };
  }

  // Fallback: Genie ignored the format — narrate the whole answer.
  return { summary: text, details: '' };
}

/** Max result rows to include in the on-screen data preview. */
const MAX_PREVIEW_ROWS = 12;

/** Fetch the full raw message JSON (includes `thoughts`, which the SDK omits). */
async function fetchRawMessage(
  client: WorkspaceClient,
  spaceId: string,
  conversationId: string,
  messageId: string,
): Promise<RawMessage> {
  const raw = await client.apiClient.request({
    path: `/api/2.0/genie/spaces/${spaceId}/conversations/${conversationId}/messages/${messageId}`,
    method: 'GET',
    headers: new Headers(),
    raw: false,
  });
  return raw as RawMessage;
}

/** Fetch a preview of the actual result rows for a query attachment. */
async function fetchQueryData(
  client: WorkspaceClient,
  spaceId: string,
  conversationId: string,
  messageId: string,
  attachmentId: string,
): Promise<QueryData | undefined> {
  try {
    const resp = await client.genie.getMessageAttachmentQueryResult({
      space_id: spaceId,
      conversation_id: conversationId,
      message_id: messageId,
      attachment_id: attachmentId,
    });
    const sr = resp.statement_response;
    const columns = (sr?.manifest?.schema?.columns ?? [])
      .map((c) => c.name ?? '')
      .filter(Boolean);
    const allRows = sr?.result?.data_array;
    if (!columns.length || !allRows?.length) return undefined;
    return {
      columns,
      rows: allRows.slice(0, MAX_PREVIEW_ROWS),
      totalRows: sr?.manifest?.total_row_count ?? allRows.length,
      truncated: (sr?.manifest?.total_row_count ?? allRows.length) > MAX_PREVIEW_ROWS,
    };
  } catch {
    return undefined; // result may be expired/external — skip the preview
  }
}

async function pollMessage(
  client: WorkspaceClient,
  spaceId: string,
  conversationId: string,
  messageId: string,
): Promise<GenieAnswer> {
  const genie: GenieService = client.genie;
  const deadline = Date.now() + MESSAGE_TIMEOUT_MS;
  for (;;) {
    const msg = await genie.getMessage({
      space_id: spaceId,
      conversation_id: conversationId,
      message_id: messageId,
    });

    if (msg.status === 'FAILED' || msg.status === 'CANCELLED') {
      throw new Error(msg.error?.error ?? `Genie message ${msg.status}`);
    }

    if (msg.status === 'COMPLETED') {
      // Re-read the raw JSON so we get the agent's `thoughts` (reasoning),
      // which the typed SDK does not surface.
      const raw = await fetchRawMessage(client, spaceId, conversationId, messageId).catch(
        () => ({ attachments: msg.attachments as RawAttachment[] }) as RawMessage,
      );
      const attachments = raw.attachments ?? [];

      // Only the ANSWER text is the response; ignore follow-up/clarifying text.
      const answerTexts = attachments
        .filter((a) => a.text?.purpose === 'TEXT_ATTACHMENT_PURPOSE_ANSWER' && a.text.content)
        .map((a) => a.text!.content!.trim());
      const anyText = attachments.filter((a) => a.text?.content).map((a) => a.text!.content!.trim());

      const queryAtt = attachments.find((a) => a.query);
      const q = queryAtt?.query;

      let data: QueryData | undefined;
      if (queryAtt?.attachment_id) {
        data = await fetchQueryData(client, spaceId, conversationId, messageId, queryAtt.attachment_id);
      }

      return {
        conversationId,
        messageId,
        rawText: (answerTexts.length ? answerTexts : anyText).join('\n\n'),
        sql: q?.query,
        queryDescription: q?.description,
        rowCount: q?.query_result_metadata?.row_count,
        reasoning: formatReasoning(q?.thoughts),
        data,
      };
    }

    if (Date.now() > deadline) {
      throw new Error(`Genie timed out after ${MESSAGE_TIMEOUT_MS / 1000}s (status: ${msg.status ?? 'unknown'})`);
    }
    await new Promise((r) => setTimeout(r, POLL_INTERVAL_MS));
  }
}

/**
 * Ask Genie one question (wrapped for SUMMARY/DETAILS). Pass an existing
 * `conversationId` to keep context across a podcast's questions; omit it for
 * the first question to start a new conversation.
 */
export async function askForSummaryDetails(
  client: WorkspaceClient,
  spaceId: string,
  conversationId: string | undefined,
  question: string,
): Promise<GenieAnswer> {
  const genie = client.genie;
  const content = wrapQuestion(question);

  if (!conversationId) {
    const started = await genie.startConversation({ space_id: spaceId, content });
    return pollMessage(client, spaceId, started.conversation_id, started.message_id);
  }

  const created = await genie.createMessage({
    space_id: spaceId,
    conversation_id: conversationId,
    content,
  });
  return pollMessage(client, spaceId, conversationId, created.message_id);
}
