/** FE-Tickets — list + filter/search. Mounted at `/admin/tickets`. */

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";

import { Card, Spinner } from "../../components";
import { api, unwrap } from "../../lib/api";

interface Tag {
  name: string;
  status: string;
}

interface Ticket {
  id: string;
  state: string;
  priority: string;
  language: string | null;
  created_at: string;
  tags: Tag[];
}

interface Page<T> {
  items: T[];
  total: number;
}

const STATES = ["new", "ai_handling", "escalated", "with_agent", "resolved", "closed", "reopened"];
const PRIORITIES = ["low", "normal", "high"];

export function TicketsPage() {
  const [status, setStatus] = useState("");
  const [priority, setPriority] = useState("");
  const [tag, setTag] = useState("");

  const { data, isLoading, isError } = useQuery({
    queryKey: ["tickets", { status, priority, tag }],
    queryFn: async () =>
      unwrap<Page<Ticket>>(
        await api.GET("/api/v1/tickets", {
          params: {
            query: {
              status: status || undefined,
              priority: priority || undefined,
              tag: tag || undefined,
            },
          },
        })
      ),
  });

  return (
    <Card>
      <h2>Tickets</h2>
      <div style={{ display: "flex", gap: 8, marginBottom: 16 }}>
        <select value={status} onChange={(e) => setStatus(e.target.value)}>
          <option value="">All statuses</option>
          {STATES.map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </select>
        <select value={priority} onChange={(e) => setPriority(e.target.value)}>
          <option value="">All priorities</option>
          {PRIORITIES.map((p) => (
            <option key={p} value={p}>
              {p}
            </option>
          ))}
        </select>
        <input placeholder="Filter by tag" value={tag} onChange={(e) => setTag(e.target.value)} />
      </div>

      {isLoading && <Spinner />}
      {isError && (
        <p role="alert" style={{ color: "#dc2626" }}>
          Failed to load tickets.
        </p>
      )}
      {data && data.items.length === 0 && <p>No tickets match these filters.</p>}
      {data && data.items.length > 0 && (
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 14 }}>
          <thead>
            <tr style={{ textAlign: "left", borderBottom: "1px solid #e5e7eb" }}>
              <th style={{ padding: "6px 4px" }}>State</th>
              <th style={{ padding: "6px 4px" }}>Priority</th>
              <th style={{ padding: "6px 4px" }}>Language</th>
              <th style={{ padding: "6px 4px" }}>Tags</th>
              <th style={{ padding: "6px 4px" }}>Created</th>
            </tr>
          </thead>
          <tbody>
            {data.items.map((t) => (
              <tr key={t.id} style={{ borderBottom: "1px solid #f3f4f6" }}>
                <td style={{ padding: "6px 4px" }}>
                  <Link to={`/admin/tickets/${t.id}`}>{t.state}</Link>
                </td>
                <td style={{ padding: "6px 4px" }}>{t.priority}</td>
                <td style={{ padding: "6px 4px" }}>{t.language ?? "—"}</td>
                <td style={{ padding: "6px 4px" }}>
                  {t.tags.map((tg) => tg.name).join(", ") || "—"}
                </td>
                <td style={{ padding: "6px 4px" }}>{new Date(t.created_at).toLocaleString()}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {data && <p style={{ marginTop: 8, color: "#6b7280" }}>{data.total} total</p>}
    </Card>
  );
}
