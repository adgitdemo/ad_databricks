import { useEffect, useMemo, useState } from 'react';
import { useParams, Link, useNavigate } from 'react-router';
import {
  Play,
  Pause,
  Square,
  Loader2,
  AlertCircle,
  ArrowLeft,
  Volume2,
  ExternalLink,
  Trash2,
} from 'lucide-react';
import type { Podcast } from '@shared/types';
import { api } from '@/lib/api';
import { usePodcastPlayer } from '@/hooks/usePodcastPlayer';
import { DEFAULT_VOICE, RECOMMENDED_VOICES } from '@/lib/voices';
import {
  Button,
  buttonClasses,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  CardDescription,
  Badge,
  Alert,
  AlertDescription,
  Select,
  Disclosure,
} from '@/components/ui';

const POLL_INTERVAL_MS = 2_000;

export function PodcastDetailPage() {
  const { id = '' } = useParams();
  const navigate = useNavigate();
  const [podcast, setPodcast] = useState<Podcast | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [voice, setVoice] = useState(DEFAULT_VOICE);
  const [deleting, setDeleting] = useState(false);

  const player = usePodcastPlayer();

  async function handleDelete() {
    if (!podcast) return;
    if (!window.confirm(`Delete “${podcast.title}”? This permanently removes the podcast and its audio.`)) {
      return;
    }
    setDeleting(true);
    player.stop();
    try {
      await api.deletePodcast(podcast.id);
      await navigate('/');
    } catch (err) {
      setLoadError(err instanceof Error ? err.message : String(err));
      setDeleting(false);
    }
  }

  // Load the user's saved voice preference once (reused across podcasts).
  useEffect(() => {
    api
      .getPreferences()
      .then((p) => setVoice(p.voice))
      .catch(() => {});
  }, []);

  const changeVoice = (next: string) => {
    setVoice(next);
    // Remember the choice for next time (best-effort).
    void api.putPreferences({ voice: next }).catch(() => {});
  };

  useEffect(() => {
    let active = true;
    let timer: ReturnType<typeof setTimeout>;
    async function tick() {
      try {
        const p = await api.getPodcast(id);
        if (!active) return;
        setPodcast(p);
        if (p.status === 'generating') timer = setTimeout(() => void tick(), POLL_INTERVAL_MS);
      } catch (err) {
        if (active) setLoadError(err instanceof Error ? err.message : String(err));
      }
    }
    void tick();
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, [id]);

  const playable = useMemo(
    () =>
      (podcast?.segments ?? [])
        .map((seg, index) => ({ seg, index }))
        .filter(({ seg }) => seg.status === 'done' && seg.summary.trim().length > 0),
    [podcast],
  );
  const playableIndices = useMemo(() => playable.map((p) => p.index), [playable]);
  const activeSegmentIndex = player.currentSegment;
  const canPlay = playableIndices.length > 0;

  // Warm the first playable segment's audio (server synth + browser cache) as
  // soon as it's ready, and again when the voice changes, so pressing Play
  // starts immediately instead of waiting on a first synthesis.
  const firstPlayable = canPlay ? playableIndices[0] : -1;
  useEffect(() => {
    if (firstPlayable < 0) return;
    const controller = new AbortController();
    fetch(`/api/podcasts/${id}/audio/${firstPlayable}?voice=${encodeURIComponent(voice)}`, {
      signal: controller.signal,
    }).catch(() => {});
    return () => controller.abort();
  }, [id, voice, firstPlayable]);

  if (loadError) {
    return (
      <div className="mx-auto max-w-2xl">
        <Alert variant="destructive">
          <AlertCircle className="h-4 w-4 shrink-0" />
          <AlertDescription>{loadError}</AlertDescription>
        </Alert>
      </div>
    );
  }

  if (!podcast) {
    return (
      <div className="flex items-center justify-center gap-2 py-8 text-sm text-muted-foreground">
        <Loader2 className="h-4 w-4 animate-spin" /> Loading…
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-2xl space-y-4">
      <div className="flex items-center justify-between gap-2">
        <Link to="/" className={buttonClasses('ghost', 'sm', '-ml-2')}>
          <ArrowLeft className="h-4 w-4" /> Back
        </Link>
        <Button
          variant="ghost"
          size="sm"
          className="text-muted-foreground hover:text-destructive"
          onClick={() => void handleDelete()}
          disabled={deleting}
        >
          {deleting ? <Loader2 className="h-4 w-4 animate-spin" /> : <Trash2 className="h-4 w-4" />}
          Delete
        </Button>
      </div>

      <Card>
        <CardHeader>
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0 space-y-1">
              <CardTitle className="text-lg">{podcast.title}</CardTitle>
              <CardDescription className="truncate">
                {podcast.genieSpace.name} · {playable.length}/{podcast.segments.length} ready
              </CardDescription>
              {podcast.genieUrl && (
                <a
                  href={podcast.genieUrl}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex items-center gap-1 text-xs font-medium text-primary hover:underline"
                >
                  <ExternalLink className="h-3 w-3" /> Open conversation in Genie
                </a>
              )}
            </div>
            {podcast.status === 'generating' && (
              <Badge variant="outline">
                <Loader2 className="h-3 w-3 animate-spin" /> Generating
              </Badge>
            )}
            {podcast.status === 'error' && <Badge variant="destructive">Error</Badge>}
          </div>
        </CardHeader>
        <CardContent className="space-y-4">
          {/* Player controls */}
          <div className="flex flex-wrap items-center gap-2">
            {!player.isPlaying && !player.isPaused && (
              <Button
                onClick={() => player.play(podcast.id, playableIndices, voice)}
                disabled={!canPlay || player.isLoading}
              >
                {player.isLoading ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <Play className="h-4 w-4" />
                )}
                Play
              </Button>
            )}
            {player.isPlaying && (
              <Button onClick={player.pause} variant="secondary">
                <Pause className="h-4 w-4" /> Pause
              </Button>
            )}
            {player.isPaused && (
              <Button onClick={player.resume}>
                <Play className="h-4 w-4" /> Resume
              </Button>
            )}
            {(player.isPlaying || player.isPaused) && (
              <Button onClick={player.stop} variant="outline">
                <Square className="h-4 w-4" /> Stop
              </Button>
            )}

            <div className="flex w-full items-center gap-2 sm:ml-auto sm:w-auto">
              <Volume2 className="h-4 w-4 shrink-0 text-muted-foreground" />
              <Select
                value={voice}
                onChange={(e) => changeVoice(e.target.value)}
                className="sm:w-[190px]"
                aria-label="Narration voice"
              >
                {RECOMMENDED_VOICES.map((v) => (
                  <option key={v.id} value={v.id}>
                    {v.label}
                  </option>
                ))}
              </Select>
            </div>
          </div>

          {!canPlay && podcast.status !== 'generating' && (
            <p className="text-sm text-muted-foreground">No summaries are ready to play.</p>
          )}

          {player.isLoading && (
            <p className="flex items-center gap-2 text-xs text-muted-foreground">
              <Loader2 className="h-3 w-3 animate-spin" /> Synthesizing audio with Kokoro…
            </p>
          )}

          {player.error && (
            <Alert variant="destructive">
              <AlertCircle className="h-4 w-4 shrink-0" />
              <AlertDescription>{player.error}</AlertDescription>
            </Alert>
          )}
        </CardContent>
      </Card>

      {/* Segments */}
      <div className="space-y-3">
        {podcast.segments.map((seg, i) => (
          // Segments have a fixed order for a given podcast, so the index is a stable key.
          // eslint-disable-next-line react/no-array-index-key
          <Card key={i} className={i === activeSegmentIndex ? 'ring-2 ring-primary' : undefined}>
            <CardHeader className="pb-3">
              <div className="flex items-start justify-between gap-3">
                <CardTitle className="text-sm font-medium leading-snug">
                  {i + 1}. {seg.question}
                </CardTitle>
                {seg.status === 'generating' && (
                  <Loader2 className="h-4 w-4 shrink-0 animate-spin text-muted-foreground" />
                )}
                {seg.status === 'error' && (
                  <Badge variant="destructive" className="shrink-0">
                    Failed
                  </Badge>
                )}
              </div>
            </CardHeader>
            <CardContent className="space-y-3">
              {seg.status === 'done' && (
                <p className="break-words text-sm text-foreground">{seg.summary}</p>
              )}
              {seg.status === 'done' && seg.audioStatus === 'generating' && (
                <p className="flex items-center gap-2 text-xs text-muted-foreground">
                  <Loader2 className="h-3 w-3 animate-spin" /> Preparing audio…
                </p>
              )}
              {seg.status === 'done' && seg.audioStatus === 'error' && (
                <p className="text-xs text-muted-foreground">
                  Audio couldn&apos;t be prepared ahead of time; it will be synthesized when you
                  press Play.
                </p>
              )}
              {seg.status === 'error' && <p className="text-sm text-destructive">{seg.error}</p>}
              {seg.status === 'pending' && <p className="text-sm text-muted-foreground">Waiting…</p>}

              {(seg.details || seg.sql || seg.reasoning || seg.data) && (
                <Disclosure
                  summary={
                    <>
                      Detailed analysis
                      {typeof seg.rowCount === 'number' ? ` · ${seg.rowCount} rows` : ''}
                    </>
                  }
                >
                  {seg.details && (
                    <p className="whitespace-pre-wrap break-words text-sm text-muted-foreground">
                      {seg.details}
                    </p>
                  )}

                  {seg.data && seg.data.columns.length > 0 && (
                    <div className="overflow-x-auto rounded-md border">
                      <table className="w-full text-xs">
                        <thead className="bg-muted">
                          <tr>
                            {seg.data.columns.map((c) => (
                              <th key={c} className="px-2 py-1.5 text-left font-medium">
                                {c}
                              </th>
                            ))}
                          </tr>
                        </thead>
                        <tbody>
                          {seg.data.rows.map((row, ri) => (
                            // eslint-disable-next-line react/no-array-index-key
                            <tr key={ri} className="border-t">
                              {row.map((cell, ci) => (
                                // eslint-disable-next-line react/no-array-index-key
                                <td key={ci} className="whitespace-nowrap px-2 py-1">
                                  {cell}
                                </td>
                              ))}
                            </tr>
                          ))}
                        </tbody>
                      </table>
                      {seg.data.truncated && (
                        <p className="px-2 py-1 text-[11px] text-muted-foreground">
                          Showing {seg.data.rows.length} of {seg.data.totalRows} rows.
                        </p>
                      )}
                    </div>
                  )}

                  {seg.reasoning && (
                    <div className="space-y-1">
                      <p className="text-xs font-medium text-foreground">{"Genie's reasoning"}</p>
                      <p className="whitespace-pre-wrap break-words text-xs text-muted-foreground">
                        {seg.reasoning}
                      </p>
                    </div>
                  )}

                  {seg.queryDescription && !seg.reasoning && (
                    <p className="text-xs italic text-muted-foreground">{seg.queryDescription}</p>
                  )}
                  {seg.sql && (
                    <pre className="overflow-x-auto rounded-md bg-muted p-3 text-xs">
                      <code>{seg.sql}</code>
                    </pre>
                  )}
                </Disclosure>
              )}
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  );
}
