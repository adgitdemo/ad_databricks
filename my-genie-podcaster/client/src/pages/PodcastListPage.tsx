import { useEffect, useState } from 'react';
import { Link } from 'react-router';
import { Plus, Mic, Loader2, AlertCircle, Trash2 } from 'lucide-react';
import type { PodcastSummary } from '@shared/types';
import { api } from '@/lib/api';
import {
  Button,
  buttonClasses,
  Card,
  CardDescription,
  CardHeader,
  CardTitle,
  CardContent,
  Badge,
  Alert,
  AlertDescription,
} from '@/components/ui';

function StatusBadge({ status }: { status: PodcastSummary['status'] }) {
  if (status === 'ready') return <Badge variant="secondary">Ready</Badge>;
  if (status === 'error') return <Badge variant="destructive">Error</Badge>;
  return (
    <Badge variant="outline">
      <Loader2 className="h-3 w-3 animate-spin" /> Generating
    </Badge>
  );
}

export function PodcastListPage() {
  const [podcasts, setPodcasts] = useState<PodcastSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    api
      .listPodcasts()
      .then((p) => active && setPodcasts(p))
      .catch((e: unknown) => active && setError(e instanceof Error ? e.message : String(e)));
    return () => {
      active = false;
    };
  }, []);

  // The card is a link; stop the click from navigating, confirm, then delete.
  async function handleDelete(e: React.MouseEvent, id: string, title: string) {
    e.preventDefault();
    e.stopPropagation();
    if (!window.confirm(`Delete “${title}”? This permanently removes the podcast and its audio.`)) {
      return;
    }
    setDeletingId(id);
    setError(null);
    try {
      await api.deletePodcast(id);
      setPodcasts((cur) => cur?.filter((p) => p.id !== id) ?? cur);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setDeletingId(null);
    }
  }

  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <div className="flex items-center justify-between gap-3">
        <div className="min-w-0">
          <h2 className="text-2xl font-bold text-foreground">Your podcasts</h2>
          <p className="text-sm text-muted-foreground">Turn Genie answers into a spoken podcast.</p>
        </div>
        <Link to="/new" className={buttonClasses('default', 'default', 'shrink-0')}>
          <Plus className="h-4 w-4" /> New
        </Link>
      </div>

      {error && (
        <Alert variant="destructive">
          <AlertCircle className="h-4 w-4 shrink-0" />
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}

      {podcasts === null && !error && (
        <div className="flex items-center justify-center gap-2 py-8 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" /> Loading…
        </div>
      )}

      {podcasts?.length === 0 && (
        <Card>
          <CardContent className="flex flex-col items-center gap-3 py-12 text-center">
            <Mic className="h-10 w-10 text-muted-foreground" />
            <p className="text-muted-foreground">No podcasts yet.</p>
            <Link to="/new" className={buttonClasses('secondary')}>
              Create your first podcast
            </Link>
          </CardContent>
        </Card>
      )}

      <div className="space-y-3">
        {podcasts?.map((p) => (
          <Link key={p.id} to={`/podcast/${p.id}`} className="block">
            <Card className="transition-colors hover:bg-muted/50">
              <CardHeader className="flex-row items-center justify-between gap-2 space-y-0">
                <div className="min-w-0 space-y-1">
                  <CardTitle className="truncate text-base">{p.title}</CardTitle>
                  <CardDescription className="truncate">
                    {p.genieSpace.name} · {p.doneCount}/{p.questionCount} answered
                  </CardDescription>
                </div>
                <div className="flex shrink-0 items-center gap-1">
                  <StatusBadge status={p.status} />
                  <Button
                    variant="ghost"
                    size="icon"
                    className="text-muted-foreground hover:text-destructive"
                    aria-label={`Delete ${p.title}`}
                    disabled={deletingId === p.id}
                    onClick={(e) => void handleDelete(e, p.id, p.title)}
                  >
                    {deletingId === p.id ? (
                      <Loader2 className="h-4 w-4 animate-spin" />
                    ) : (
                      <Trash2 className="h-4 w-4" />
                    )}
                  </Button>
                </div>
              </CardHeader>
            </Card>
          </Link>
        ))}
      </div>
    </div>
  );
}
