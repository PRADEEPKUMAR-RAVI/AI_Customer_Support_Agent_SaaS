/** Knowledge source list with live ingestion-status polling (stops once all settle). */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";
import { BookOpen, RefreshCw, Trash2 } from "lucide-react";
import { toast } from "sonner";

import { ConfirmDialog } from "@/components/confirm-dialog";
import { DataTable } from "@/components/data-table";
import { EmptyState } from "@/components/empty-state";
import { StatusBadge } from "@/components/status-badge";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";

import { deleteSource, listSources, reingestSource, type SourceOut } from "./api";

const SOURCES_KEY = ["kb", "sources"] as const;

const isActive = (s: SourceOut) => s.status === "queued" || s.status === "ingesting";

const dateFmt = new Intl.DateTimeFormat(undefined, {
  month: "short",
  day: "numeric",
  year: "numeric",
});

function RowActions({ source }: { source: SourceOut }) {
  const qc = useQueryClient();
  const invalidate = () => qc.invalidateQueries({ queryKey: SOURCES_KEY });
  const del = useMutation({
    mutationFn: () => deleteSource(source.id),
    onSuccess: () => {
      toast.success("Source deleted.");
      invalidate();
    },
    onError: (e) => toast.error((e as Error).message),
  });
  const re = useMutation({
    mutationFn: () => reingestSource(source.id),
    onSuccess: () => {
      toast.success("Reingestion started.");
      invalidate();
    },
    onError: (e) => toast.error((e as Error).message),
  });
  // Don't act on a source mid-ingest; the original guard kept parity with the backend.
  const busy = source.status === "ingesting";

  return (
    <div className="flex items-center justify-center gap-1">
      <Tooltip>
        <TooltipTrigger asChild>
          <Button
            variant="ghost"
            size="icon-sm"
            aria-label={`Reingest ${source.name}`}
            disabled={busy || re.isPending}
            onClick={() => re.mutate()}
          >
            <RefreshCw className={re.isPending ? "animate-spin" : undefined} />
          </Button>
        </TooltipTrigger>
        <TooltipContent>Reingest</TooltipContent>
      </Tooltip>
      <ConfirmDialog
        title="Delete this source?"
        description={`"${source.name}" and its ${source.chunk_count.toLocaleString()} indexed chunks will be removed. This can't be undone.`}
        confirmText="Delete"
        destructive
        onConfirm={() => del.mutate()}
        trigger={
          <Button
            variant="ghost"
            size="icon-sm"
            aria-label={`Delete ${source.name}`}
            disabled={busy || del.isPending}
            className="text-muted-foreground hover:text-destructive"
          >
            <Trash2 />
          </Button>
        }
      />
    </div>
  );
}

const columns: ColumnDef<SourceOut>[] = [
  {
    accessorKey: "name",
    header: "Name",
    cell: ({ row }) => {
      const s = row.original;
      return (
        <div className="min-w-0">
          <div className="truncate font-medium">{s.name}</div>
          {s.source_url ? (
            <div className="truncate text-xs text-muted-foreground">{s.source_url}</div>
          ) : null}
        </div>
      );
    },
  },
  {
    accessorKey: "kind",
    header: "Type",
    cell: ({ row }) => (
      <Badge variant="secondary" className="font-normal capitalize">
        {row.original.kind}
      </Badge>
    ),
  },
  {
    accessorKey: "status",
    header: "Status",
    cell: ({ row }) => {
      const s = row.original;
      const badge = <StatusBadge value={s.status} />;
      if (s.status === "failed" && s.error) {
        return (
          <Tooltip>
            <TooltipTrigger asChild>
              <span className="cursor-help">{badge}</span>
            </TooltipTrigger>
            <TooltipContent className="max-w-xs">{s.error}</TooltipContent>
          </Tooltip>
        );
      }
      return badge;
    },
  },
  {
    accessorKey: "chunk_count",
    header: "Chunks",
    cell: ({ row }) => (
      <span className="tabular-nums text-muted-foreground">
        {row.original.chunk_count.toLocaleString()}
      </span>
    ),
  },
  {
    accessorKey: "created_at",
    header: "Added",
    cell: ({ row }) => (
      <span className="whitespace-nowrap tabular-nums text-muted-foreground">
        {dateFmt.format(new Date(row.original.created_at))}
      </span>
    ),
  },
  {
    id: "actions",
    header: "Actions",
    meta: { align: "center" },
    cell: ({ row }) => <RowActions source={row.original} />,
  },
];

export function SourceList() {
  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: SOURCES_KEY,
    queryFn: listSources,
    // Poll only while something is still ingesting; stop when all are ready|failed.
    refetchInterval: (query) => {
      const items = query.state.data as SourceOut[] | undefined;
      return items?.some(isActive) ? 1500 : false;
    },
  });

  return (
    <DataTable
      columns={columns}
      data={data ?? []}
      loading={isLoading}
      error={isError}
      onRetry={() => refetch()}
      empty={
        <EmptyState
          icon={BookOpen}
          title="No sources yet"
          description="Add a file, paste text, or crawl a URL to give the assistant something to answer from."
        />
      }
    />
  );
}
