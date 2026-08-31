import type {
  CreatePodcastRequest,
  GenieSpaceOption,
  Podcast,
  PodcastSummary,
  UserPreferences,
} from '@shared/types';

async function parse<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let message = `${res.status} ${res.statusText}`;
    try {
      const body = (await res.json()) as { error?: string };
      if (body?.error) message = body.error;
    } catch {
      // non-JSON error body — keep the status text
    }
    throw new Error(message);
  }
  return (await res.json()) as T;
}

export const api = {
  listSpaces: (): Promise<GenieSpaceOption[]> =>
    fetch('/api/genie/spaces').then((r) => parse<GenieSpaceOption[]>(r)),

  listPodcasts: (): Promise<PodcastSummary[]> =>
    fetch('/api/podcasts').then((r) => parse<PodcastSummary[]>(r)),

  getPodcast: (id: string): Promise<Podcast> =>
    fetch(`/api/podcasts/${id}`).then((r) => parse<Podcast>(r)),

  createPodcast: (body: CreatePodcastRequest): Promise<Podcast> =>
    fetch('/api/podcasts', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }).then((r) => parse<Podcast>(r)),

  deletePodcast: async (id: string): Promise<void> => {
    const res = await fetch(`/api/podcasts/${id}`, { method: 'DELETE' });
    if (!res.ok && res.status !== 204) throw new Error(`Failed to delete (${res.status})`);
  },

  getPreferences: (): Promise<UserPreferences> =>
    fetch('/api/preferences').then((r) => parse<UserPreferences>(r)),

  putPreferences: (prefs: UserPreferences): Promise<UserPreferences> =>
    fetch('/api/preferences', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(prefs),
    }).then((r) => parse<UserPreferences>(r)),
};
