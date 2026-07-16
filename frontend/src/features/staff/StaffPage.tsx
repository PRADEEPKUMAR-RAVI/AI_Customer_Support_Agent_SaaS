/** FE-Staff — admin-only invite/manage staff. Mounted at `/admin/staff`. */

import { useMemo, useState } from "react";
import { zodResolver } from "@hookform/resolvers/zod";
import { useForm } from "react-hook-form";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";
import { UserPlus, Users } from "lucide-react";
import { toast } from "sonner";
import { z } from "zod";

import { PageHeader } from "@/components/page-header";
import { DataTable } from "@/components/data-table";
import { EmptyState } from "@/components/empty-state";
import { StatusBadge } from "@/components/status-badge";
import { ConfirmDialog } from "@/components/confirm-dialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import {
  Form,
  FormControl,
  FormDescription,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from "@/components/ui/form";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { api, unwrap } from "@/lib/api";
import type { components } from "@/api/generated/schema";

type Staff = components["schemas"]["StaffResponse"];
type StaffUpdate = components["schemas"]["StaffUpdateRequest"];

const STAFF_QUERY_KEY = ["admin", "staff"] as const;
const ROLES = ["admin", "agent"] as const;

function titleCase(value: string): string {
  return value.replace(/[_-]+/g, " ").replace(/^\w/, (c) => c.toUpperCase());
}

function roleBadgeVariant(role: string): "default" | "secondary" | "outline" {
  if (role === "admin") return "default";
  if (role === "agent") return "secondary";
  return "outline";
}

export function StaffPage() {
  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: STAFF_QUERY_KEY,
    queryFn: async () => unwrap<Staff[]>(await api.GET("/api/v1/admin/staff")),
  });

  const columns = useMemo<ColumnDef<Staff>[]>(
    () => [
      {
        accessorKey: "email",
        header: "Teammate",
        cell: ({ row }) => {
          const s = row.original;
          return (
            <div className="flex flex-col gap-0.5">
              <span className="font-medium text-foreground">{s.email}</span>
              <span className="text-xs text-muted-foreground">
                {s.email_verified ? "Email verified" : "Invitation pending"}
              </span>
            </div>
          );
        },
      },
      {
        accessorKey: "role",
        header: "Role",
        cell: ({ row }) => (
          <Badge variant={roleBadgeVariant(row.original.role)}>
            {titleCase(row.original.role)}
          </Badge>
        ),
      },
      {
        id: "status",
        header: "Status",
        accessorFn: (row) => (row.is_active ? "active" : "suspended"),
        cell: ({ row }) => (
          <StatusBadge value={row.original.is_active ? "active" : "suspended"} />
        ),
      },
      {
        id: "actions",
        header: () => <span className="sr-only">Actions</span>,
        enableSorting: false,
        cell: ({ row }) => <StaffRowActions staff={row.original} />,
      },
    ],
    []
  );

  return (
    <>
      <PageHeader
        title="Staff"
        description="Invite teammates and manage who can access the support console."
        actions={<InviteTeammateDialog />}
      />
      <DataTable
        columns={columns}
        data={data ?? []}
        loading={isLoading}
        error={isError}
        onRetry={() => void refetch()}
        empty={
          <EmptyState
            icon={Users}
            title="No teammates yet"
            description="Invite an admin or agent to help resolve customer conversations."
            action={<InviteTeammateDialog />}
          />
        }
      />
    </>
  );
}

/** Per-row role change + activate/deactivate, each PATCHing `/admin/staff/{id}`. */
function StaffRowActions({ staff }: { staff: Staff }) {
  const queryClient = useQueryClient();

  const update = useMutation({
    mutationFn: async (patch: StaffUpdate) =>
      unwrap<Staff>(
        await api.PATCH("/api/v1/admin/staff/{staff_id}", {
          params: { path: { staff_id: staff.id } },
          body: patch,
        })
      ),
    onSuccess: (_data, patch) => {
      const message =
        patch.is_active === false
          ? "Teammate deactivated"
          : patch.is_active === true
            ? "Teammate reactivated"
            : "Role updated";
      toast.success(message);
      void queryClient.invalidateQueries({ queryKey: STAFF_QUERY_KEY });
    },
    onError: (err: unknown) => {
      toast.error(err instanceof Error ? err.message : "Update failed");
    },
  });

  // Re-issue a fresh invite email for a teammate who hasn't accepted yet (lost/expired link).
  const resend = useMutation({
    mutationFn: async () =>
      unwrap<Staff>(
        await api.POST("/api/v1/admin/staff/{staff_id}/resend-invite", {
          params: { path: { staff_id: staff.id } },
        })
      ),
    onSuccess: () => {
      toast.success("Invite re-sent", {
        description: `A fresh invite email is on its way to ${staff.email}.`,
      });
      void queryClient.invalidateQueries({ queryKey: STAFF_QUERY_KEY });
    },
    onError: (err: unknown) => {
      toast.error(err instanceof Error ? err.message : "Couldn't resend the invite");
    },
  });

  // Ensure the current role is always selectable even if it's outside the standard set.
  const roleOptions = useMemo(
    () => Array.from(new Set<string>([...ROLES, staff.role])),
    [staff.role]
  );

  const busy = update.isPending || resend.isPending;

  return (
    <div className="flex items-center justify-end gap-2">
      <Select
        value={staff.role}
        disabled={busy}
        onValueChange={(role) => {
          if (role !== staff.role) update.mutate({ role });
        }}
      >
        <SelectTrigger
          size="sm"
          className="w-[116px]"
          aria-label={`Change role for ${staff.email}`}
        >
          <SelectValue />
        </SelectTrigger>
        <SelectContent align="end">
          {roleOptions.map((role) => (
            <SelectItem key={role} value={role}>
              {titleCase(role)}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>

      {!staff.email_verified ? (
        <Button
          variant="outline"
          size="sm"
          disabled={busy}
          onClick={() => resend.mutate()}
          title="Send a fresh invite email (their link expired or was lost)"
        >
          {resend.isPending ? "Sending…" : "Resend invite"}
        </Button>
      ) : null}

      {staff.is_active ? (
        <ConfirmDialog
          trigger={
            <Button variant="outline" size="sm" disabled={busy}>
              Deactivate
            </Button>
          }
          title="Deactivate teammate?"
          description={`${staff.email} will immediately lose access to the console until reactivated.`}
          confirmText="Deactivate"
          destructive
          onConfirm={() => update.mutate({ is_active: false })}
        />
      ) : (
        <Button
          variant="outline"
          size="sm"
          disabled={busy}
          onClick={() => update.mutate({ is_active: true })}
        >
          Reactivate
        </Button>
      )}
    </div>
  );
}

const inviteSchema = z.object({
  email: z.string().min(1, "Email is required").email("Enter a valid email address"),
  role: z.enum(ROLES),
});

type InviteValues = z.infer<typeof inviteSchema>;

/** Invite dialog: react-hook-form + zod → POST `/admin/staff`. */
function InviteTeammateDialog() {
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);

  const form = useForm<InviteValues>({
    resolver: zodResolver(inviteSchema),
    defaultValues: { email: "", role: "agent" },
  });

  const invite = useMutation({
    mutationFn: async (values: InviteValues) =>
      unwrap<Staff>(await api.POST("/api/v1/admin/staff", { body: values })),
    onSuccess: (_data, values) => {
      toast.success(`Invitation sent to ${values.email}`);
      void queryClient.invalidateQueries({ queryKey: STAFF_QUERY_KEY });
      setOpen(false);
      form.reset();
    },
    onError: (err: unknown) => {
      toast.error(err instanceof Error ? err.message : "Invite failed");
    },
  });

  function handleOpenChange(next: boolean) {
    setOpen(next);
    if (!next) form.reset();
  }

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogTrigger asChild>
        <Button>
          <UserPlus />
          Invite teammate
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Invite teammate</DialogTitle>
          <DialogDescription>
            Send an invitation to join your team. They&apos;ll receive an email to set up their
            account.
          </DialogDescription>
        </DialogHeader>

        <Form {...form}>
          <form
            className="space-y-4"
            onSubmit={form.handleSubmit((values) => invite.mutate(values))}
          >
            <FormField
              control={form.control}
              name="email"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Email</FormLabel>
                  <FormControl>
                    <Input
                      type="email"
                      autoComplete="off"
                      placeholder="teammate@company.com"
                      {...field}
                    />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />

            <FormField
              control={form.control}
              name="role"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Role</FormLabel>
                  <Select value={field.value} onValueChange={field.onChange}>
                    <FormControl>
                      <SelectTrigger className="w-full">
                        <SelectValue placeholder="Select a role" />
                      </SelectTrigger>
                    </FormControl>
                    <SelectContent>
                      <SelectItem value="admin">Admin</SelectItem>
                      <SelectItem value="agent">Agent</SelectItem>
                    </SelectContent>
                  </Select>
                  <FormDescription>
                    Admins manage settings and teammates. Agents handle conversations.
                  </FormDescription>
                  <FormMessage />
                </FormItem>
              )}
            />

            <DialogFooter>
              <DialogClose asChild>
                <Button type="button" variant="outline">
                  Cancel
                </Button>
              </DialogClose>
              <Button type="submit" disabled={invite.isPending}>
                {invite.isPending ? "Sending…" : "Send invitation"}
              </Button>
            </DialogFooter>
          </form>
        </Form>
      </DialogContent>
    </Dialog>
  );
}
