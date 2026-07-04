/** FE-Tickets / FE-AgentWorkspace — detail + working view via `GET /tickets/{id}` and the
 * aggregated `.../context` payload. Mounted at both `/admin/tickets/:id` and
 * `/agent/tickets/:id`. When a ticket is `with_agent`, reply/notes/resolve/release are shown;
 * the backend enforces server-side that only the current holder can actually use them (a 403
 * surfaces inline here rather than being hidden client-side, since ownership can change between
 * page load and the click). */

import { type FormEvent, useState } from "react";
import { useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { Button, Card, Spinner } from "../../components";
import { api, unwrap } from "../../lib/api";

interface Ticket {
  id: string;
  state: string;
  priority: string;
  language: string | null;
  linked_record_type: string | null;
  linked_record_key: string | null;
  assignee_id: string | null;
  tags: { name: string; status: string }[];
}

interface Message {
  id: string;
  role: string;
  content: string;
  created_at: string;
}

interface Note {
  id: string;
  staff_id: string;
  content: string;
  created_at: string;
}

interface LiveRecord {
  status: string;
  reason?: string | null;
}

interface TicketContext {
  transcript: Message[];
  internal_notes: Note[];
  ai_summary: string | null;
  suggested_reply: string | null;
  live_record: LiveRecord;
}

export function TicketDetailPage() {
  const { id = "" } = useParams();
  const queryClient = useQueryClient();
  const [actionError, setActionError] = useState<string | null>(null);

  const { data: ticket, isLoading } = useQuery({
    queryKey: ["ticket", id],
    queryFn: async () =>
      unwrap<Ticket>(
        await api.GET("/api/v1/tickets/{ticket_id}", { params: { path: { ticket_id: id } } })
      ),
    enabled: !!id,
  });

  const { data: context } = useQuery({
    queryKey: ["ticket-context", id],
    queryFn: async () =>
      unwrap<TicketContext>(
        await api.GET("/api/v1/tickets/{ticket_id}/context", {
          params: { path: { ticket_id: id } },
        })
      ),
    enabled: !!id,
  });

  function invalidate() {
    void queryClient.invalidateQueries({ queryKey: ["ticket", id] });
    void queryClient.invalidateQueries({ queryKey: ["ticket-context", id] });
    void queryClient.invalidateQueries({ queryKey: ["agent-queue"] });
  }

  function onError(err: unknown) {
    setActionError(err instanceof Error ? err.message : "That didn't work");
  }

  const reopen = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/tickets/{ticket_id}/reopen", {
          params: { path: { ticket_id: id } },
        })
      ),
    onSuccess: invalidate,
    onError,
  });

  const reply = useMutation({
    mutationFn: async (content: string) =>
      unwrap(
        await api.POST("/api/v1/tickets/{ticket_id}/reply", {
          params: { path: { ticket_id: id } },
          body: { content },
        })
      ),
    onSuccess: invalidate,
    onError,
  });

  const addNote = useMutation({
    mutationFn: async (content: string) =>
      unwrap(
        await api.POST("/api/v1/tickets/{ticket_id}/notes", {
          params: { path: { ticket_id: id } },
          body: { content },
        })
      ),
    onSuccess: invalidate,
    onError,
  });

  const resolve = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.PATCH("/api/v1/tickets/{ticket_id}", {
          params: { path: { ticket_id: id } },
          body: { state: "resolved" },
        })
      ),
    onSuccess: invalidate,
    onError,
  });

  const release = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/tickets/{ticket_id}/release", {
          params: { path: { ticket_id: id } },
        })
      ),
    onSuccess: invalidate,
    onError,
  });

  function handleReply(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setActionError(null);
    const form = e.currentTarget;
    const content = (form.elements.namedItem("content") as HTMLTextAreaElement).value;
    if (!content.trim()) return;
    reply.mutate(content, { onSuccess: () => form.reset() });
  }

  function handleNote(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setActionError(null);
    const form = e.currentTarget;
    const content = (form.elements.namedItem("content") as HTMLTextAreaElement).value;
    if (!content.trim()) return;
    addNote.mutate(content, { onSuccess: () => form.reset() });
  }

  if (isLoading) return <Spinner />;
  if (!ticket)
    return (
      <Card>
        <p>Ticket not found.</p>
      </Card>
    );

  const canReopen = ticket.state === "resolved" || ticket.state === "closed";
  const isWithAgent = ticket.state === "with_agent";

  return (
    <Card>
      <h2>Ticket {ticket.id.slice(0, 8)}</h2>
      <p>
        <strong>State:</strong> {ticket.state} &nbsp; <strong>Priority:</strong> {ticket.priority}
      </p>
      <p>
        <strong>Tags:</strong>{" "}
        {ticket.tags.map((t) => `${t.name} (${t.status})`).join(", ") || "—"}
      </p>
      {ticket.linked_record_type && (
        <p>
          <strong>Linked record:</strong> {ticket.linked_record_type} / {ticket.linked_record_key}
        </p>
      )}
      {actionError && (
        <p role="alert" style={{ color: "#dc2626" }}>
          {actionError}
        </p>
      )}
      {canReopen && (
        <Button onClick={() => reopen.mutate()} disabled={reopen.isPending}>
          {reopen.isPending ? "Reopening…" : "Reopen"}
        </Button>
      )}

      {isWithAgent && (
        <div style={{ marginTop: 16, display: "grid", gap: 12 }}>
          <form onSubmit={handleReply} style={{ display: "grid", gap: 6 }}>
            <label>Reply to customer</label>
            <textarea name="content" rows={2} required />
            <Button type="submit" disabled={reply.isPending} style={{ width: "fit-content" }}>
              {reply.isPending ? "Sending…" : "Send reply"}
            </Button>
          </form>
          <form onSubmit={handleNote} style={{ display: "grid", gap: 6 }}>
            <label>Internal note (not visible to the customer)</label>
            <textarea name="content" rows={2} required />
            <Button
              type="submit"
              variant="ghost"
              disabled={addNote.isPending}
              style={{ width: "fit-content" }}
            >
              {addNote.isPending ? "Saving…" : "Add note"}
            </Button>
          </form>
          <div style={{ display: "flex", gap: 8 }}>
            <Button onClick={() => resolve.mutate()} disabled={resolve.isPending}>
              {resolve.isPending ? "Resolving…" : "Resolve"}
            </Button>
            <Button variant="ghost" onClick={() => release.mutate()} disabled={release.isPending}>
              {release.isPending ? "Releasing…" : "Release back to queue"}
            </Button>
          </div>
        </div>
      )}

      <h3 style={{ marginTop: 20 }}>Conversation context</h3>
      {!context && <Spinner />}
      {context && (
        <>
          <p>
            <strong>AI summary:</strong> {context.ai_summary ?? "Summary pending."}
          </p>
          <p>
            <strong>Suggested reply:</strong> {context.suggested_reply ?? "Not available yet."}
          </p>
          <p>
            <strong>Live record:</strong>{" "}
            {context.live_record.status === "ok"
              ? "available"
              : `unavailable — ${context.live_record.reason ?? "unknown reason"}`}
          </p>
          <div style={{ display: "grid", gap: 8, marginTop: 12 }}>
            {context.transcript.length === 0 && (
              <p style={{ color: "#6b7280" }}>No messages yet.</p>
            )}
            {context.transcript.map((m) => (
              <div key={m.id} style={{ padding: 8, background: "#f9fafb", borderRadius: 8 }}>
                <strong>{m.role}:</strong> {m.content}
              </div>
            ))}
          </div>
          {context.internal_notes.length > 0 && (
            <>
              <h4 style={{ marginTop: 16 }}>Internal notes</h4>
              <div style={{ display: "grid", gap: 8 }}>
                {context.internal_notes.map((n) => (
                  <div key={n.id} style={{ padding: 8, background: "#fffbeb", borderRadius: 8 }}>
                    {n.content}
                  </div>
                ))}
              </div>
            </>
          )}
        </>
      )}
    </Card>
  );
}
