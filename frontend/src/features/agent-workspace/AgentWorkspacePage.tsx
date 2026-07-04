/** FE-AgentWorkspace — Available/Away + heartbeat, polled live queue, claim. Mounted at
 * `/agent`.
 *
 * Realtime: `GET /agents/queue` is polled rather than pushed over SSE. The backend already
 * derives the queue directly from ticket state — the documented source of truth on its own —
 * so polling is correct today without standing up a bespoke SSE client for this one screen.
 * Presence liveness works the same way: a heartbeat call refreshes the backend's Redis-TTL
 * presence key on an interval, giving the same crash-detection property a live SSE connection
 * would (stop calling -> TTL expires -> Away), without needing that connection to exist.
 */

import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";

import { Button, Card, Spinner } from "../../components";
import { api, unwrap } from "../../lib/api";

interface QueueEntry {
  id: string;
  priority: string;
  language: string | null;
  escalated_at: string;
  wait_seconds: number;
  tags: { name: string; status: string }[];
}

const HEARTBEAT_INTERVAL_MS = 20_000;
const QUEUE_POLL_INTERVAL_MS = 5_000;

export function AgentWorkspacePage() {
  const [available, setAvailableState] = useState(false);
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  const presence = useMutation({
    mutationFn: async (status: "available" | "away") =>
      unwrap(await api.POST("/api/v1/agents/presence", { body: { status } })),
  });

  useEffect(() => {
    if (!available) return undefined;
    const id = setInterval(() => presence.mutate("available"), HEARTBEAT_INTERVAL_MS);
    // Browsers throttle setInterval in a backgrounded tab, which can let the presence TTL
    // lapse right as the agent switches back — send an immediate heartbeat on regaining
    // visibility instead of waiting for the next throttled tick ("reconnect" polish).
    const onVisible = () => {
      if (document.visibilityState === "visible") presence.mutate("available");
    };
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      clearInterval(id);
      document.removeEventListener("visibilitychange", onVisible);
    };
    // presence is a stable useMutation object across renders; only `available` should re-arm this.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [available]);

  function toggleAvailable() {
    const next = !available;
    setAvailableState(next);
    presence.mutate(next ? "available" : "away");
  }

  const { data: queue, isLoading } = useQuery({
    queryKey: ["agent-queue"],
    queryFn: async () => unwrap<QueueEntry[]>(await api.GET("/api/v1/agents/queue")),
    refetchInterval: QUEUE_POLL_INTERVAL_MS,
    // Overrides the app-wide default (off) — the queue is exactly the kind of view that goes
    // stale while a tab is backgrounded; refetch immediately on refocus rather than waiting
    // up to QUEUE_POLL_INTERVAL_MS ("reconnect" polish).
    refetchOnWindowFocus: true,
  });

  const claim = useMutation({
    mutationFn: async (ticketId: string) =>
      unwrap(
        await api.POST("/api/v1/tickets/{ticket_id}/claim", {
          params: { path: { ticket_id: ticketId } },
        })
      ),
    onSuccess: (_data, ticketId) => {
      void queryClient.invalidateQueries({ queryKey: ["agent-queue"] });
      navigate(`/agent/tickets/${ticketId}`);
    },
  });

  return (
    <Card>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <h2>Agent workspace</h2>
        <Button variant={available ? "primary" : "ghost"} onClick={toggleAvailable}>
          {available ? "Available" : "Away"} — click to toggle
        </Button>
      </div>

      <h3 style={{ marginTop: 16 }}>Live queue</h3>
      {isLoading && <Spinner />}
      {queue && queue.length === 0 && <p>No escalations waiting.</p>}
      {queue && queue.length > 0 && (
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 14 }}>
          <thead>
            <tr style={{ textAlign: "left", borderBottom: "1px solid #e5e7eb" }}>
              <th style={{ padding: "6px 4px" }}>Priority</th>
              <th style={{ padding: "6px 4px" }}>Language</th>
              <th style={{ padding: "6px 4px" }}>Waiting</th>
              <th style={{ padding: "6px 4px" }}>Tags</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {queue.map((q) => (
              <tr key={q.id} style={{ borderBottom: "1px solid #f3f4f6" }}>
                <td style={{ padding: "6px 4px" }}>{q.priority}</td>
                <td style={{ padding: "6px 4px" }}>{q.language ?? "—"}</td>
                <td style={{ padding: "6px 4px" }}>{Math.round(q.wait_seconds)}s</td>
                <td style={{ padding: "6px 4px" }}>
                  {q.tags.map((t) => t.name).join(", ") || "—"}
                </td>
                <td style={{ padding: "6px 4px" }}>
                  <Button disabled={claim.isPending} onClick={() => claim.mutate(q.id)}>
                    Claim
                  </Button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Card>
  );
}
