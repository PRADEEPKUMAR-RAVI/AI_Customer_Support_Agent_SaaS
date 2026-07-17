/** FE-AgentWorkspace — a three-pane live working view mounted at `/inbox`.
 *
 *   left   = the live escalation queue (polled `GET /agents/queue`, FIFO) with per-entry Claim.
 *   center = the selected conversation: transcript + a Reply / Internal-note composer.
 *   right  = the context rail: AI summary, tags, and the live-refetched customer record.
 *
 * Realtime: `GET /agents/queue` is polled rather than pushed over SSE — the backend derives the
 * queue directly from ticket state, so polling is correct today without a bespoke SSE client. The
 * selected ticket + its context are polled on a slower cadence so replies/notes stay live.
 * Presence liveness works the same way: a heartbeat call refreshes the backend's Redis-TTL
 * presence key on an interval (stop calling -> TTL expires -> Away).
 *
 * Ownership is enforced server-side; the UI mirrors it — the composer and resolve/release are only
 * offered when the ticket is `with_agent` and held by the current agent, otherwise the pane is
 * read-only (a 403 would still surface as a toast if ownership changed under us).
 */

import { type FormEvent, type KeyboardEvent, type ReactNode, useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { LucideIcon } from "lucide-react";
import {
  Bot,
  Clock,
  FileText,
  Inbox,
  MessageSquare,
  RefreshCw,
  Send,
  Sparkles,
  StickyNote,
  Tag,
  User,
} from "lucide-react";
import { toast } from "sonner";

import type { components } from "@/api/generated/schema";
import { ConfirmDialog } from "@/components/confirm-dialog";
import { EmptyState } from "@/components/empty-state";
import { ErrorState } from "@/components/error-state";
import { StatusBadge } from "@/components/status-badge";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Separator } from "@/components/ui/separator";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import { api, unwrap } from "@/lib/api";
import { usePageBanner } from "@/lib/pageBanner";
import { readMe } from "@/lib/useMe";
import { cn } from "@/lib/utils";

type Ticket = components["schemas"]["TicketResponse"];
type TicketContext = components["schemas"]["TicketContextResponse"];
type QueueEntry = components["schemas"]["QueueEntry"];
type Message = components["schemas"]["MessageOut"];
type LiveRecord = components["schemas"]["LiveRecordResponse"];

const QUEUE_POLL_INTERVAL_MS = 5_000;
const CONTEXT_POLL_INTERVAL_MS = 8_000;

const PANE_CLASS = "flex min-h-0 flex-col gap-0 overflow-hidden p-0 lg:h-full";

function errMessage(e: unknown): string {
  return e instanceof Error ? e.message : "Something went wrong. Please try again.";
}

function humanizeKey(k: string): string {
  return k.replace(/[_-]+/g, " ").replace(/^\w/, (c) => c.toUpperCase());
}

function formatWait(seconds: number): string {
  const s = Math.max(0, Math.round(seconds));
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ${s % 60}s`;
  const h = Math.floor(m / 60);
  return `${h}h ${m % 60}m`;
}

function formatTime(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function formatFieldValue(v: unknown): string {
  if (v === null || v === undefined || v === "") return "—";
  if (typeof v === "object") return JSON.stringify(v);
  return String(v);
}

export function AgentWorkspacePage() {
  const me = readMe();
  const queryClient = useQueryClient();

  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [mode, setMode] = useState<"reply" | "note">("reply");
  const [composerText, setComposerText] = useState("");

  // Hands the top bar the page title/description in place of the plain breadcrumb, same pattern
  // as the onboarding wizard — cleared on unmount so leaving restores the default.
  useEffect(() => {
    usePageBanner.getState().set({
      title: "Agent workspace",
      subtitle: "Claim escalations from the live queue and resolve them with full conversation context.",
    });
    return () => usePageBanner.getState().clear();
  }, []);

  // --- Queue ----------------------------------------------------------------
  const {
    data: queue,
    isLoading: queueLoading,
    isError: queueError,
    refetch: refetchQueue,
  } = useQuery({
    queryKey: ["agent-queue"],
    queryFn: async () => unwrap<QueueEntry[]>(await api.GET("/api/v1/agents/queue")),
    refetchInterval: QUEUE_POLL_INTERVAL_MS,
    refetchOnWindowFocus: true,
  });

  // --- Selected ticket + context -------------------------------------------
  const { data: ticket, isLoading: ticketLoading } = useQuery({
    queryKey: ["ticket", selectedId],
    queryFn: async () =>
      unwrap<Ticket>(
        await api.GET("/api/v1/tickets/{ticket_id}", {
          params: { path: { ticket_id: selectedId! } },
        })
      ),
    enabled: !!selectedId,
    refetchInterval: CONTEXT_POLL_INTERVAL_MS,
  });

  const { data: context } = useQuery({
    queryKey: ["ticket-context", selectedId],
    queryFn: async () =>
      unwrap<TicketContext>(
        await api.GET("/api/v1/tickets/{ticket_id}/context", {
          params: { path: { ticket_id: selectedId! } },
        })
      ),
    enabled: !!selectedId,
    refetchInterval: CONTEXT_POLL_INTERVAL_MS,
  });

  function invalidate(id: string | null) {
    if (id) {
      void queryClient.invalidateQueries({ queryKey: ["ticket", id] });
      void queryClient.invalidateQueries({ queryKey: ["ticket-context", id] });
    }
    void queryClient.invalidateQueries({ queryKey: ["agent-queue"] });
    void queryClient.invalidateQueries({ queryKey: ["live-record"] });
  }

  // --- Mutations ------------------------------------------------------------
  const claim = useMutation({
    mutationFn: async (ticketId: string) =>
      unwrap(
        await api.POST("/api/v1/tickets/{ticket_id}/claim", {
          params: { path: { ticket_id: ticketId } },
        })
      ),
    onSuccess: (_data, ticketId) => {
      setSelectedId(ticketId);
      invalidate(ticketId);
      toast.success("Conversation claimed");
    },
    onError: (e) => toast.error(errMessage(e)),
  });

  const reply = useMutation({
    mutationFn: async (content: string) =>
      unwrap(
        await api.POST("/api/v1/tickets/{ticket_id}/reply", {
          params: { path: { ticket_id: selectedId! } },
          body: { content },
        })
      ),
    onSuccess: () => {
      invalidate(selectedId);
      setComposerText("");
      toast.success("Reply sent to the customer");
    },
    onError: (e) => toast.error(errMessage(e)),
  });

  const addNote = useMutation({
    mutationFn: async (content: string) =>
      unwrap(
        await api.POST("/api/v1/tickets/{ticket_id}/notes", {
          params: { path: { ticket_id: selectedId! } },
          body: { content },
        })
      ),
    onSuccess: () => {
      invalidate(selectedId);
      setComposerText("");
      toast.success("Internal note added");
    },
    onError: (e) => toast.error(errMessage(e)),
  });

  const resolve = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.PATCH("/api/v1/tickets/{ticket_id}", {
          params: { path: { ticket_id: selectedId! } },
          body: { state: "resolved" },
        })
      ),
    onSuccess: () => {
      invalidate(selectedId);
      toast.success("Ticket resolved");
    },
    onError: (e) => toast.error(errMessage(e)),
  });

  const release = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/tickets/{ticket_id}/release", {
          params: { path: { ticket_id: selectedId! } },
        })
      ),
    onSuccess: () => {
      invalidate(selectedId);
      toast.success("Released back to the queue");
    },
    onError: (e) => toast.error(errMessage(e)),
  });

  // --- Derived ownership ----------------------------------------------------
  const assignee = ticket?.assignee_id ?? null;
  const claimedByMe = !!assignee && assignee === me?.staffId;
  const claimedByOther = !!assignee && assignee !== me?.staffId;
  const isWithAgent = ticket?.state === "with_agent";
  const canWork = isWithAgent && claimedByMe;
  const isEscalated = ticket?.state === "escalated";
  const sendBusy = mode === "reply" ? reply.isPending : addNote.isPending;

  function submitComposer() {
    const text = composerText.trim();
    if (!text || !canWork || sendBusy) return;
    if (mode === "reply") reply.mutate(text);
    else addNote.mutate(text);
  }

  function onComposerSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    submitComposer();
  }

  function onComposerKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
      e.preventDefault();
      submitComposer();
    }
  }

  return (
    <>
      <div className="grid gap-4 lg:h-[calc(100dvh-12rem)] lg:min-h-[34rem] lg:grid-cols-[300px_minmax(0,1fr)_320px]">
        {/* ── Left: live queue ─────────────────────────────────────────── */}
        <Card className={cn(PANE_CLASS, "h-[24rem]")}>
          <div className="flex items-center justify-between border-b px-4 py-3">
            <h2 className="text-sm font-semibold">Live queue</h2>
            {queue ? (
              <Badge variant="secondary" className="tabular-nums">
                {queue.length}
              </Badge>
            ) : null}
          </div>
          <ScrollArea className="min-h-0 flex-1">
            <div className="p-2">
              {queueLoading ? (
                <div className="space-y-2 p-1">
                  {[0, 1, 2, 3].map((i) => (
                    <Skeleton key={i} className="h-20 w-full rounded-lg" />
                  ))}
                </div>
              ) : queueError ? (
                <ErrorState
                  title="Couldn't load the queue"
                  message="The escalation queue failed to load."
                  onRetry={() => void refetchQueue()}
                  className="border-0 bg-transparent py-8"
                />
              ) : !queue || queue.length === 0 ? (
                <EmptyState
                  icon={Inbox}
                  title="Queue is clear"
                  description="No escalations are waiting right now."
                  className="border-0 bg-transparent py-10"
                />
              ) : (
                <ul className="space-y-1.5">
                  {queue.map((item) => (
                    <QueueRow
                      key={item.id}
                      item={item}
                      selected={selectedId === item.id}
                      claiming={claim.isPending}
                      onSelect={() => setSelectedId(item.id)}
                      onClaim={() => claim.mutate(item.id)}
                    />
                  ))}
                </ul>
              )}
            </div>
          </ScrollArea>
        </Card>

        {/* ── Center: selected conversation ────────────────────────────── */}
        <Card className={cn(PANE_CLASS, "h-[30rem]")}>
          {!selectedId ? (
            <div className="flex flex-1 items-center justify-center p-6">
              <EmptyState
                icon={MessageSquare}
                title="No conversation selected"
                description="Pick an escalation from the queue to view its transcript and start working."
                className="border-0 bg-transparent"
              />
            </div>
          ) : (
            <>
              <div className="flex items-center justify-between gap-3 border-b px-4 py-3">
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-mono text-sm font-medium tabular-nums">
                      #{selectedId.slice(0, 8)}
                    </span>
                    {ticket ? <StatusBadge value={ticket.state} /> : null}
                    {ticket ? <StatusBadge value={ticket.priority} /> : null}
                  </div>
                  {ticket?.language ? (
                    <p className="mt-0.5 text-xs text-muted-foreground">
                      Language: {ticket.language}
                    </p>
                  ) : null}
                </div>
                {canWork ? (
                  <div className="flex shrink-0 items-center gap-2">
                    <ConfirmDialog
                      trigger={
                        <Button size="sm" variant="outline">
                          Resolve
                        </Button>
                      }
                      title="Resolve this conversation?"
                      description="Mark the ticket resolved. The customer will be notified it's been handled."
                      confirmText="Resolve"
                      onConfirm={() => resolve.mutate()}
                    />
                    <ConfirmDialog
                      trigger={
                        <Button size="sm" variant="ghost">
                          Release
                        </Button>
                      }
                      title="Release back to the queue?"
                      description="You'll give up this conversation so another agent can claim it."
                      confirmText="Release"
                      onConfirm={() => release.mutate()}
                    />
                  </div>
                ) : null}
              </div>

              <ScrollArea className="min-h-0 flex-1">
                <div className="space-y-4 p-4">
                  {ticketLoading || !context ? (
                    <div className="space-y-3">
                      {[0, 1, 2].map((i) => (
                        <Skeleton
                          key={i}
                          className={cn("h-16 rounded-2xl", i % 2 ? "ml-auto w-3/5" : "w-3/5")}
                        />
                      ))}
                    </div>
                  ) : (
                    <>
                      {context.transcript.length === 0 ? (
                        <p className="py-6 text-center text-sm text-muted-foreground">
                          No messages yet.
                        </p>
                      ) : (
                        context.transcript.map((m) => <MessageBubble key={m.id} message={m} />)
                      )}

                      {context.internal_notes.length > 0 ? (
                        <div className="space-y-3 pt-2">
                          <div className="flex items-center gap-2">
                            <Separator className="flex-1" />
                            <span className="text-xs font-medium text-muted-foreground">
                              Internal notes
                            </span>
                            <Separator className="flex-1" />
                          </div>
                          {context.internal_notes.map((n) => (
                            <div
                              key={n.id}
                              className="rounded-lg border border-warning/40 bg-warning/10 p-3"
                            >
                              <div className="mb-1 flex flex-wrap items-center gap-1.5 text-xs text-warning-foreground/80">
                                <StickyNote className="size-3" />
                                <span className="font-mono tabular-nums">
                                  {n.staff_id.slice(0, 8)}
                                </span>
                                <span className="tabular-nums">· {formatTime(n.created_at)}</span>
                              </div>
                              <p className="text-sm break-words whitespace-pre-wrap text-foreground">
                                {n.content}
                              </p>
                            </div>
                          ))}
                        </div>
                      ) : null}
                    </>
                  )}
                </div>
              </ScrollArea>

              {/* Composer / read-only footer */}
              <div className="border-t p-3">
                {canWork ? (
                  <form onSubmit={onComposerSubmit} className="space-y-2">
                    <Tabs value={mode} onValueChange={(v) => setMode(v as "reply" | "note")}>
                      <TabsList className="grid w-full grid-cols-2">
                        <TabsTrigger value="reply">
                          <Send className="size-3.5" />
                          Reply
                        </TabsTrigger>
                        <TabsTrigger value="note">
                          <StickyNote className="size-3.5" />
                          Internal note
                        </TabsTrigger>
                      </TabsList>
                    </Tabs>
                    <div
                      className={cn(
                        "rounded-lg border transition-colors",
                        mode === "note" ? "border-warning/50 bg-warning/10" : "border-input"
                      )}
                    >
                      <Textarea
                        value={composerText}
                        onChange={(e) => setComposerText(e.target.value)}
                        onKeyDown={onComposerKeyDown}
                        placeholder={
                          mode === "reply"
                            ? "Write a reply to the customer…"
                            : "Add an internal note (not visible to the customer)…"
                        }
                        aria-label={mode === "reply" ? "Reply to customer" : "Internal note"}
                        className="min-h-20 resize-none border-0 bg-transparent shadow-none focus-visible:ring-0"
                      />
                      <div className="flex items-center justify-between gap-2 px-2 pb-2">
                        <span className="text-xs text-muted-foreground">
                          {mode === "note"
                            ? "Visible only to your team"
                            : "Sends to the customer"}{" "}
                          · Ctrl+Enter
                        </span>
                        <Button
                          type="submit"
                          size="sm"
                          variant={mode === "note" ? "secondary" : "default"}
                          disabled={!composerText.trim() || sendBusy}
                        >
                          {sendBusy
                            ? "Sending…"
                            : mode === "reply"
                              ? "Send reply"
                              : "Add note"}
                        </Button>
                      </div>
                    </div>
                  </form>
                ) : claimedByOther ? (
                  <div className="flex items-center gap-2 rounded-lg bg-muted px-3 py-2.5 text-sm text-muted-foreground">
                    <User className="size-4 shrink-0" />
                    This conversation is being handled by another agent. Read-only.
                  </div>
                ) : isEscalated ? (
                  <div className="space-y-2">
                    <p className="text-center text-xs text-muted-foreground">
                      Claim this conversation to reply and resolve it.
                    </p>
                    <Button
                      className="w-full"
                      disabled={claim.isPending}
                      onClick={() => claim.mutate(selectedId)}
                    >
                      Claim this conversation
                    </Button>
                  </div>
                ) : (
                  <p className="text-center text-sm text-muted-foreground">
                    {ticket ? `This conversation is ${ticket.state.replace(/_/g, " ")}.` : "Loading…"}
                  </p>
                )}
              </div>
            </>
          )}
        </Card>

        {/* ── Right: context rail ──────────────────────────────────────── */}
        <Card className={cn(PANE_CLASS, "h-[24rem]")}>
          <div className="border-b px-4 py-3">
            <h2 className="text-sm font-semibold">Context</h2>
          </div>
          <ScrollArea className="min-h-0 flex-1">
            <div className="space-y-5 p-4">
              {!selectedId ? (
                <p className="text-sm text-muted-foreground">
                  Select a conversation to see its AI summary, tags, and linked customer record.
                </p>
              ) : (
                <>
                  <section>
                    <SectionTitle icon={Sparkles}>AI summary</SectionTitle>
                    {context ? (
                      <p className="text-sm break-words whitespace-pre-wrap text-foreground/90">
                        {context.ai_summary ?? "Summary pending."}
                      </p>
                    ) : (
                      <div className="space-y-2">
                        <Skeleton className="h-4 w-full" />
                        <Skeleton className="h-4 w-2/3" />
                      </div>
                    )}
                    {context?.suggested_reply && canWork ? (
                      <div className="mt-3 rounded-lg border bg-muted/40 p-3">
                        <p className="text-xs font-medium text-muted-foreground">Suggested reply</p>
                        <p className="mt-1 text-sm break-words whitespace-pre-wrap">
                          {context.suggested_reply}
                        </p>
                        <Button
                          size="xs"
                          variant="outline"
                          className="mt-2"
                          onClick={() => {
                            setMode("reply");
                            setComposerText(context.suggested_reply ?? "");
                          }}
                        >
                          Use suggestion
                        </Button>
                      </div>
                    ) : null}
                  </section>

                  <Separator />

                  <section>
                    <SectionTitle icon={Tag}>Tags</SectionTitle>
                    {ticket && ticket.tags.length > 0 ? (
                      <div className="space-y-1.5">
                        {ticket.tags.map((t) => (
                          <div
                            key={t.name}
                            className="flex items-center justify-between gap-2 rounded-md border px-2.5 py-1.5"
                          >
                            <span className="truncate text-sm">{t.name}</span>
                            <StatusBadge value={t.status} />
                          </div>
                        ))}
                      </div>
                    ) : (
                      <p className="text-sm text-muted-foreground">No tags.</p>
                    )}
                  </section>

                  <Separator />

                  <section>
                    <SectionTitle icon={FileText}>Linked record</SectionTitle>
                    {ticket?.linked_record_type && ticket?.linked_record_key ? (
                      <>
                        <p className="text-sm">
                          <span className="text-muted-foreground">
                            {humanizeKey(ticket.linked_record_type)}
                          </span>{" "}
                          ·{" "}
                          <span className="font-mono tabular-nums break-all">
                            {ticket.linked_record_key}
                          </span>
                        </p>
                        <div className="mt-3">
                          <LiveRecordPanel
                            recordType={ticket.linked_record_type}
                            recordKey={ticket.linked_record_key}
                          />
                        </div>
                      </>
                    ) : (
                      <p className="text-sm text-muted-foreground">No linked record.</p>
                    )}
                  </section>
                </>
              )}
            </div>
          </ScrollArea>
        </Card>
      </div>
    </>
  );
}

// ── Sub-components ──────────────────────────────────────────────────────────

function SectionTitle({ icon: Icon, children }: { icon: LucideIcon; children: ReactNode }) {
  return (
    <h3 className="mb-2 flex items-center gap-1.5 text-xs font-medium tracking-wide text-muted-foreground uppercase">
      <Icon className="size-3.5" />
      {children}
    </h3>
  );
}

function QueueRow({
  item,
  selected,
  claiming,
  onSelect,
  onClaim,
}: {
  item: QueueEntry;
  selected: boolean;
  claiming: boolean;
  onSelect: () => void;
  onClaim: () => void;
}) {
  return (
    <li>
      <div
        className={cn(
          "rounded-lg border p-2.5 transition-colors",
          selected ? "border-primary/40 bg-accent" : "hover:bg-muted/50"
        )}
      >
        <button type="button" onClick={onSelect} className="w-full text-left">
          <div className="flex items-center justify-between gap-2">
            <StatusBadge value={item.priority} />
            <span className="inline-flex items-center gap-1 text-xs tabular-nums text-muted-foreground">
              <Clock className="size-3" />
              {formatWait(item.wait_seconds)}
            </span>
          </div>
          <div className="mt-1.5 flex items-center justify-between gap-2">
            <span className="font-mono text-xs tabular-nums text-muted-foreground">
              #{item.id.slice(0, 8)}
            </span>
            <span className="text-xs text-muted-foreground">{item.language ?? "—"}</span>
          </div>
          {item.tags.length > 0 ? (
            <div className="mt-1.5 flex flex-wrap gap-1">
              {item.tags.slice(0, 3).map((t) => (
                <Badge key={t.name} variant="outline" className="text-[10px]">
                  {t.name}
                </Badge>
              ))}
            </div>
          ) : null}
        </button>
        <Button size="sm" className="mt-2 w-full" disabled={claiming} onClick={onClaim}>
          Claim
        </Button>
      </div>
    </li>
  );
}

function MessageBubble({ message }: { message: Message }) {
  const roleLabel: Record<string, string> = {
    user: "Customer",
    customer: "Customer",
    assistant: "AI agent",
    agent: "Agent",
    staff: "Agent",
  };
  const label = roleLabel[message.role] ?? humanizeKey(message.role);
  const incoming = message.role === "user" || message.role === "customer";
  const Icon = message.role === "assistant" ? Bot : User;
  return (
    <div className={cn("flex flex-col gap-1", incoming ? "items-start" : "items-end")}>
      <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
        <Icon className="size-3" />
        <span className="font-medium">{label}</span>
        <span className="tabular-nums">· {formatTime(message.created_at)}</span>
      </div>
      <div
        className={cn(
          "max-w-[85%] rounded-2xl px-3 py-2 text-sm break-words whitespace-pre-wrap",
          incoming
            ? "rounded-tl-sm bg-muted text-foreground"
            : "rounded-tr-sm bg-primary/10 text-foreground"
        )}
      >
        {message.content}
      </div>
    </div>
  );
}

function LiveRecordPanel({
  recordType,
  recordKey,
}: {
  recordType: string;
  recordKey: string;
}) {
  const { data, isLoading, isError, isFetching, refetch } = useQuery({
    queryKey: ["live-record", recordType, recordKey],
    queryFn: async () =>
      unwrap<LiveRecord>(
        await api.GET("/api/v1/records/live/{record_type}/{key}", {
          params: { path: { record_type: recordType, key: recordKey } },
        })
      ),
  });

  let body: ReactNode;
  if (isLoading) {
    body = (
      <div className="space-y-2">
        <Skeleton className="h-4 w-full" />
        <Skeleton className="h-4 w-5/6" />
        <Skeleton className="h-4 w-2/3" />
      </div>
    );
  } else if (isError) {
    body = (
      <p className="rounded-md bg-warning/15 px-2.5 py-2 text-sm text-warning-foreground">
        Couldn't reach the record system. Try again shortly.
      </p>
    );
  } else if (!data?.available) {
    body = (
      <p className="rounded-md bg-warning/15 px-2.5 py-2 text-sm text-warning-foreground">
        The record system is currently unavailable. Try again shortly.
      </p>
    );
  } else if (!data.record) {
    body = (
      <p className="rounded-md border border-dashed px-2.5 py-2 text-sm text-muted-foreground">
        This record no longer exists.
      </p>
    );
  } else {
    const entries = Object.entries(data.record);
    body =
      entries.length === 0 ? (
        <p className="text-sm text-muted-foreground">No fields returned.</p>
      ) : (
        <dl className="space-y-1.5">
          {entries.map(([k, v]) => (
            <div key={k} className="flex items-start justify-between gap-3 text-sm">
              <dt className="text-muted-foreground">{humanizeKey(k)}</dt>
              <dd className="text-right font-medium tabular-nums break-words">
                {formatFieldValue(v)}
              </dd>
            </div>
          ))}
        </dl>
      );
  }

  return (
    <div className="rounded-lg border bg-muted/30 p-3">
      <div className="mb-2 flex items-center justify-between">
        <p className="text-xs font-medium text-muted-foreground">Live record</p>
        <Button
          size="icon-xs"
          variant="ghost"
          aria-label="Refresh live record"
          disabled={isFetching}
          onClick={() => void refetch()}
        >
          <RefreshCw className={cn("size-3", isFetching && "animate-spin")} />
        </Button>
      </div>
      {body}
    </div>
  );
}
