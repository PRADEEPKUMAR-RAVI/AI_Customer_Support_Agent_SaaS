/** FE-Analytics: tenant dashboard over turn_metric — KPI row + volume/resolution, escalation-reason,
 * language, and top-tag charts, all with a date-range control. Charts theme via the CSS-var chart
 * tokens so light/dark work. Empty/unavailable states are handled per card. */

import type { ReactNode } from "react";
import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  LabelList,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { Bot, Coins, Languages, MessagesSquare, ShieldAlert, Tags, Timer } from "lucide-react";

import { EmptyState } from "@/components/empty-state";
import { ErrorState } from "@/components/error-state";
import { NoAccessState } from "@/components/no-access-state";
import { StatTile } from "@/components/stat-tile";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { usePageBanner } from "@/lib/pageBanner";
import { CHART_CHROME, CHART_COLORS, ESCALATION_REASON_COLOR } from "@/styles/tokens";
import { cn } from "@/lib/utils";

import { useAuth } from "../../app/providers";
import { hasPermission } from "../../lib/rbac";
import { getCost, getLatency, getOverview, getTags } from "./api";

// ---------------------------------------------------------------------------
// Date-range presets → the from_date/to_date the endpoints already accept.
// ---------------------------------------------------------------------------
type Preset = "7d" | "30d" | "90d" | "all";

const PRESET_LABEL: Record<Preset, string> = {
  "7d": "Last 7 days",
  "30d": "Last 30 days",
  "90d": "Last 90 days",
  all: "All time",
};

const isoDate = (d: Date) =>
  `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;

function rangeForPreset(preset: Preset): { from: string; to: string } {
  if (preset === "all") return { from: "", to: "" };
  const days = preset === "7d" ? 7 : preset === "30d" ? 30 : 90;
  const to = new Date();
  const from = new Date();
  from.setDate(to.getDate() - (days - 1));
  return { from: isoDate(from), to: isoDate(to) };
}

// ---------------------------------------------------------------------------
// Small data helpers
// ---------------------------------------------------------------------------
type Slice = { key: string; label: string; value: number };

const humanize = (key: string) =>
  key.replace(/[_-]+/g, " ").replace(/^\w/, (c) => c.toUpperCase());

/** Sort a `{name: count}` map desc; optionally bucket the tail into "Other". */
function toSlices(map: Record<string, number> | undefined, limit?: number): Slice[] {
  const rows = Object.entries(map ?? {})
    .filter(([, v]) => v > 0)
    .sort((a, b) => b[1] - a[1])
    .map(([key, value]) => ({ key, label: humanize(key), value }));
  if (!limit || rows.length <= limit) return rows;
  const head = rows.slice(0, limit - 1);
  const tail = rows.slice(limit - 1);
  const other = tail.reduce((sum, r) => sum + r.value, 0);
  return [...head, { key: "__other__", label: "Other", value: other }];
}

// ---------------------------------------------------------------------------
// Token-styled tooltip (no vendor default white box)
// ---------------------------------------------------------------------------
interface TipEntry {
  name?: string;
  value?: number | string;
}
function ChartTooltip({
  active,
  payload,
  label,
}: {
  active?: boolean;
  payload?: TipEntry[];
  label?: string;
}) {
  if (!active || !payload?.length) return null;
  return (
    <div className="min-w-32 rounded-md border bg-popover px-3 py-2 text-xs shadow-md">
      {label ? <div className="mb-1 font-medium text-popover-foreground">{label}</div> : null}
      <div className="space-y-0.5">
        {payload.map((entry, i) => (
          <div key={i} className="flex items-center justify-between gap-4">
            <span className="text-muted-foreground">{entry.name}</span>
            <span className="font-medium text-foreground tabular-nums">
              {typeof entry.value === "number" ? entry.value.toLocaleString() : entry.value}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

const AXIS_TICK = { fill: CHART_CHROME.axis, fontSize: 12 } as const;

// ---------------------------------------------------------------------------
// Chart shell — title/description + fixed-height body with loading/empty/error
// ---------------------------------------------------------------------------
function ChartCard({
  title,
  description,
  children,
  className,
}: {
  title: string;
  description?: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <Card className={cn("gap-4", className)}>
      <CardHeader>
        <CardTitle className="text-base">{title}</CardTitle>
        {description ? <CardDescription>{description}</CardDescription> : null}
      </CardHeader>
      <CardContent>{children}</CardContent>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------
export function AnalyticsPage() {
  const { role } = useAuth();
  const [preset, setPreset] = useState<Preset>("all");
  const range = useMemo(() => rangeForPreset(preset), [preset]);
  const keyBase = [range.from, range.to] as const;

  const overviewQ = useQuery({
    queryKey: ["analytics", "overview", ...keyBase],
    queryFn: () => getOverview(range),
  });
  const latencyQ = useQuery({
    queryKey: ["analytics", "latency", ...keyBase],
    queryFn: () => getLatency(range),
  });
  const costQ = useQuery({
    queryKey: ["analytics", "cost", ...keyBase],
    queryFn: () => getCost(range),
  });
  const tagsQ = useQuery({
    queryKey: ["analytics", "tags", ...keyBase],
    queryFn: () => getTags(range),
  });

  const rangeControl = (
    <Select value={preset} onValueChange={(v) => setPreset(v as Preset)}>
      <SelectTrigger className="w-[160px]" aria-label="Date range">
        <SelectValue />
      </SelectTrigger>
      <SelectContent align="end">
        {(Object.keys(PRESET_LABEL) as Preset[]).map((p) => (
          <SelectItem key={p} value={p}>
            {PRESET_LABEL[p]}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );

  const canRead = !role || hasPermission(role, "analytics:read");

  useEffect(() => {
    usePageBanner.getState().set({
      title: "Analytics",
      subtitle: canRead
        ? "How autonomously the assistant resolves conversations, and what it costs."
        : "Resolution, latency, and cost for your account.",
    });
    return () => usePageBanner.getState().clear();
  }, [canRead]);

  if (role && !hasPermission(role, "analytics:read")) {
    return (
      <div className="space-y-6">
        <NoAccessState description="Your role doesn't include the analytics:read permission. Ask an admin if you need it." />
      </div>
    );
  }

  const ov = overviewQ.data;
  const lat = latencyQ.data;
  const cost = costQ.data;

  const resolvedPct = ov ? Math.round((ov.autonomous_resolution_rate ?? 0) * 100) : 0;
  const resolvedCount = ov ? Math.round(ov.volume * (ov.autonomous_resolution_rate ?? 0)) : 0;
  const escalatedCount = ov ? Math.max(ov.volume - resolvedCount, 0) : 0;
  const turnsPerConv = ov && ov.volume > 0 ? (ov.turns / ov.volume).toFixed(1) : "0.0";

  const escalationSlices = toSlices(ov?.escalation_reasons);
  const languageSlices = toSlices(ov?.language_distribution, 7).map((s) => ({
    ...s,
    label: s.key === "__other__" ? "Other" : s.key.toUpperCase(),
  }));
  const tagSlices = toSlices(tagsQ.data?.tags, 10);

  return (
    <div className="space-y-6">
      <div className="flex justify-end">{rangeControl}</div>

      {/* KPI row */}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <StatTile
          label="Conversations"
          value={ov ? ov.volume.toLocaleString() : "—"}
          hint={ov ? `${ov.turns.toLocaleString()} turns · ${turnsPerConv} per conversation` : undefined}
          icon={MessagesSquare}
          loading={overviewQ.isLoading}
        />
        <StatTile
          label="Autonomous resolution"
          value={`${resolvedPct}%`}
          hint={ov ? `${resolvedCount.toLocaleString()} of ${ov.volume.toLocaleString()} resolved by AI` : undefined}
          icon={Bot}
          loading={overviewQ.isLoading}
        />
        <StatTile
          label="Latency p95"
          value={lat?.p95_ms != null ? `${lat.p95_ms.toLocaleString()} ms` : "—"}
          hint={lat ? `p50 ${lat.p50_ms != null ? `${lat.p50_ms.toLocaleString()} ms` : "—"} · ${lat.count.toLocaleString()} turns` : undefined}
          icon={Timer}
          loading={latencyQ.isLoading}
        />
        <StatTile
          label="Cost / conversation"
          value={cost ? `$${(cost.cost_per_conversation ?? 0).toFixed(4)}` : "—"}
          hint={cost ? `$${(cost.total_cost_usd ?? 0).toFixed(2)} total spend` : undefined}
          icon={Coins}
          loading={costQ.isLoading}
        />
      </div>

      {/* Volume & resolution mix */}
      <ChartCard
        title="Conversation volume"
        description="Total conversations in range, split by how they were resolved."
      >
        {overviewQ.isLoading ? (
          <Skeleton className="h-20 w-full" />
        ) : overviewQ.isError ? (
          <ErrorState
            title="Couldn't load volume"
            message="The overview request failed. Try again."
            onRetry={() => void overviewQ.refetch()}
          />
        ) : !ov || ov.volume === 0 ? (
          <EmptyState
            icon={MessagesSquare}
            title="No conversations yet"
            description="Once customers start chatting in this range, volume and resolution appear here."
          />
        ) : (
          <div className="space-y-4">
            <div className="flex items-baseline gap-2">
              <span className="text-4xl font-semibold tracking-tight tabular-nums">
                {ov.volume.toLocaleString()}
              </span>
              <span className="text-sm text-muted-foreground">conversations</span>
            </div>
            <div className="h-8 w-full">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart
                  layout="vertical"
                  data={[{ name: "mix", ai: resolvedCount, escalated: escalatedCount }]}
                  margin={{ top: 0, right: 0, bottom: 0, left: 0 }}
                  barCategoryGap={0}
                >
                  <XAxis type="number" hide domain={[0, ov.volume]} />
                  <YAxis type="category" dataKey="name" hide />
                  <Tooltip cursor={false} content={<ChartTooltip />} />
                  <Bar dataKey="ai" name="Resolved by AI" stackId="mix" fill="var(--color-chart-2)" radius={[4, 0, 0, 4]} />
                  <Bar
                    dataKey="escalated"
                    name="Escalated / handed off"
                    stackId="mix"
                    fill="var(--color-muted-foreground)"
                    radius={[0, 4, 4, 0]}
                  />
                </BarChart>
              </ResponsiveContainer>
            </div>
            <div className="flex flex-wrap gap-x-6 gap-y-2 text-sm">
              <LegendItem dotClass="bg-chart-2" label="Resolved by AI" value={resolvedCount} />
              <LegendItem
                dotClass="bg-muted-foreground"
                label="Escalated / handed off"
                value={escalatedCount}
              />
            </div>
          </div>
        )}
      </ChartCard>

      {/* Escalation + language */}
      <div className="grid gap-6 lg:grid-cols-2">
        <ChartCard title="Escalation reasons" description="Why conversations left the AI in this range.">
          {overviewQ.isLoading ? (
            <Skeleton className="h-64 w-full" />
          ) : overviewQ.isError ? (
            <ErrorState
              message="Couldn't load escalation reasons."
              onRetry={() => void overviewQ.refetch()}
            />
          ) : escalationSlices.length === 0 ? (
            <EmptyState
              icon={ShieldAlert}
              title="No escalations"
              description="Nothing was handed off to a human in this range."
            />
          ) : (
            <div className="h-64 w-full">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={escalationSlices} margin={{ top: 8, right: 8, bottom: 0, left: -16 }}>
                  <CartesianGrid vertical={false} stroke={CHART_CHROME.grid} strokeDasharray="3 3" />
                  <XAxis
                    dataKey="label"
                    tick={AXIS_TICK}
                    tickLine={false}
                    axisLine={false}
                    interval={0}
                  />
                  <YAxis allowDecimals={false} tick={AXIS_TICK} tickLine={false} axisLine={false} width={40} />
                  <Tooltip cursor={{ fill: "var(--color-muted)", opacity: 0.4 }} content={<ChartTooltip />} />
                  <Bar dataKey="value" name="Conversations" radius={[4, 4, 0, 0]} maxBarSize={56}>
                    {escalationSlices.map((s, i) => (
                      <Cell
                        key={s.key}
                        fill={ESCALATION_REASON_COLOR[s.key] ?? CHART_COLORS[i % CHART_COLORS.length]}
                      />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}
        </ChartCard>

        <ChartCard title="Language distribution" description="Detected customer language across conversations.">
          {overviewQ.isLoading ? (
            <Skeleton className="h-64 w-full" />
          ) : overviewQ.isError ? (
            <ErrorState message="Couldn't load languages." onRetry={() => void overviewQ.refetch()} />
          ) : languageSlices.length === 0 ? (
            <EmptyState
              icon={Languages}
              title="No language data"
              description="Language is recorded per turn once conversations come in."
            />
          ) : (
            <div className="h-64 w-full">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart
                  layout="vertical"
                  data={languageSlices}
                  margin={{ top: 4, right: 24, bottom: 4, left: 8 }}
                >
                  <CartesianGrid horizontal={false} stroke={CHART_CHROME.grid} strokeDasharray="3 3" />
                  <XAxis type="number" allowDecimals={false} tick={AXIS_TICK} tickLine={false} axisLine={false} />
                  <YAxis
                    type="category"
                    dataKey="label"
                    tick={AXIS_TICK}
                    tickLine={false}
                    axisLine={false}
                    width={56}
                  />
                  <Tooltip cursor={{ fill: "var(--color-muted)", opacity: 0.4 }} content={<ChartTooltip />} />
                  <Bar dataKey="value" name="Conversations" radius={[0, 4, 4, 0]} maxBarSize={28}>
                    {languageSlices.map((s, i) => (
                      <Cell key={s.key} fill={CHART_COLORS[i % CHART_COLORS.length]} />
                    ))}
                    <LabelList
                      dataKey="value"
                      position="right"
                      className="fill-muted-foreground text-xs tabular-nums"
                    />
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}
        </ChartCard>
      </div>

      {/* Top tags */}
      <ChartCard title="Top tags" description="Most common topics the AI tagged on conversations.">
        {tagsQ.isLoading ? (
          <Skeleton className="h-56 w-full" />
        ) : tagsQ.isError ? (
          <ErrorState message="Couldn't load tags." onRetry={() => void tagsQ.refetch()} />
        ) : tagSlices.length === 0 ? (
          <EmptyState
            icon={Tags}
            title="No tags yet"
            description={
              tagsQ.data?.note ?? "Tags appear here as the assistant classifies incoming conversations."
            }
          />
        ) : (
          <div className="h-72 w-full">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart
                layout="vertical"
                data={tagSlices}
                margin={{ top: 4, right: 32, bottom: 4, left: 8 }}
              >
                <CartesianGrid horizontal={false} stroke={CHART_CHROME.grid} strokeDasharray="3 3" />
                <XAxis type="number" allowDecimals={false} tick={AXIS_TICK} tickLine={false} axisLine={false} />
                <YAxis
                  type="category"
                  dataKey="label"
                  tick={AXIS_TICK}
                  tickLine={false}
                  axisLine={false}
                  width={140}
                />
                <Tooltip cursor={{ fill: "var(--color-muted)", opacity: 0.4 }} content={<ChartTooltip />} />
                <Bar dataKey="value" name="Conversations" fill="var(--color-chart-1)" radius={[0, 4, 4, 0]} maxBarSize={22}>
                  <LabelList
                    dataKey="value"
                    position="right"
                    className="fill-muted-foreground text-xs tabular-nums"
                  />
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        )}
      </ChartCard>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Legend chip for the volume/resolution split
// ---------------------------------------------------------------------------
function LegendItem({
  dotClass,
  label,
  value,
}: {
  dotClass: string;
  label: string;
  value: number;
}) {
  return (
    <span className="flex items-center gap-2">
      <span aria-hidden className={cn("size-2.5 shrink-0 rounded-[3px]", dotClass)} />
      <span className="text-muted-foreground">{label}</span>
      <span className="font-medium text-foreground tabular-nums">{value.toLocaleString()}</span>
    </span>
  );
}
