/** Connector management screen — one row per configured live source, with health, and
 * test / edit / delete actions. The create/edit form is `ConnectorForm` in a dialog; testing a
 * saved connector runs the stored-credential test endpoint. Mounted in the Records "Connectors"
 * tab in place of the old always-blank single form. */

import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Database, Pencil, Plug, Plus, TestTube2, Trash2, Webhook } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Badge } from "@/components/ui/badge";
import { ConfirmDialog } from "@/components/confirm-dialog";
import { EmptyState } from "@/components/empty-state";
import { ErrorState } from "@/components/error-state";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

import { ConnectorForm } from "./ConnectorForm";
import {
  CONNECTORS_KEY,
  deleteConnector,
  getConnector,
  listConnectors,
  patchConnector,
  testConnector,
  type ConnectorDetail,
  type ConnectorListItem,
  type RecordSchemaOut,
} from "./api";

function titleCase(v: string): string {
  return v.replace(/[_-]+/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

function relativeTime(iso: string | null | undefined): string {
  if (!iso) return "Never tested";
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "Never tested";
  const secs = Math.max(0, Math.round((Date.now() - then) / 1000));
  if (secs < 60) return "Tested just now";
  const mins = Math.round(secs / 60);
  if (mins < 60) return `Tested ${mins} min ago`;
  const hours = Math.round(mins / 60);
  if (hours < 24) return `Tested ${hours} h ago`;
  return `Tested ${Math.round(hours / 24)} d ago`;
}

function HealthBadge({ ok }: { ok: boolean | null | undefined }) {
  const cfg =
    ok === true
      ? { cls: "bg-success/12 text-success", dot: "bg-success", label: "Healthy" }
      : ok === false
        ? { cls: "bg-destructive/12 text-destructive", dot: "bg-destructive", label: "Failing" }
        : { cls: "bg-secondary text-muted-foreground", dot: "bg-muted-foreground/60", label: "Not tested" };
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-medium whitespace-nowrap",
        cfg.cls
      )}
    >
      <span className={cn("size-1.5 rounded-full", cfg.dot)} />
      {cfg.label}
    </span>
  );
}

/** Small dialog that collects a lookup value and runs the stored-credential test for a connector. */
function TestConnectorDialog({
  connector,
  open,
  onOpenChange,
  onDone,
}: {
  connector: ConnectorListItem | null;
  open: boolean;
  onOpenChange: (v: boolean) => void;
  onDone: () => void;
}) {
  const [key, setKey] = useState("");
  const run = useMutation({
    mutationFn: () => testConnector(connector!.id, key.trim()),
    onSuccess: (r) => {
      if (r.ok) toast.success(`${titleCase(connector!.record_type)} — test passed`);
      else toast.error(r.error ?? "Test failed");
      onDone();
      onOpenChange(false);
      setKey("");
    },
    onError: (e) => toast.error(e instanceof Error ? e.message : "Test failed"),
  });

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Test {connector ? titleCase(connector.record_type) : ""} connector</DialogTitle>
          <DialogDescription>
            Enter a known lookup value; it runs against the stored credentials and updates the health
            status.
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-2">
          <Label htmlFor="test-key">Lookup value</Label>
          <Input
            id="test-key"
            placeholder="e.g. an existing order id"
            value={key}
            onChange={(e) => setKey(e.target.value)}
          />
        </div>
        <div className="flex justify-end gap-2">
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button disabled={!key.trim() || run.isPending} onClick={() => run.mutate()}>
            {run.isPending ? "Testing…" : "Run test"}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}

export function ConnectorList({ schemas }: { schemas: RecordSchemaOut[] }) {
  const qc = useQueryClient();
  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: CONNECTORS_KEY,
    queryFn: listConnectors,
  });

  const [formOpen, setFormOpen] = useState(false);
  const [editDetail, setEditDetail] = useState<ConnectorDetail | null>(null);
  const [testTarget, setTestTarget] = useState<ConnectorListItem | null>(null);
  const [testOpen, setTestOpen] = useState(false);

  const invalidate = () => void qc.invalidateQueries({ queryKey: CONNECTORS_KEY });

  const openCreate = () => {
    setEditDetail(null);
    setFormOpen(true);
  };

  const edit = useMutation({
    mutationFn: (id: string) => getConnector(id),
    onSuccess: (detail) => {
      setEditDetail(detail);
      setFormOpen(true);
    },
    onError: (e) => toast.error(e instanceof Error ? e.message : "Couldn't load connector"),
  });

  const remove = useMutation({
    mutationFn: (id: string) => deleteConnector(id),
    onSuccess: () => {
      toast.success("Connector deleted");
      invalidate();
    },
    onError: (e) => toast.error(e instanceof Error ? e.message : "Delete failed"),
  });

  // Enabling one connector auto-pauses its siblings server-side; refetch to reflect the new active
  // source across the whole group. At most one is active per record type (DB-enforced).
  const toggle = useMutation({
    mutationFn: ({ id, enabled }: { id: string; enabled: boolean }) =>
      patchConnector(id, { enabled }),
    onSuccess: () => invalidate(),
    onError: (e) => toast.error(e instanceof Error ? e.message : "Couldn't update the source"),
  });

  const connectors = data ?? [];

  // One card per record type: many connectors may share a type, but only one is the live source.
  const grouped = useMemo(() => {
    const m = new Map<string, ConnectorListItem[]>();
    for (const c of connectors) m.set(c.record_type, [...(m.get(c.record_type) ?? []), c]);
    return [...m.entries()];
  }, [connectors]);

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between gap-3">
        <p className="text-sm text-muted-foreground">
          Live sources the AI reads from on every lookup. Keep several per record type, but only one
          is active at a time — it overrides the uploaded dataset; pause it to fall back.
        </p>
        <Button onClick={openCreate}>
          <Plus className="size-4" />
          Connect a live source
        </Button>
      </div>

      {isLoading ? (
        <div className="space-y-2">
          <Skeleton className="h-20 w-full rounded-xl" />
          <Skeleton className="h-20 w-full rounded-xl" />
        </div>
      ) : isError ? (
        <ErrorState message="Couldn't load your connectors." onRetry={() => void refetch()} />
      ) : connectors.length === 0 ? (
        <EmptyState
          icon={Plug}
          title="No live sources yet"
          description="Connect a database or API so the AI can look up and verify records in real time instead of an uploaded file."
        />
      ) : (
        <div className="space-y-4">
          {grouped.map(([recordType, group]) => {
            const noneActive = !group.some((c) => c.enabled);
            return (
              <div key={recordType} className="overflow-hidden rounded-xl border bg-card">
                <div className="flex items-center justify-between gap-2 border-b bg-muted/30 px-4 py-2">
                  <span className="text-sm font-medium">{titleCase(recordType)}</span>
                  <span className="text-[11px] text-muted-foreground">
                    {noneActive
                      ? "Paused · falls back to uploaded dataset"
                      : group.length > 1
                        ? `1 of ${group.length} active`
                        : "Active"}
                  </span>
                </div>
                <ul className="divide-y">
                  {group.map((c) => (
                    <li
                      key={c.id}
                      className={cn(
                        "flex flex-wrap items-center gap-4 px-4 py-3.5",
                        !c.enabled && "opacity-60"
                      )}
                    >
                      <span className="grid size-9 shrink-0 place-items-center rounded-lg bg-accent/60 text-primary">
                        {c.source_type === "db" ? <Database className="size-4" /> : <Webhook className="size-4" />}
                      </span>
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-2">
                          <Badge variant="outline" className="shrink-0 text-[10px] font-normal uppercase tracking-wide">
                            {c.source_type === "db" ? "Live DB" : "Live API"}
                          </Badge>
                          <span className="truncate text-sm">{c.summary}</span>
                        </div>
                      </div>
                      <div className="flex flex-col items-end gap-1">
                        <HealthBadge ok={c.last_test_ok} />
                        <span className="text-[11px] tabular-nums text-muted-foreground">
                          {relativeTime(c.last_tested_at)}
                        </span>
                      </div>
                      <label className="flex items-center gap-2">
                        <span className="text-[11px] font-medium text-muted-foreground">
                          {c.enabled ? "Active" : "Paused"}
                        </span>
                        <Switch
                          checked={c.enabled}
                          disabled={toggle.isPending}
                          onCheckedChange={(v) => toggle.mutate({ id: c.id, enabled: v })}
                          aria-label={`${c.enabled ? "Pause" : "Activate"} the ${titleCase(c.record_type)} ${c.source_type === "db" ? "database" : "API"} source`}
                        />
                      </label>
                      <div className="flex items-center gap-1">
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => {
                            setTestTarget(c);
                            setTestOpen(true);
                          }}
                        >
                          <TestTube2 className="size-4" />
                          Test
                        </Button>
                        <Button
                          variant="ghost"
                          size="icon-sm"
                          aria-label={`Edit ${c.record_type} connector`}
                          disabled={edit.isPending}
                          onClick={() => edit.mutate(c.id)}
                        >
                          <Pencil className="size-4" />
                        </Button>
                        <ConfirmDialog
                          trigger={
                            <Button variant="ghost" size="icon-sm" aria-label={`Delete ${c.record_type} connector`}>
                              <Trash2 className="size-4" />
                            </Button>
                          }
                          title="Delete this connector?"
                          description={`This source will be removed. ${titleCase(c.record_type)} falls back to its uploaded dataset (if any); otherwise lookups return not-found.`}
                          confirmText="Delete"
                          destructive
                          onConfirm={() => remove.mutate(c.id)}
                        />
                      </div>
                    </li>
                  ))}
                </ul>
              </div>
            );
          })}
        </div>
      )}

      {/* Create / edit form */}
      <Dialog open={formOpen} onOpenChange={setFormOpen}>
        <DialogContent className="max-h-[85vh] overflow-y-auto sm:max-w-2xl">
          <DialogHeader>
            <DialogTitle>{editDetail ? "Edit connector" : "Connect a live source"}</DialogTitle>
            <DialogDescription>
              Map your source onto the record schema, then validate a lookup before saving.
            </DialogDescription>
          </DialogHeader>
          <ConnectorForm
            schemas={schemas}
            existing={editDetail}
            onSaved={() => {
              setFormOpen(false);
              setEditDetail(null);
              invalidate();
            }}
          />
        </DialogContent>
      </Dialog>

      <TestConnectorDialog
        connector={testTarget}
        open={testOpen}
        onOpenChange={setTestOpen}
        onDone={invalidate}
      />
    </div>
  );
}
