import { useEffect, useMemo, useRef, useState } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { apiService } from '@/api/service';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

type SummaryRes = { commentary: string; generated_at?: string; model?: string };

export const Commentary = ({ refreshSeconds = 60 }: { refreshSeconds?: number }) => {
  const [text, setText] = useState('');
  const [meta, setMeta] = useState<{ generated_at?: string; model?: string }>({});
  const [loading, setLoading] = useState(false);
  const [autoRefresh, setAutoRefresh] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const ctrlRef = useRef<AbortController | null>(null);

  const load = async () => {
    if (loading) return;
    setLoading(true);
    setError(null);
    ctrlRef.current?.abort();
    const ctrl = new AbortController();
    ctrlRef.current = ctrl;
    try {
      const res: SummaryRes = await apiService.getSummary();
      if (ctrl.signal.aborted) return;
      setText(res.commentary || '');
      setMeta({ generated_at: res.generated_at, model: res.model });
    } catch (e: any) {
      if (ctrl.signal.aborted) return;
      setError('Summary not available.');
      setText('');
    } finally {
      if (!ctrl.signal.aborted) setLoading(false);
    }
  };

  useEffect(() => {
    load();
    return () => ctrlRef.current?.abort();
  }, []);

  useEffect(() => {
    if (!autoRefresh || !refreshSeconds || refreshSeconds <= 0) return;
    const id = setInterval(load, refreshSeconds * 1000);
    return () => clearInterval(id);
  }, [autoRefresh, refreshSeconds]);

  const subtitle = useMemo(() => {
    const parts: string[] = [];
    if (meta.model) parts.push(`LLM: ${meta.model}`);
    if (meta.generated_at) parts.push(new Date(meta.generated_at).toLocaleString());
    return parts.join(' · ');
  }, [meta]);

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between">
        <div className="space-y-1">
          <CardTitle>Summary</CardTitle>
          <p className="text-xs text-muted-foreground">{subtitle}</p>
        </div>
        <div className="flex items-center gap-2">
          <Button size="sm" variant={autoRefresh ? 'default' : 'secondary'} onClick={() => setAutoRefresh(v => !v)}>
            {autoRefresh ? 'Auto: ON' : 'Auto: OFF'}
          </Button>
          <Button size="sm" onClick={load} disabled={loading}>
            {loading ? 'Loading…' : 'Refresh'}
          </Button>
        </div>
      </CardHeader>
      <CardContent>
        {error ? (
          <div className="text-sm text-destructive">{error}</div>
        ) : text ? (
          <div className="prose prose-sm dark:prose-invert max-w-none whitespace-pre-wrap break-words leading-relaxed">
            <ReactMarkdown
              remarkPlugins={[remarkGfm]}
              components={{
                a: (props) => <a {...props} target="_blank" rel="noopener noreferrer" className="underline" />,
                code: (props) => {
                  const { inline, className, children, ...rest } = props as any;
                  return inline ? (
                    <code className="px-1 py-0.5 rounded bg-muted" {...rest}>{children}</code>
                  ) : (
                    <pre className="p-3 rounded bg-muted overflow-auto">
                      <code className={className} {...rest}>{children}</code>
                    </pre>
                  );
                },
                table: (props) => (
                  <div className="overflow-x-auto"><table className="min-w-full" {...props} /></div>
                ),
                p: (props) => <p className="mb-3" {...props} />,
                ul: (props) => <ul className="list-disc ml-6 mb-3" {...props} />,
                ol: (props) => <ol className="list-decimal ml-6 mb-3" {...props} />,
                blockquote: (props) => <blockquote className="border-l-2 pl-3 italic text-muted-foreground" {...props} />,
              }}
            >
              {text}
            </ReactMarkdown>
          </div>
        ) : (
          <div className="text-sm text-muted-foreground">—</div>
        )}
        {meta.generated_at && (
          <div className="text-xs text-muted-foreground mt-3">
            Last updated: {new Date(meta.generated_at).toLocaleString()}
          </div>
        )}
      </CardContent>
    </Card>
  );
};
