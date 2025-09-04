import { useState } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { Badge } from '@/components/ui/badge';
import { Input } from '@/components/ui/input';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { Search, ChevronLeft, ChevronRight } from 'lucide-react';
import { Item } from '@/types';
import { format } from 'date-fns';

interface ItemsTableProps {
  items: Item[];
  isLoading?: boolean;
}

export const ItemsTable = ({ items, isLoading }: ItemsTableProps) => {
  const [searchText, setSearchText] = useState('');
  const [sourceFilter, setSourceFilter] = useState<string>('all');
  const [currentPage, setCurrentPage] = useState(1);
  const itemsPerPage = 25;

  const getScoreBadge = (score: number) => {
    if (score <= -0.5) return { variant: 'destructive' as const, label: score.toFixed(2) };
    if (score >= 0.5) return { variant: 'success' as const, label: score.toFixed(2) };
    return { variant: 'secondary' as const, label: score.toFixed(2) };
  };

  const getImpactBadge = (v: number | null | undefined) => {
    if (v === null || v === undefined || Number.isNaN(v)) {
      return { variant: 'outline' as const, label: '—' };
    }
    const abs = Math.abs(v);
    if (abs >= 0.8) return { variant: 'success' as const, label: v.toFixed(2) };
    if (abs >= 0.4) return { variant: 'secondary' as const, label: v.toFixed(2) };
    if (abs > 0) return { variant: 'outline' as const, label: v.toFixed(2) };
    return { variant: 'outline' as const, label: '—' };
  };

  const getSourceBadge = (source: string) => {
    const variants: Record<string, 'default' | 'secondary' | 'outline'> = {
      rss: 'default',
      x: 'secondary',
      tg: 'outline',
      seed: 'outline',
    };
    return variants[source] || 'default';
  };

  const filteredItems = items.filter(item => {
    const matchesSearch = item.text.toLowerCase().includes(searchText.toLowerCase());
    const matchesSource = sourceFilter === 'all' || item.source === sourceFilter;
    return matchesSearch && matchesSource;
  });

  const totalPages = Math.ceil(filteredItems.length / itemsPerPage);
  const startIndex = (currentPage - 1) * itemsPerPage;
  const paginatedItems = filteredItems.slice(startIndex, startIndex + itemsPerPage);

  if (isLoading) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Latest Items</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="space-y-4">
            <div className="flex gap-4">
              <Skeleton className="h-10 flex-1" />
              <Skeleton className="h-10 w-32" />
            </div>
            <div className="space-y-2">
              {Array.from({ length: 5 }).map((_, i) => (
                <Skeleton key={i} className="h-12 w-full" />
              ))}
            </div>
          </div>
        </CardContent>
      </Card>
    );
  }

  const normalizeUrl = (u?: string | null): string | undefined => {
    if (!u) return undefined;
    const v = u.trim();
    if (/^https?:\/\//i.test(v)) return v;
    if (v.startsWith('//')) return 'https:' + v;
    if (/^(x\.com|twitter\.com|t\.co)\b/i.test(v)) return 'https://' + v;
    return 'https://' + v;
  };

  const SafeSourceBadge = ({ item }: { item: Item }) => {
    const variant = getSourceBadge(item.source);
    const badge = (
      <Badge variant={variant} className="uppercase tracking-wide">
        {item.source.toUpperCase()}
      </Badge>
    );

    const normalized = normalizeUrl((item as any).url);
    let href: string | undefined = normalized;
    if (!href && item.source === 'x') {
      const q = encodeURIComponent(item.text.slice(0, 80));
      href = `https://x.com/search?q=${q}`;
    }

    if (!href) return badge;

    return (
      <a
        href={href}
        target="_blank"
        rel="noopener noreferrer"
        onClick={(e) => e.stopPropagation()}
        className="inline-flex items-center cursor-pointer"
        title="Abrir fuente"
      >
        {badge}
      </a>
    );
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle>Latest Items</CardTitle>
        <div className="flex gap-4">
          <div className="relative flex-1">
            <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 h-4 w-4 text-muted-foreground" />
            <Input
              placeholder="Search items..."
              value={searchText}
              onChange={(e) => setSearchText(e.target.value)}
              className="pl-10"
            />
          </div>
          <Select value={sourceFilter} onValueChange={setSourceFilter}>
            <SelectTrigger className="w-32">
              <SelectValue placeholder="Source" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All</SelectItem>
              <SelectItem value="rss">RSS</SelectItem>
              <SelectItem value="x">X</SelectItem>
              <SelectItem value="tg">Telegram</SelectItem>
              <SelectItem value="seed">Seed</SelectItem>
            </SelectContent>
          </Select>
        </div>
      </CardHeader>
      <CardContent>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Time</TableHead>
              <TableHead>Source</TableHead>
              <TableHead>Label</TableHead>
              <TableHead>Score</TableHead>
              <TableHead title="Impacto estimado en precio a 15 min (normalizado)">Impact (15m)</TableHead>
              <TableHead>Text</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {paginatedItems.map((item, index) => {
              const impact15 = (item as any).impact as number | undefined;
              const impactMeta = (item as any).impact_meta as { norm60?: number } | undefined;
              const badge = getImpactBadge(impact15);

              return (
                <TableRow key={`${item.ts}-${index}`}>
                  <TableCell className="font-mono text-sm">
                    {format(new Date(item.ts), 'HH:mm:ss')}
                  </TableCell>
                  <TableCell>
                    <SafeSourceBadge item={item} />
                  </TableCell>
                  <TableCell className="text-sm text-muted-foreground">
                    {item.label}
                  </TableCell>
                  <TableCell>
                    <Badge variant={getScoreBadge(item.score).variant}>
                      {getScoreBadge(item.score).label}
                    </Badge>
                  </TableCell>
                  <TableCell title={impactMeta?.norm60 !== undefined ? `Impact(60m): ${impactMeta.norm60.toFixed(2)}` : ''}>
                    <Badge variant={badge.variant}>{badge.label}</Badge>
                  </TableCell>
                  <TableCell className="max-w-md truncate">
                    {item.text}
                  </TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>

        {totalPages > 1 && (
          <div className="flex items-center justify-between mt-4">
            <p className="text-sm text-muted-foreground">
              Showing {startIndex + 1}-{Math.min(startIndex + itemsPerPage, filteredItems.length)} of {filteredItems.length} items
            </p>
            <div className="flex gap-2">
              <Button
                variant="outline"
                size="sm"
                onClick={() => setCurrentPage(p => Math.max(1, p - 1))}
                disabled={currentPage === 1}
              >
                <ChevronLeft className="h-4 w-4" />
              </Button>
              <span className="flex items-center px-3 text-sm">
                {currentPage} of {totalPages}
              </span>
              <Button
                variant="outline"
                size="sm"
                onClick={() => setCurrentPage(p => Math.min(totalPages, p + 1))}
                disabled={currentPage === totalPages}
              >
                <ChevronRight className="h-4 w-4" />
              </Button>
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
};
