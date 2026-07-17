/** FE-Tickets — list + filter/search. Mounted at `/tickets` under the console.
 *
 * Filter state (state / priority / language / tag search) is the URL search string — the
 * `useSearchParams` bag is the single source of truth, so a filtered view is shareable and
 * survives refresh/back-forward. The list is driven by `GET /api/v1/tickets`, whose only
 * free-text filter is `tag`; the search box is wired to it (debounced into the URL). */

import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";
import { Search, SearchX, X } from "lucide-react";

import type { components } from "@/api/generated/schema";
import { DataTable } from "@/components/data-table";
import { EmptyState } from "@/components/empty-state";
import { StatusBadge } from "@/components/status-badge";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { api, unwrap } from "@/lib/api";
import { usePageBanner } from "@/lib/pageBanner";

type Ticket = components["schemas"]["TicketResponse"];
type TicketPage = components["schemas"]["Page_TicketResponse_"];

const STATES: { value: string; label: string }[] = [
  { value: "new", label: "New" },
  { value: "ai_handling", label: "AI handling" },
  { value: "escalated", label: "Escalated" },
  { value: "with_agent", label: "With agent" },
  { value: "resolved", label: "Resolved" },
  { value: "closed", label: "Closed" },
  { value: "reopened", label: "Reopened" },
];

const PRIORITIES: { value: string; label: string }[] = [
  { value: "low", label: "Low" },
  { value: "normal", label: "Normal" },
  { value: "high", label: "High" },
];

const LANGUAGES: { value: string; label: string }[] = [
  { value: "en", label: "English" },
  { value: "es", label: "Spanish" },
  { value: "fr", label: "French" },
  { value: "de", label: "German" },
  { value: "pt", label: "Portuguese" },
  { value: "hi", label: "Hindi" },
  { value: "ar", label: "Arabic" },
  { value: "zh", label: "Chinese" },
  { value: "ja", label: "Japanese" },
];

const ALL = "all";

const rtf = new Intl.RelativeTimeFormat(undefined, { numeric: "auto" });

/** Best-available "last activity" moment for a ticket, as epoch ms (the list payload has no
 * explicit `updated_at`, so fall back through the lifecycle timestamps). */
function lastActivity(t: Ticket): number {
  return Date.parse(t.closed_at ?? t.resolved_at ?? t.created_at);
}

function relativeTime(ms: number): string {
  if (!Number.isFinite(ms)) return "—";
  const diff = ms - Date.now();
  const abs = Math.abs(diff);
  const MIN = 60_000;
  const HR = 60 * MIN;
  const DAY = 24 * HR;
  const WEEK = 7 * DAY;
  const MONTH = 30 * DAY;
  const YEAR = 365 * DAY;
  if (abs < MIN) return "just now";
  if (abs < HR) return rtf.format(Math.round(diff / MIN), "minute");
  if (abs < DAY) return rtf.format(Math.round(diff / HR), "hour");
  if (abs < WEEK) return rtf.format(Math.round(diff / DAY), "day");
  if (abs < MONTH) return rtf.format(Math.round(diff / WEEK), "week");
  if (abs < YEAR) return rtf.format(Math.round(diff / MONTH), "month");
  return rtf.format(Math.round(diff / YEAR), "year");
}

function humanize(v: string): string {
  return v.replace(/[_-]+/g, " ").replace(/^\w/, (c) => c.toUpperCase());
}

export function TicketsPage() {
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();

  useEffect(() => {
    usePageBanner.getState().set({
      title: "Tickets",
      subtitle: "Browse, filter, and review every conversation the assistant has opened.",
    });
    return () => usePageBanner.getState().clear();
  }, []);

  const status = searchParams.get("status") ?? "";
  const priority = searchParams.get("priority") ?? "";
  const language = searchParams.get("language") ?? "";
  const tag = searchParams.get("tag") ?? "";

  const hasFilters = Boolean(status || priority || language || tag);

  const setParam = useCallback(
    (key: string, value: string) => {
      setSearchParams(
        (prev) => {
          const next = new URLSearchParams(prev);
          if (value) next.set(key, value);
          else next.delete(key);
          return next;
        },
        { replace: true }
      );
    },
    [setSearchParams]
  );

  const clearAll = useCallback(() => {
    setSearchParams({}, { replace: true });
  }, [setSearchParams]);

  // The search box edits a local draft; it's debounced into the URL (which drives the query).
  const [searchDraft, setSearchDraft] = useState(tag);
  // Reflect external URL changes (browser back/forward, "Clear all") back into the input.
  useEffect(() => {
    setSearchDraft(tag);
  }, [tag]);
  useEffect(() => {
    const trimmed = searchDraft.trim();
    if (trimmed === tag) return;
    const timer = setTimeout(() => setParam("tag", trimmed), 300);
    return () => clearTimeout(timer);
  }, [searchDraft, tag, setParam]);

  const languageOptions = useMemo(() => {
    if (language && !LANGUAGES.some((l) => l.value === language)) {
      return [...LANGUAGES, { value: language, label: language.toUpperCase() }];
    }
    return LANGUAGES;
  }, [language]);

  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ["tickets", { status, priority, language, tag }],
    queryFn: async () =>
      unwrap<TicketPage>(
        await api.GET("/api/v1/tickets", {
          params: {
            query: {
              status: status || undefined,
              priority: priority || undefined,
              language: language || undefined,
              tag: tag || undefined,
            },
          },
        })
      ),
  });

  const columns = useMemo<ColumnDef<Ticket>[]>(
    () => [
      {
        accessorKey: "id",
        header: "ID",
        enableSorting: false,
        cell: ({ row }) => (
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              navigate(`/tickets/${row.original.id}`);
            }}
            title={row.original.id}
            className="rounded font-mono text-xs tabular-nums text-muted-foreground hover:text-foreground hover:underline focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
          >
            #{row.original.id.slice(0, 8)}
          </button>
        ),
      },
      {
        id: "subject",
        header: "Customer",
        enableSorting: false,
        cell: ({ row }) => {
          const t = row.original;
          const primary = t.contact_email ?? "Anonymous visitor";
          const record = t.linked_record_type
            ? `${humanize(t.linked_record_type)} · ${t.linked_record_key ?? "—"}`
            : "No linked record";
          return (
            <div className="flex min-w-0 max-w-[22rem] flex-col gap-0.5">
              <span className="truncate font-medium text-foreground">{primary}</span>
              <span className="truncate text-xs text-muted-foreground">{record}</span>
            </div>
          );
        },
      },
      {
        id: "tags",
        header: "Tags",
        enableSorting: false,
        cell: ({ row }) => {
          const t = row.original.tags;
          if (!t.length) return <span className="text-xs text-muted-foreground">—</span>;
          return (
            <div className="flex max-w-[14rem] flex-wrap gap-1">
              {t.map((tg) => (
                <Badge key={tg.name} variant="secondary">
                  {tg.name}
                </Badge>
              ))}
            </div>
          );
        },
      },
      {
        accessorKey: "state",
        header: "State",
        cell: ({ row }) => <StatusBadge value={row.original.state} />,
      },
      {
        accessorKey: "priority",
        header: "Priority",
        cell: ({ row }) => <StatusBadge value={row.original.priority} />,
      },
      {
        accessorKey: "language",
        header: "Language",
        enableSorting: false,
        cell: ({ row }) => (
          <span className="text-sm text-muted-foreground uppercase tabular-nums">
            {row.original.language ?? "—"}
          </span>
        ),
      },
      {
        id: "updated",
        header: "Updated",
        accessorFn: (t) => lastActivity(t),
        sortingFn: "basic",
        cell: ({ row }) => {
          const ms = lastActivity(row.original);
          return (
            <span
              className="tabular-nums text-sm text-muted-foreground"
              title={Number.isFinite(ms) ? new Date(ms).toLocaleString() : undefined}
            >
              {relativeTime(ms)}
            </span>
          );
        },
      },
    ],
    [navigate]
  );

  const emptyNode = hasFilters ? (
    <EmptyState
      icon={SearchX}
      title="No matching tickets"
      description="No tickets match the current filters. Try broadening or clearing them."
      action={
        <Button variant="outline" size="sm" onClick={clearAll}>
          Clear filters
        </Button>
      }
      className="border-0 bg-transparent"
    />
  ) : (
    <EmptyState
      title="No tickets yet"
      description="Conversations turn into tickets the moment a customer starts chatting with your assistant."
      className="border-0 bg-transparent"
    />
  );

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-3 md:flex-row md:items-center">
        <div className="relative w-full md:max-w-xs">
          <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={searchDraft}
            onChange={(e) => setSearchDraft(e.target.value)}
            placeholder="Filter by tag"
            aria-label="Filter tickets by tag"
            className="pl-9"
          />
        </div>

        <div className="flex flex-wrap items-center gap-2 md:ml-auto">
          <Select
            value={status || ALL}
            onValueChange={(v) => setParam("status", v === ALL ? "" : v)}
          >
            <SelectTrigger aria-label="Filter by state" className="w-[150px]">
              <SelectValue placeholder="State" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={ALL}>All states</SelectItem>
              {STATES.map((s) => (
                <SelectItem key={s.value} value={s.value}>
                  {s.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>

          <Select
            value={priority || ALL}
            onValueChange={(v) => setParam("priority", v === ALL ? "" : v)}
          >
            <SelectTrigger aria-label="Filter by priority" className="w-[140px]">
              <SelectValue placeholder="Priority" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={ALL}>All priorities</SelectItem>
              {PRIORITIES.map((p) => (
                <SelectItem key={p.value} value={p.value}>
                  {p.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>

          <Select
            value={language || ALL}
            onValueChange={(v) => setParam("language", v === ALL ? "" : v)}
          >
            <SelectTrigger aria-label="Filter by language" className="w-[150px]">
              <SelectValue placeholder="Language" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={ALL}>All languages</SelectItem>
              {languageOptions.map((l) => (
                <SelectItem key={l.value} value={l.value}>
                  {l.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>

          {hasFilters ? (
            <Button variant="ghost" size="sm" onClick={clearAll}>
              <X className="size-4" />
              Clear
            </Button>
          ) : null}
        </div>
      </div>

      <p className="text-sm font-semibold text-muted-foreground tabular-nums" aria-live="polite">
        {isLoading
          ? "Loading tickets…"
          : data
            ? `${data.total} ${data.total === 1 ? "ticket" : "tickets"}`
            : ""}
      </p>

      <DataTable
        columns={columns}
        data={data?.items ?? []}
        loading={isLoading}
        error={isError}
        onRetry={() => void refetch()}
        onRowClick={(t) => navigate(`/tickets/${t.id}`)}
        empty={emptyNode}
      />
    </div>
  );
}
