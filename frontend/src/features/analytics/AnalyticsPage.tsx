/** FE-Analytics: tenant dashboard over turn_metric — stat cards + escalation/language bar charts,
 * with a date range. Tags/CSAT are shown as "coming soon" (blocked on M5 tags + feedback). */

import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { useAuth } from "../../app/providers";
import { Card, Spinner } from "../../components";
import { hasPermission } from "../../lib/rbac";
import { getCost, getLatency, getOverview } from "./api";

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <Card>
      <div style={{ fontSize: 12, color: "#6b7280" }}>{label}</div>
      <div style={{ fontSize: 26, fontWeight: 600 }}>{value}</div>
    </Card>
  );
}

function DistChart({ title, data }: { title: string; data: Record<string, number> }) {
  const rows = Object.entries(data).map(([name, value]) => ({ name, value }));
  return (
    <Card>
      <h3>{title}</h3>
      {rows.length === 0 ? (
        <p style={{ color: "#6b7280" }}>No data yet.</p>
      ) : (
        <div style={{ width: "100%", height: 220 }}>
          <ResponsiveContainer>
            <BarChart data={rows}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="name" />
              <YAxis allowDecimals={false} />
              <Tooltip />
              <Bar dataKey="value" fill="#2563eb" />
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}
    </Card>
  );
}

export function AnalyticsPage() {
  const { role } = useAuth();
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const range = { from, to };

  const overviewQ = useQuery({ queryKey: ["analytics", "overview", from, to], queryFn: () => getOverview(range) });
  const latencyQ = useQuery({ queryKey: ["analytics", "latency", from, to], queryFn: () => getLatency(range) });
  const costQ = useQuery({ queryKey: ["analytics", "cost", from, to], queryFn: () => getCost(range) });

  if (role && !hasPermission(role, "analytics:read")) {
    return <Card><p>You don't have permission to view analytics.</p></Card>;
  }
  if (overviewQ.isLoading || latencyQ.isLoading || costQ.isLoading) return <Spinner />;
  if (overviewQ.isError) return <p role="alert">Failed to load analytics.</p>;

  const ov = overviewQ.data!;
  const lat = latencyQ.data!;
  const cost = costQ.data!;

  return (
    <div style={{ display: "grid", gap: 16, maxWidth: 900 }}>
      <div style={{ display: "flex", gap: 12, alignItems: "center", flexWrap: "wrap" }}>
        <h2 style={{ marginRight: "auto" }}>Analytics</h2>
        <label style={{ fontSize: 13 }}>from <input type="date" value={from} onChange={(e) => setFrom(e.target.value)} /></label>
        <label style={{ fontSize: 13 }}>to <input type="date" value={to} onChange={(e) => setTo(e.target.value)} /></label>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 12 }}>
        <Stat label="Conversations" value={String(ov.volume)} />
        <Stat label="Autonomous resolution" value={`${Math.round((ov.autonomous_resolution_rate ?? 0) * 100)}%`} />
        <Stat label="Latency p50 / p95" value={`${lat.p50_ms ?? "—"} / ${lat.p95_ms ?? "—"} ms`} />
        <Stat label="Cost / conversation" value={`$${(cost.cost_per_conversation ?? 0).toFixed(4)}`} />
      </div>

      <DistChart title="Escalation reasons" data={ov.escalation_reasons ?? {}} />
      <DistChart title="Language distribution" data={ov.language_distribution ?? {}} />

      <Card>
        <h3>Top tags · CSAT</h3>
        <p style={{ color: "#6b7280" }}>Coming soon — pending ticket tags (M5) and thumbs feedback.</p>
      </Card>
    </div>
  );
}
