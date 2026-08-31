import { useEffect, useState } from 'react';
import { useNavigate, Link } from 'react-router';
import { Plus, Trash2, Loader2, AlertCircle, ArrowLeft } from 'lucide-react';
import type { GenieSpaceOption } from '@shared/types';
import { api } from '@/lib/api';
import {
  Button,
  buttonClasses,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  CardDescription,
  Input,
  Textarea,
  Label,
  Alert,
  AlertDescription,
} from '@/components/ui';

export function NewPodcastPage() {
  const navigate = useNavigate();
  const [genieSpace, setGenieSpace] = useState('');
  const [title, setTitle] = useState('');
  const [questions, setQuestions] = useState<Array<{ id: string; text: string }>>([
    { id: crypto.randomUUID(), text: '' },
  ]);
  const [spaces, setSpaces] = useState<GenieSpaceOption[]>([]);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    // Best-effort space suggestions; ignore failures (e.g. no Genie access yet).
    api
      .listSpaces()
      .then(setSpaces)
      .catch(() => {});
  }, []);

  const setQuestion = (id: string, text: string) =>
    setQuestions((qs) => qs.map((q) => (q.id === id ? { ...q, text } : q)));
  const addQuestion = () => setQuestions((qs) => [...qs, { id: crypto.randomUUID(), text: '' }]);
  const removeQuestion = (id: string) =>
    setQuestions((qs) => (qs.length === 1 ? qs : qs.filter((q) => q.id !== id)));

  const canSubmit =
    genieSpace.trim().length > 0 && questions.some((q) => q.text.trim().length > 0) && !submitting;

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      const podcast = await api.createPodcast({
        genieSpace: genieSpace.trim(),
        title: title.trim() || undefined,
        questions: questions.map((q) => q.text.trim()).filter(Boolean),
      });
      await navigate(`/podcast/${podcast.id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setSubmitting(false);
    }
  }

  return (
    <div className="mx-auto max-w-2xl space-y-4">
      <Link to="/" className={buttonClasses('ghost', 'sm', '-ml-2')}>
        <ArrowLeft className="h-4 w-4" /> Back
      </Link>

      <form onSubmit={(e) => void submit(e)}>
        <Card>
          <CardHeader>
            <CardTitle className="text-xl">New podcast</CardTitle>
            <CardDescription>
              Pick a Genie space and the questions to ask. Genie answers each one, and the podcast
              narrates the summaries.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-5">
            <div className="space-y-2">
              <Label htmlFor="space">Genie space (name or ID)</Label>
              <Input
                id="space"
                list="genie-spaces"
                placeholder="e.g. Sales Analytics or 01ef…"
                value={genieSpace}
                onChange={(e) => setGenieSpace(e.target.value)}
                required
              />
              <datalist id="genie-spaces">
                {spaces.map((s) => (
                  <option key={s.id} value={s.title}>
                    {s.id}
                  </option>
                ))}
              </datalist>
            </div>

            <div className="space-y-2">
              <Label htmlFor="title">Title (optional)</Label>
              <Input
                id="title"
                placeholder="Weekly sales roundup"
                value={title}
                onChange={(e) => setTitle(e.target.value)}
              />
            </div>

            <div className="space-y-2">
              <Label>Questions</Label>
              <div className="space-y-2">
                {questions.map((q, i) => (
                  <div key={q.id} className="flex gap-2">
                    <Textarea
                      className="min-h-[2.75rem]"
                      rows={2}
                      placeholder={`Question ${i + 1}`}
                      value={q.text}
                      onChange={(e) => setQuestion(q.id, e.target.value)}
                    />
                    <Button
                      type="button"
                      variant="ghost"
                      size="icon"
                      className="shrink-0"
                      onClick={() => removeQuestion(q.id)}
                      disabled={questions.length === 1}
                      aria-label="Remove question"
                    >
                      <Trash2 className="h-4 w-4" />
                    </Button>
                  </div>
                ))}
              </div>
              <Button type="button" variant="outline" size="sm" onClick={addQuestion}>
                <Plus className="h-4 w-4" /> Add question
              </Button>
            </div>

            {error && (
              <Alert variant="destructive">
                <AlertCircle className="h-4 w-4 shrink-0" />
                <AlertDescription>{error}</AlertDescription>
              </Alert>
            )}

            <Button type="submit" disabled={!canSubmit} className="w-full sm:w-auto">
              {submitting && <Loader2 className="h-4 w-4 animate-spin" />}
              Create podcast
            </Button>
          </CardContent>
        </Card>
      </form>
    </div>
  );
}
