/** FE-Ops — the platform-operator console (M10). Cross-tenant, platform-scoped principal only.
 *
 * There is no `/ops/login`: the operator pastes a platform JWT into a gate, which `opsAuth` holds
 * for the session. Every request here uses `opsFetch` (raw fetch + operator token) — NEVER the
 * shared `@/lib/api` client, which would inject the tenant staff token. */

import { type FormEvent, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";
import {
  Activity,
  BarChart3,
  Building2,
  CheckCircle2,
  KeyRound,
  LogOut,
  MailWarning,
  RefreshCw,
  TriangleAlert,
} from "lucide-react";
import { toast } from "sonner";

import { PageHeader } from "@/components/page-header";
import { DataTable } from "@/components/data-table";
import { EmptyState } from "@/components/empty-state";
import { ErrorState } from "@/components/error-state";
import { StatTile } from "@/components/stat-tile";
import { StatusBadge } from "@/components/status-badge";
import { ConfirmDialog } from "@/components/confirm-dialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { cn } from "@/lib/utils";
import type { components } from "@/api/generated/schema";

import { clearOpsToken, getOpsToken, opsFetch, setOpsToken } from "./opsAuth";

type TenantOut = components["schemas"]["TenantOut"];
type TenantStatusPatch = components["schemas"]["TenantStatusPatchRequest"];
type HealthResponse = components["schemas"]["HealthResponse"];
type UsageResponse = components["schemas"]["UsageResponse"];

const OPS_KEYS = {
  tenants: ["ops", "tenants"] as const,
  health: ["ops", "health"] as const,
  usage: ["ops", "usage"] as const,
};

const humanize = (v: string) =>
  v.replace(/[_-]+/g, " ").replace(/^\w/, (c) => c.toUpperCase());

// ---------------------------------------------------------------------------
// Entry point: token gate → console
// ---------------------------------------------------------------------------
export function OpsPage() {
  const [token, setToken] = useState<string | null>(() => getOpsToken());

  if (!token) {
    return <TokenGate onAuthed={() => setToken(getOpsToken())} />;
  }

  return (
    <OpsConsole
      onSignOut={() => {
        clearOpsToken();
        setToken(null);
      }}
    />
  );
}

// ---------------------------------------------------------------------------
// Gate — paste a platform operator token
// ---------------------------------------------------------------------------
function TokenGate({ onAuthed }: { onAuthed: () => void }) {
  const [value, setValue] = useState("");
  const [error, setError] = useState<string | null>(null);

  function submit(e: FormEvent) {
    e.preventDefault();
    const trimmed = value.trim();
    if (!trimmed) {
      setError("Paste a platform operator token to continue.");
      return;
    }
    setOpsToken(trimmed);
    onAuthed();
  }

  return (
    <div className="grid min-h-[70vh] place-items-center">
      <Card className="w-full max-w-md">
        <CardHeader className="items-start gap-3">
          <span className="grid size-11 place-items-center rounded-full bg-secondary text-primary">
            <KeyRound className="size-5" />
          </span>
          <div className="space-y-1.5">
            <CardTitle>Paste operator token</CardTitle>
            <CardDescription>
              The platform console has no sign-in. Paste a platform-scoped JWT to run cross-tenant
              operations. It stays in this browser tab only and is cleared when you sign out.
            </CardDescription>
          </div>
        </CardHeader>
        <CardContent>
          <form className="space-y-4" onSubmit={submit} noValidate>
            <div className="space-y-2">
              <Label htmlFor="ops-token">Operator token</Label>
              <Textarea
                id="ops-token"
                value={value}
                onChange={(e) => {
                  setValue(e.target.value);
                  if (error) setError(null);
                }}
                placeholder="eyJhbGciOiJI…"
                rows={4}
                autoFocus
                spellCheck={false}
                className="resize-none font-mono text-xs"
                aria-invalid={error ? true : undefined}
                aria-describedby={error ? "ops-token-error" : undefined}
              />
              {error ? (
                <p id="ops-token-error" className="text-sm text-destructive">
                  {error}
                </p>
              ) : null}
            </div>
            <Button type="submit" className="w-full">
              Continue
            </Button>
          </form>
        </CardContent>
      </Card>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Console — tabs
// ---------------------------------------------------------------------------
function OpsConsole({ onSignOut }: { onSignOut: () => void }) {
  return (
    <>
      <PageHeader
        title="Platform operations"
        description="Cross-tenant administration: tenant lifecycle, delivery health, and usage."
        actions={
          <Button variant="outline" onClick={onSignOut}>
            <LogOut />
            Sign out operator
          </Button>
        }
      />

      <Tabs defaultValue="tenants" className="w-full">
        <TabsList>
          <TabsTrigger value="tenants">
            <Building2 />
            Tenants
          </TabsTrigger>
          <TabsTrigger value="health">
            <Activity />
            Health
          </TabsTrigger>
          <TabsTrigger value="usage">
            <BarChart3 />
            Usage
          </TabsTrigger>
        </TabsList>

        <TabsContent value="tenants" className="mt-6">
          <TenantsTab />
        </TabsContent>
        <TabsContent value="health" className="mt-6">
          <HealthTab />
        </TabsContent>
        <TabsContent value="usage" className="mt-6">
          <UsageTab />
        </TabsContent>
      </Tabs>
    </>
  );
}

// ---------------------------------------------------------------------------
// Tenants
// ---------------------------------------------------------------------------
function TenantsTab() {
  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: OPS_KEYS.tenants,
    queryFn: () => opsGet<TenantOut[]>("/api/v1/ops/tenants"),
  });

  const columns = useMemo<ColumnDef<TenantOut>[]>(
    () => [
      {
        accessorKey: "name",
        header: "Tenant",
        cell: ({ row }) => (
          <div className="flex flex-col gap-0.5">
            <span className="font-medium text-foreground">{row.original.name}</span>
            <span className="font-mono text-xs text-muted-foreground tabular-nums">
              {row.original.id}
            </span>
          </div>
        ),
      },
      {
        accessorKey: "industry",
        header: "Industry",
        cell: ({ row }) => <Badge variant="outline">{humanize(row.original.industry)}</Badge>,
      },
      {
        accessorKey: "status",
        header: "Status",
        cell: ({ row }) => <StatusBadge value={row.original.status} />,
      },
      {
        id: "actions",
        header: () => <span className="sr-only">Actions</span>,
        enableSorting: false,
        cell: ({ row }) => <TenantRowActions tenant={row.original} />,
      },
    ],
    []
  );

  return (
    <DataTable
      columns={columns}
      data={data ?? []}
      loading={isLoading}
      error={isError}
      onRetry={() => void refetch()}
      empty={
        <EmptyState
          icon={Building2}
          title="No tenants yet"
          description="Businesses appear here once they sign up for the platform."
        />
      }
    />
  );
}

/** Suspend / reactivate a tenant, each PATCHing `/ops/tenants/{id}` and confirmed via ConfirmDialog. */
function TenantRowActions({ tenant }: { tenant: TenantOut }) {
  const queryClient = useQueryClient();
  const suspended = tenant.status === "suspended";

  const mutation = useMutation({
    mutationFn: (body: TenantStatusPatch) =>
      opsPatch<TenantOut>(`/api/v1/ops/tenants/${tenant.id}`, body),
    onSuccess: (_data, body) => {
      toast.success(body.status === "suspended" ? "Tenant suspended" : "Tenant reactivated");
      void queryClient.invalidateQueries({ queryKey: OPS_KEYS.tenants });
    },
    onError: (err: unknown) => {
      toast.error(err instanceof Error ? err.message : "Update failed");
    },
  });

  return (
    <div className="flex items-center justify-end">
      {suspended ? (
        <ConfirmDialog
          trigger={
            <Button variant="outline" size="sm" disabled={mutation.isPending}>
              Reactivate
            </Button>
          }
          title="Reactivate tenant?"
          description={`${tenant.name} will be able to sign in and start new chat sessions again immediately.`}
          confirmText="Reactivate"
          onConfirm={() => mutation.mutate({ status: "active", reason: null })}
        />
      ) : (
        <ConfirmDialog
          trigger={
            <Button variant="outline" size="sm" disabled={mutation.isPending}>
              Suspend
            </Button>
          }
          title="Suspend tenant?"
          description={`${tenant.name} will be blocked from staff sign-in and new chat sessions until reactivated. In-flight sessions are not force-closed.`}
          confirmText="Suspend"
          destructive
          onConfirm={() =>
            mutation.mutate({
              status: "suspended",
              reason: "Suspended from the platform operator console",
            })
          }
        />
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Health
// ---------------------------------------------------------------------------
function HealthTab() {
  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: OPS_KEYS.health,
    queryFn: () => opsGet<HealthResponse>("/api/v1/ops/health"),
  });

  if (isLoading) return <CardGridSkeleton count={3} />;
  if (isError || !data) {
    return (
      <ErrorState
        title="Couldn't load health"
        message="The platform health check failed. Check the operator token and try again."
        onRetry={() => void refetch()}
      />
    );
  }

  const healthy = data.email_dlq_depth === 0 && data.recent_send_failures === 0;

  return (
    <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
      <StatTile
        icon={MailWarning}
        label="Email DLQ depth"
        value={data.email_dlq_depth.toLocaleString()}
        hint="Dead-lettered messages that exhausted retries and need operator attention."
        alert={data.email_dlq_depth > 0}
      />
      <StatTile
        icon={RefreshCw}
        label="Recent send failures"
        value={data.recent_send_failures.toLocaleString()}
        hint="Emails that failed at least once and are still backing off for retry."
        alert={data.recent_send_failures > 0}
      />
      <Card className={cn("justify-center", healthy ? "border-success/30" : "border-warning/40")}>
        <CardContent className="flex items-center gap-4">
          <span
            className={cn(
              "grid size-11 shrink-0 place-items-center rounded-full",
              healthy ? "bg-success/12 text-success" : "bg-warning/20 text-warning-foreground"
            )}
          >
            {healthy ? (
              <CheckCircle2 className="size-6" />
            ) : (
              <TriangleAlert className="size-6" />
            )}
          </span>
          <div className="space-y-0.5">
            <div className="font-medium">
              {healthy ? "All systems healthy" : "Needs attention"}
            </div>
            <p className="text-sm text-muted-foreground">
              {healthy
                ? "Email delivery is flowing with no backlog."
                : "One or more delivery signals are non-zero."}
            </p>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Usage
// ---------------------------------------------------------------------------
function UsageTab() {
  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: OPS_KEYS.usage,
    queryFn: () => opsGet<UsageResponse>("/api/v1/ops/usage"),
  });

  if (isLoading) return <CardGridSkeleton count={1} />;
  if (isError || !data) {
    return (
      <ErrorState
        title="Couldn't load usage"
        message="The usage report failed to load. Check the operator token and try again."
        onRetry={() => void refetch()}
      />
    );
  }

  if (data.status !== "ok") {
    return (
      <EmptyState
        icon={BarChart3}
        title="Usage rollups aren't wired yet"
        description={
          data.reason ??
          "Per-tenant usage aggregation (M8 analytics) isn't available in this build yet."
        }
      />
    );
  }

  const rows = data.tenants ?? [];
  if (rows.length === 0) {
    return (
      <EmptyState
        icon={BarChart3}
        title="No usage recorded"
        description="No tenant usage has been aggregated for the current period."
      />
    );
  }

  const keys = Array.from(new Set(rows.flatMap((r) => Object.keys(r))));

  return (
    <div className="overflow-hidden rounded-xl border bg-card">
      <div className="overflow-x-auto">
        <Table>
          <TableHeader>
            <TableRow className="hover:bg-transparent">
              {keys.map((k) => (
                <TableHead key={k} className="whitespace-nowrap">
                  {humanize(k)}
                </TableHead>
              ))}
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((row, i) => (
              <TableRow key={i} className="hover:bg-transparent">
                {keys.map((k) => {
                  const v = row[k];
                  return (
                    <TableCell key={k} className={cn(typeof v === "number" && "tabular-nums")}>
                      {formatCell(v)}
                    </TableCell>
                  );
                })}
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
    </div>
  );
}

function formatCell(v: unknown): string {
  if (v == null) return "—";
  if (typeof v === "number") return v.toLocaleString();
  if (typeof v === "boolean") return v ? "Yes" : "No";
  if (typeof v === "object") return JSON.stringify(v);
  return String(v);
}

// ---------------------------------------------------------------------------
// Shared
// ---------------------------------------------------------------------------
function CardGridSkeleton({ count }: { count: number }) {
  return (
    <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
      {Array.from({ length: count }).map((_, i) => (
        <Card key={i}>
          <CardContent className="space-y-3">
            <Skeleton className="h-4 w-28" />
            <Skeleton className="h-8 w-16" />
            <Skeleton className="h-3 w-full max-w-[200px]" />
          </CardContent>
        </Card>
      ))}
    </div>
  );
}

// Thin wrappers around opsFetch so queryFn/mutationFn stay tidy. These deliberately bypass the
// shared api client — the operator token must not be replaced by the staff token.
function opsGet<T>(path: string): Promise<T> {
  return opsFetch<T>(path);
}

function opsPatch<T>(path: string, body: unknown): Promise<T> {
  return opsFetch<T>(path, { method: "PATCH", body: JSON.stringify(body) });
}
