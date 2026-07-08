/** FE-Tickets / FE-AgentWorkspace — detail + working view via `GET /tickets/{id}` and the
 * aggregated `.../context` payload. Mounted at `/tickets/:id`. When a ticket is `with_agent`,
 * reply/notes/resolve/release are shown; the backend enforces server-side that only the current
 * holder can actually use them (a 403 surfaces as a toast rather than being hidden client-side,
 * since ownership can change between page load and the click). */

import { useMemo, useState, type ReactNode } from "react";
import { Link, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowLeft,
  Bot,
  CheckCircle2,
  FileText,
  Globe,
  Headset,
  Inbox,
  Lock,
  MessageSquare,
  RotateCcw,
  Send,
  Sparkles,
  StickyNote,
  Tag,
  User,
  Wand2,
} from "lucide-react";
import { toast } from "sonner";

import { PageHeader } from "@/components/page-header";
import { StatusBadge } from "@/components/status-badge";
import { EmptyState } from "@/components/empty-state";
import { ErrorState } from "@/components/error-state";
import { ConfirmDialog } from "@/components/confirm-dialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Separator } from "@/components/ui/separator";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import type { components } from "@/api/generated/schema";
import { api, unwrap } from "@/lib/api";
import { cn } from "@/lib/utils";

type Ticket = components["schemas"]["TicketResponse"];
type TicketContext = components["schemas"]["TicketContextResponse"];
type MessageOut = components["schemas"]["MessageOut"];
type NoteOut = components["schemas"]["NoteOut"];

type TimelineItem =
  | ({ kind: "message" } & MessageOut)
  | ({ kind: "note" } & NoteOut);

const errMsg = (e: unknown) => (e instanceof Error ? e.message : "That didn't work. Try again.");

function formatShort(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
}

function formatFull(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

type RoleMeta = {
  label: string;
  side: "left" | "right";
  icon: typeof Bot;
  avatar: string;
  bubble: string;
};

function roleMeta(role: string): RoleMeta {
  const r = role.toLowerCase();
  if (r === "customer" || r === "user" || r === "end_user") {
    return {
      label: "Customer",
      side: "left",
      icon: User,
      avatar: "bg-secondary text-secondary-foreground",
      bubble: "bg-muted text-foreground",
    };
  }
  if (r === "ai" || r === "assistant" || r === "bot") {
    return {
      label: "AI agent",
      side: "right",
      icon: Bot,
      avatar: "bg-accent text-accent-foreground",
      bubble: "bg-accent text-accent-foreground",
    };
  }
  return {
    label: "Agent",
    side: "right",
    icon: Headset,
    avatar: "bg-primary text-primary-foreground",
    bubble: "bg-primary text-primary-foreground",
  };
}

function DetailRow({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex items-start justify-between gap-3">
      <span className="shrink-0 text-muted-foreground">{label}</span>
      <div className="min-w-0 text-right font-medium">{children}</div>
    </div>
  );
}

function MessageRow({ message }: { message: MessageOut }) {
  const meta = roleMeta(message.role);
  const Icon = meta.icon;
  return (
    <div className={cn("flex items-start gap-3", meta.side === "right" && "flex-row-reverse")}>
      <div className={cn("mt-0.5 grid size-8 shrink-0 place-items-center rounded-full", meta.avatar)}>
        <Icon className="size-4" />
      </div>
      <div className={cn("flex max-w-[82%] flex-col gap-1", meta.side === "right" && "items-end")}>
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          <span className="font-medium text-foreground">{meta.label}</span>
          <span className="tabular-nums">{formatShort(message.created_at)}</span>
        </div>
        <div
          className={cn(
            "rounded-xl px-3.5 py-2.5 text-sm leading-relaxed whitespace-pre-wrap break-words",
            meta.bubble
          )}
        >
          {message.content}
        </div>
      </div>
    </div>
  );
}

function NoteRow({ note }: { note: NoteOut }) {
  return (
    <div className="rounded-xl border border-warning/40 bg-warning/10 px-4 py-3">
      <div className="flex items-center gap-2 text-xs font-medium text-warning-foreground">
        <Lock className="size-3.5" />
        Internal note
        <span className="ml-auto font-normal text-muted-foreground tabular-nums">
          {formatShort(note.created_at)}
        </span>
      </div>
      <p className="mt-1.5 text-sm leading-relaxed whitespace-pre-wrap break-words text-foreground">
        {note.content}
      </p>
      <p className="mt-1.5 text-xs text-muted-foreground">Only visible to your team.</p>
    </div>
  );
}

export function TicketDetailPage() {
  const { id = "" } = useParams();
  const queryClient = useQueryClient();
  const [replyText, setReplyText] = useState("");
  const [noteText, setNoteText] = useState("");
  const [composerTab, setComposerTab] = useState("reply");

  const ticketQuery = useQuery({
    queryKey: ["ticket", id],
    queryFn: async () =>
      unwrap<Ticket>(
        await api.GET("/api/v1/tickets/{ticket_id}", { params: { path: { ticket_id: id } } })
      ),
    enabled: !!id,
  });

  const contextQuery = useQuery({
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

  const reopen = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/tickets/{ticket_id}/reopen", {
          params: { path: { ticket_id: id } },
        })
      ),
    onSuccess: () => {
      invalidate();
      toast.success("Ticket reopened.");
    },
    onError: (e) => toast.error(errMsg(e)),
  });

  const reply = useMutation({
    mutationFn: async (content: string) =>
      unwrap(
        await api.POST("/api/v1/tickets/{ticket_id}/reply", {
          params: { path: { ticket_id: id } },
          body: { content },
        })
      ),
    onSuccess: () => {
      invalidate();
      setReplyText("");
      toast.success("Reply sent to the customer.");
    },
    onError: (e) => toast.error(errMsg(e)),
  });

  const addNote = useMutation({
    mutationFn: async (content: string) =>
      unwrap(
        await api.POST("/api/v1/tickets/{ticket_id}/notes", {
          params: { path: { ticket_id: id } },
          body: { content },
        })
      ),
    onSuccess: () => {
      invalidate();
      setNoteText("");
      toast.success("Internal note added.");
    },
    onError: (e) => toast.error(errMsg(e)),
  });

  const resolve = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.PATCH("/api/v1/tickets/{ticket_id}", {
          params: { path: { ticket_id: id } },
          body: { state: "resolved" },
        })
      ),
    onSuccess: () => {
      invalidate();
      toast.success("Ticket resolved.");
    },
    onError: (e) => toast.error(errMsg(e)),
  });

  const release = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/tickets/{ticket_id}/release", {
          params: { path: { ticket_id: id } },
        })
      ),
    onSuccess: () => {
      invalidate();
      toast.success("Ticket released back to the queue.");
    },
    onError: (e) => toast.error(errMsg(e)),
  });

  const timeline = useMemo<TimelineItem[]>(() => {
    if (!contextQuery.data) return [];
    const merged: TimelineItem[] = [
      ...contextQuery.data.transcript.map((m) => ({ kind: "message" as const, ...m })),
      ...contextQuery.data.internal_notes.map((n) => ({ kind: "note" as const, ...n })),
    ];
    return merged.sort((a, b) => a.created_at.localeCompare(b.created_at));
  }, [contextQuery.data]);

  if (ticketQuery.isLoading) {
    return (
      <div className="space-y-6">
        <Skeleton className="h-4 w-28" />
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="space-y-2">
            <Skeleton className="h-8 w-48" />
            <Skeleton className="h-5 w-40" />
          </div>
          <Skeleton className="h-9 w-32" />
        </div>
        <div className="grid gap-6 lg:grid-cols-3">
          <Skeleton className="h-[480px] rounded-xl lg:col-span-2" />
          <div className="space-y-6">
            <Skeleton className="h-56 rounded-xl" />
            <Skeleton className="h-40 rounded-xl" />
          </div>
        </div>
      </div>
    );
  }

  const ticket = ticketQuery.data;
  if (ticketQuery.isError || !ticket) {
    return (
      <div className="space-y-6">
        <Link
          to="/tickets"
          className="inline-flex items-center gap-1.5 text-sm text-muted-foreground transition-colors hover:text-foreground"
        >
          <ArrowLeft className="size-4" />
          Back to tickets
        </Link>
        <PageHeader title="Ticket" description="This ticket could not be loaded." />
        <ErrorState
          title="Ticket unavailable"
          message={
            ticketQuery.error instanceof Error
              ? ticketQuery.error.message
              : "This ticket couldn't be loaded or no longer exists."
          }
          onRetry={() => void ticketQuery.refetch()}
        />
      </div>
    );
  }

  const canReopen = ticket.state === "resolved" || ticket.state === "closed";
  const isWithAgent = ticket.state === "with_agent";
  const shortId = ticket.id.slice(0, 8);
  const context = contextQuery.data;
  const liveOk =
    context?.live_record.status === "ok" || context?.live_record.status === "available";

  function insertSuggested() {
    if (!context?.suggested_reply) return;
    setReplyText(context.suggested_reply);
    setComposerTab("reply");
  }

  const headerActions = (
    <>
      {canReopen ? (
        <Button variant="outline" onClick={() => reopen.mutate()} disabled={reopen.isPending}>
          <RotateCcw />
          {reopen.isPending ? "Reopening…" : "Reopen"}
        </Button>
      ) : null}
      {isWithAgent ? (
        <>
          <ConfirmDialog
            trigger={
              <Button variant="outline" disabled={release.isPending}>
                <Inbox />
                {release.isPending ? "Releasing…" : "Release"}
              </Button>
            }
            title="Release back to the queue?"
            description="You'll give up your hold on this ticket and it returns to the shared queue for another agent to pick up."
            confirmText="Release"
            onConfirm={() => release.mutate()}
          />
          <Button onClick={() => resolve.mutate()} disabled={resolve.isPending}>
            <CheckCircle2 />
            {resolve.isPending ? "Resolving…" : "Resolve"}
          </Button>
        </>
      ) : null}
    </>
  );

  return (
    <div className="space-y-6">
      <Link
        to="/tickets"
        className="inline-flex items-center gap-1.5 text-sm text-muted-foreground transition-colors hover:text-foreground"
      >
        <ArrowLeft className="size-4" />
        Back to tickets
      </Link>

      <PageHeader
        title={`Ticket ${shortId}`}
        description={
          <span className="flex flex-wrap items-center gap-2">
            <StatusBadge value={ticket.state} />
            <StatusBadge value={ticket.priority} />
            {ticket.language ? (
              <Badge variant="outline" className="gap-1">
                <Globe className="size-3" />
                {ticket.language.toUpperCase()}
              </Badge>
            ) : null}
          </span>
        }
        actions={headerActions}
      />

      <div className="grid gap-6 lg:grid-cols-3">
        {/* Transcript + composer */}
        <Card className="gap-0 overflow-hidden py-0 lg:col-span-2">
          <div className="flex flex-col gap-0.5 border-b px-6 py-4">
            <h2 className="flex items-center gap-2 text-base font-semibold">
              <MessageSquare className="size-4 text-muted-foreground" />
              Conversation
            </h2>
            <p className="text-sm text-muted-foreground">
              Full transcript with internal notes inline. Notes are never shown to the customer.
            </p>
          </div>

          {contextQuery.isLoading ? (
            <div className="space-y-5 p-6">
              <Skeleton className="h-16 w-3/4 rounded-xl" />
              <Skeleton className="ml-auto h-16 w-3/4 rounded-xl" />
              <Skeleton className="h-12 w-2/3 rounded-xl" />
            </div>
          ) : contextQuery.isError ? (
            <div className="p-6">
              <ErrorState
                title="Couldn't load the transcript"
                message="The conversation history failed to load."
                onRetry={() => void contextQuery.refetch()}
              />
            </div>
          ) : timeline.length === 0 ? (
            <div className="p-6">
              <EmptyState
                icon={MessageSquare}
                title="No messages yet"
                description="This conversation has no transcript or internal notes so far."
              />
            </div>
          ) : (
            <ScrollArea className="h-[52vh] min-h-[360px]">
              <div className="space-y-5 p-6" role="log" aria-label="Conversation transcript">
                {timeline.map((item) =>
                  item.kind === "note" ? (
                    <NoteRow key={`note-${item.id}`} note={item} />
                  ) : (
                    <MessageRow key={`msg-${item.id}`} message={item} />
                  )
                )}
              </div>
            </ScrollArea>
          )}

          {isWithAgent ? (
            <div className="border-t bg-muted/20 px-6 py-5">
              <Tabs value={composerTab} onValueChange={setComposerTab}>
                <TabsList className="w-full">
                  <TabsTrigger value="reply">
                    <Send />
                    Reply to customer
                  </TabsTrigger>
                  <TabsTrigger value="note">
                    <Lock />
                    Internal note
                  </TabsTrigger>
                </TabsList>

                <TabsContent value="reply" className="mt-4 space-y-3">
                  <div className="space-y-2">
                    <Label
                      htmlFor="reply-input"
                      className="flex items-center gap-1.5 text-xs text-muted-foreground"
                    >
                      <Send className="size-3.5" />
                      This message is delivered to the customer.
                    </Label>
                    <Textarea
                      id="reply-input"
                      value={replyText}
                      onChange={(e) => setReplyText(e.target.value)}
                      rows={3}
                      placeholder="Write a reply to the customer…"
                    />
                  </div>
                  <div className="flex justify-end">
                    <Button
                      onClick={() => reply.mutate(replyText.trim())}
                      disabled={reply.isPending || !replyText.trim()}
                    >
                      <Send />
                      {reply.isPending ? "Sending…" : "Send reply"}
                    </Button>
                  </div>
                </TabsContent>

                <TabsContent value="note" className="mt-4">
                  <div className="space-y-3 rounded-xl border border-warning/40 bg-warning/10 p-4">
                    <div className="space-y-2">
                      <Label
                        htmlFor="note-input"
                        className="flex items-center gap-1.5 text-xs font-medium text-warning-foreground"
                      >
                        <Lock className="size-3.5" />
                        Internal note — never shown to the customer.
                      </Label>
                      <Textarea
                        id="note-input"
                        value={noteText}
                        onChange={(e) => setNoteText(e.target.value)}
                        rows={3}
                        placeholder="Add context for other agents…"
                        className="bg-background"
                      />
                    </div>
                    <div className="flex justify-end">
                      <Button
                        variant="outline"
                        onClick={() => addNote.mutate(noteText.trim())}
                        disabled={addNote.isPending || !noteText.trim()}
                      >
                        <StickyNote />
                        {addNote.isPending ? "Saving…" : "Add note"}
                      </Button>
                    </div>
                  </div>
                </TabsContent>
              </Tabs>
            </div>
          ) : (
            <div className="border-t bg-muted/20 px-6 py-4">
              <p className="text-sm text-muted-foreground">
                {canReopen
                  ? "This ticket is closed. Reopen it to continue the conversation."
                  : "Reply and internal notes unlock once this ticket is assigned to you."}
              </p>
            </div>
          )}
        </Card>

        {/* Detail sidebar */}
        <div className="space-y-6">
          <Card>
            <CardHeader>
              <CardTitle className="text-base">Details</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4 text-sm">
              <DetailRow label="State">
                <StatusBadge value={ticket.state} />
              </DetailRow>
              <DetailRow label="Priority">
                <StatusBadge value={ticket.priority} />
              </DetailRow>
              <DetailRow label="Language">
                {ticket.language ? (
                  <span className="tabular-nums uppercase">{ticket.language}</span>
                ) : (
                  <span className="text-muted-foreground">Not detected</span>
                )}
              </DetailRow>

              <Separator />

              <DetailRow label="Linked record">
                {ticket.linked_record_type ? (
                  <span className="inline-flex items-center gap-1.5">
                    <FileText className="size-3.5 text-muted-foreground" />
                    <span>{ticket.linked_record_type}</span>
                    <span className="text-muted-foreground">/</span>
                    <span className="tabular-nums">{ticket.linked_record_key}</span>
                  </span>
                ) : (
                  <span className="text-muted-foreground">None linked</span>
                )}
              </DetailRow>
              {ticket.assignee_id ? (
                <DetailRow label="Assignee">
                  <span className="tabular-nums">{ticket.assignee_id.slice(0, 8)}</span>
                </DetailRow>
              ) : null}

              <Separator />

              <DetailRow label="Created">
                <time className="tabular-nums" dateTime={ticket.created_at}>
                  {formatFull(ticket.created_at)}
                </time>
              </DetailRow>
              {ticket.resolved_at ? (
                <DetailRow label="Resolved">
                  <time className="tabular-nums" dateTime={ticket.resolved_at}>
                    {formatFull(ticket.resolved_at)}
                  </time>
                </DetailRow>
              ) : null}
              {ticket.closed_at ? (
                <DetailRow label="Closed">
                  <time className="tabular-nums" dateTime={ticket.closed_at}>
                    {formatFull(ticket.closed_at)}
                  </time>
                </DetailRow>
              ) : null}
              <DetailRow label="Ticket ID">
                <code className="rounded bg-muted px-1.5 py-0.5 text-xs tabular-nums">
                  {ticket.id}
                </code>
              </DetailRow>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-base">
                <Tag className="size-4 text-muted-foreground" />
                Tags
              </CardTitle>
              <CardDescription>Approved tags are applied; pending tags await review.</CardDescription>
            </CardHeader>
            <CardContent>
              {ticket.tags.length === 0 ? (
                <p className="text-sm text-muted-foreground">No tags yet.</p>
              ) : (
                <ul className="space-y-2.5">
                  {ticket.tags.map((t) => (
                    <li key={t.name} className="flex items-center justify-between gap-3 text-sm">
                      <span className="min-w-0 truncate font-medium">{t.name}</span>
                      <StatusBadge value={t.status} />
                    </li>
                  ))}
                </ul>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-base">
                <Sparkles className="size-4 text-muted-foreground" />
                AI context
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-4 text-sm">
              {contextQuery.isLoading ? (
                <div className="space-y-2">
                  <Skeleton className="h-4 w-24" />
                  <Skeleton className="h-4 w-full" />
                  <Skeleton className="h-4 w-3/4" />
                </div>
              ) : contextQuery.isError ? (
                <ErrorState
                  title="Couldn't load AI context"
                  message="The summary and live record failed to load."
                  onRetry={() => void contextQuery.refetch()}
                />
              ) : (
                <>
                  <div className="space-y-1">
                    <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                      Summary
                    </p>
                    {context?.ai_summary ? (
                      <p className="leading-relaxed">{context.ai_summary}</p>
                    ) : (
                      <p className="italic text-muted-foreground">Summary pending.</p>
                    )}
                  </div>

                  <div className="space-y-1">
                    <div className="flex items-center justify-between gap-2">
                      <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                        Suggested reply
                      </p>
                      {context?.suggested_reply && isWithAgent ? (
                        <Button size="xs" variant="ghost" onClick={insertSuggested}>
                          <Wand2 />
                          Insert
                        </Button>
                      ) : null}
                    </div>
                    {context?.suggested_reply ? (
                      <p className="leading-relaxed">{context.suggested_reply}</p>
                    ) : (
                      <p className="italic text-muted-foreground">Not available yet.</p>
                    )}
                  </div>

                  <Separator />

                  <div className="flex items-center justify-between gap-3">
                    <span className="text-muted-foreground">Live record</span>
                    <StatusBadge value={liveOk ? "available" : "unavailable"} />
                  </div>
                  {!liveOk && context?.live_record.reason ? (
                    <p className="text-xs text-muted-foreground">{context.live_record.reason}</p>
                  ) : null}
                </>
              )}
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}
