/** FE-Overview — the console home/dashboard. A friendly greeting, a KPI row over
 * `/analytics/*`, a compact "recent conversations" table over `/tickets`, and a getting-started
 * checklist for admins. Every data source degrades gracefully to em-dashes / empty states so the
 * page always renders, even when analytics or tickets are unavailable or the role can't read them. */

import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";
import {
  AlertTriangle,
  ArrowRight,
  BarChart3,
  BookOpen,
  CircleDollarSign,
  Database,
  MessagesSquare,
  type LucideIcon,
  SlidersHorizontal,
  Sparkles,
  TerminalSquare,
  Ticket,
} from "lucide-react";
import { Link, useNavigate } from "react-router-dom";

import type { components } from "@/api/generated/schema";
import { DataTable } from "@/components/data-table";
import { EmptyState } from "@/components/empty-state";
import { PageHeader } from "@/components/page-header";
import { StatTile } from "@/components/stat-tile";
import { StatusBadge } from "@/components/status-badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { api, unwrap } from "@/lib/api";
import { hasPermission } from "@/lib/rbac";

import { useAuth } from "../../app/providers";

type AnalyticsOverview = components["schemas"]["AnalyticsOverview"];
type CostStats = components["schemas"]["CostStats"];
type TicketResponse = components["schemas"]["TicketResponse"];
type TicketPage = components["schemas"]["Page_TicketResponse_"];

const RECENT_LIMIT = 6;

function greetingForHour(hour: number): string {
  if (hour < 12) return "Good morning";
  if (hour < 18) return "Good afternoon";
  return "Good evening";
}

/** Best-effort first name from an email local-part ("ada.lovelace@x" → "Ada"). */
function nameFromEmail(email: string | null): string {
  if (!email) return "";
  const local = email.split("@")[0]?.split(/[.+_-]/)[0] ?? "";
  if (!local) return "";
  return local.charAt(0).toUpperCase() + local.slice(1);
}

function formatUsd(value: number): string {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 2,
    maximumFractionDigits: value !== 0 && Math.abs(value) < 1 ? 4 : 2,
  }).format(value);
}

function timeAgo(iso: string): string {
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "—";
  const diffMs = then - Date.now();
  const abs = Math.abs(diffMs);
  const minute = 60_000;
  const hour = 3_600_000;
  const day = 86_400_000;
  const rtf = new Intl.RelativeTimeFormat("en", { numeric: "auto" });
  if (abs < minute) return "just now";
  if (abs < hour) return rtf.format(Math.round(diffMs / minute), "minute");
  if (abs < day) return rtf.format(Math.round(diffMs / hour), "hour");
  if (abs < 30 * day) return rtf.format(Math.round(diffMs / day), "day");
  return new Date(iso).toLocaleDateString();
}

const SETUP_STEPS: { to: string; icon: LucideIcon; title: string; description: string }[] = [
  {
    to: "/knowledge",
    icon: BookOpen,
    title: "Add knowledge sources",
    description: "Upload docs, FAQs, and URLs your agent answers from.",
  },
  {
    to: "/records",
    icon: Database,
    title: "Connect customer records",
    description: "Import orders, warranties, or appointments for lookups.",
  },
  {
    to: "/settings",
    icon: SlidersHorizontal,
    title: "Tune agent settings",
    description: "Set the persona, languages, and escalation rules.",
  },
  {
    to: "/channels",
    icon: TerminalSquare,
    title: "Embed the chat widget",
    description: "Grab your snippet and go live on your site.",
  },
];

/** Compact quick-start checklist linking to the core setup surfaces. Admin-facing. */
function GettingStarted() {
  return (
    <Card className="shadow-sm">
      <CardHeader className="border-b bg-secondary/30">
        <CardTitle>Getting started</CardTitle>
        <CardDescription>Finish setting up your AI support agent.</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-0.5 pt-6">
        {SETUP_STEPS.map((step) => (
          <Link
            key={step.to}
            to={step.to}
            className="group -mx-2 flex items-start gap-3 rounded-lg p-2.5 transition-colors hover:bg-accent focus-visible:bg-accent focus-visible:outline-none"
          >
            <span className="mt-0.5 grid size-8 shrink-0 place-items-center rounded-lg bg-ai-accent/12 text-ai-accent transition-colors group-hover:bg-ai-accent/20">
              <step.icon className="size-4" />
            </span>
            <span className="min-w-0 flex-1">
              <span className="flex items-center gap-1.5 text-sm font-medium">
                {step.title}
                <ArrowRight className="size-3.5 -translate-x-1 opacity-0 transition-all group-hover:translate-x-0 group-hover:opacity-60" />
              </span>
              <span className="mt-0.5 block text-xs text-muted-foreground">{step.description}</span>
            </span>
          </Link>
        ))}
      </CardContent>
    </Card>
  );
}

export function OverviewPage() {
  const navigate = useNavigate();
  const { role, email } = useAuth();

  const canAnalytics = hasPermission(role, "analytics:read");
  const canTickets = hasPermission(role, "tickets:read");
  const canManage = hasPermission(role, "settings:manage");

  const greeting = useMemo(() => {
    const name = nameFromEmail(email);
    const hello = greetingForHour(new Date().getHours());
    return `${hello}${name ? `, ${name}` : ""}. Here's how your support desk is doing.`;
  }, [email]);

  const overviewQ = useQuery({
    queryKey: ["overview", "analytics-overview"],
    enabled: canAnalytics,
    retry: false,
    queryFn: async () =>
      unwrap<AnalyticsOverview>(await api.GET("/api/v1/analytics/overview", {})),
  });

  const costQ = useQuery({
    queryKey: ["overview", "analytics-cost"],
    enabled: canAnalytics,
    retry: false,
    queryFn: async () => unwrap<CostStats>(await api.GET("/api/v1/analytics/cost", {})),
  });

  const escalationsQ = useQuery({
    queryKey: ["overview", "escalations-count"],
    enabled: canTickets,
    retry: false,
    queryFn: async () =>
      unwrap<TicketPage>(
        await api.GET("/api/v1/tickets", {
          params: { query: { status: "escalated", limit: 1 } },
        })
      ),
  });

  const recentQ = useQuery({
    queryKey: ["overview", "recent-tickets"],
    enabled: canTickets,
    queryFn: async () =>
      unwrap<TicketPage>(
        await api.GET("/api/v1/tickets", {
          params: { query: { limit: RECENT_LIMIT } },
        })
      ),
  });

  const overview = overviewQ.data;
  const cost = costQ.data;

  const conversationsValue = overview ? overview.volume.toLocaleString() : null;
  const conversationsHint = overview
    ? `${overview.turns.toLocaleString()} turns handled`
    : "Awaiting first conversation";

  const autoResolvedValue = overview
    ? `${Math.round((overview.autonomous_resolution_rate ?? 0) * 100)}%`
    : null;

  const escalationsValue = canTickets
    ? escalationsQ.data
      ? escalationsQ.data.total.toLocaleString()
      : null
    : null;

  const costValue = cost ? formatUsd(cost.total_cost_usd) : null;
  const costHint = cost
    ? `${formatUsd(cost.cost_per_conversation)} per conversation`
    : "No spend recorded yet";

  const columns = useMemo<ColumnDef<TicketResponse>[]>(
    () => [
      {
        accessorKey: "id",
        header: "Conversation",
        enableSorting: false,
        cell: ({ row }) => {
          const t = row.original;
          const subtitle =
            t.linked_record_key ??
            t.contact_email ??
            t.linked_record_type ??
            "Anonymous visitor";
          return (
            <div className="flex min-w-0 flex-col gap-0.5">
              <span className="font-medium tabular-nums">#{t.id.slice(0, 8)}</span>
              <span className="max-w-[220px] truncate text-xs text-muted-foreground">
                {subtitle}
              </span>
            </div>
          );
        },
      },
      {
        accessorKey: "state",
        header: "Status",
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
          <span className="text-sm text-muted-foreground uppercase">
            {row.original.language ?? "—"}
          </span>
        ),
      },
      {
        accessorKey: "created_at",
        header: "Created",
        cell: ({ row }) => (
          <span className="whitespace-nowrap text-sm text-muted-foreground tabular-nums">
            {timeAgo(row.original.created_at)}
          </span>
        ),
      },
    ],
    []
  );

  return (
    <>
      <PageHeader
        title="Overview"
        description={greeting}
        actions={
          <>
            {canTickets ? (
              <Button variant="outline" asChild>
                <Link to="/tickets">
                  <Ticket />
                  Tickets
                </Link>
              </Button>
            ) : null}
            {canAnalytics ? (
              <Button asChild>
                <Link to="/analytics">
                  <BarChart3 />
                  Analytics
                </Link>
              </Button>
            ) : null}
          </>
        }
      />

      <div className="space-y-6">
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <StatTile
            icon={MessagesSquare}
            label="Conversations"
            value={conversationsValue ?? "—"}
            hint={conversationsHint}
            loading={canAnalytics && overviewQ.isLoading}
            tone="info"
          />
          <StatTile
            icon={Sparkles}
            label="Auto-resolved"
            value={autoResolvedValue ?? "—"}
            hint="Resolved without a human"
            loading={canAnalytics && overviewQ.isLoading}
            tone="ai"
          />
          <StatTile
            icon={AlertTriangle}
            label="Open escalations"
            value={escalationsValue ?? "—"}
            hint="Awaiting a human agent"
            loading={canTickets && escalationsQ.isLoading}
            alert={!!escalationsValue && escalationsValue !== "0"}
          />
          <StatTile
            icon={CircleDollarSign}
            label="Total cost"
            value={costValue ?? "—"}
            hint={costHint}
            loading={canAnalytics && costQ.isLoading}
            tone="success"
          />
        </div>

        <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
          <section className="space-y-4 lg:col-span-2">
            <div className="flex items-end justify-between gap-4">
              <div className="space-y-1">
                <h2 className="text-lg font-semibold tracking-tight">Recent conversations</h2>
                <p className="text-sm text-muted-foreground">
                  The latest tickets across every channel.
                </p>
              </div>
              {canTickets ? (
                <Button variant="ghost" size="sm" asChild>
                  <Link to="/tickets" className="text-muted-foreground hover:text-foreground">
                    View all
                    <ArrowRight className="size-3.5" />
                  </Link>
                </Button>
              ) : null}
            </div>
            <DataTable
              columns={columns}
              data={recentQ.data?.items ?? []}
              loading={canTickets && recentQ.isLoading}
              error={recentQ.isError}
              onRetry={() => void recentQ.refetch()}
              onRowClick={(t) => navigate(`/tickets/${t.id}`)}
              skeletonRows={RECENT_LIMIT}
              empty={
                <EmptyState
                  icon={MessagesSquare}
                  title={canTickets ? "No conversations yet" : "Nothing to show"}
                  description={
                    canTickets
                      ? "When customers start chatting, their tickets will appear here."
                      : "Your role doesn't have access to conversations."
                  }
                />
              }
            />
          </section>

          {canManage ? <GettingStarted /> : null}
        </div>
      </div>
    </>
  );
}
