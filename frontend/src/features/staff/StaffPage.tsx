/** FE-Staff — admin-only invite/manage staff. Mounted at `/admin/staff`. */

import type { FormEvent } from "react";
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { Button, Card, Spinner } from "../../components";
import { api, unwrap } from "../../lib/api";

interface Staff {
  id: string;
  email: string;
  role: string;
  is_active: boolean;
  email_verified: boolean;
}

const STAFF_QUERY_KEY = ["staff"];

export function StaffPage() {
  const queryClient = useQueryClient();
  const [inviteError, setInviteError] = useState<string | null>(null);

  const { data: staff, isLoading, isError } = useQuery({
    queryKey: STAFF_QUERY_KEY,
    queryFn: async () => unwrap<Staff[]>(await api.GET("/api/v1/admin/staff")),
  });

  const invite = useMutation({
    mutationFn: async (body: { email: string; role: string }) =>
      unwrap(await api.POST("/api/v1/admin/staff", { body })),
    onSuccess: () => {
      setInviteError(null);
      void queryClient.invalidateQueries({ queryKey: STAFF_QUERY_KEY });
    },
    onError: (err: unknown) => {
      setInviteError(err instanceof Error ? err.message : "Invite failed");
    },
  });

  const setActive = useMutation({
    mutationFn: async ({ id, is_active }: { id: string; is_active: boolean }) =>
      unwrap(
        await api.PATCH("/api/v1/admin/staff/{staff_id}", {
          params: { path: { staff_id: id } },
          body: { is_active },
        })
      ),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: STAFF_QUERY_KEY }),
  });

  function handleInvite(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = e.currentTarget;
    const email = (form.elements.namedItem("email") as HTMLInputElement).value;
    const role = (form.elements.namedItem("role") as HTMLSelectElement).value;
    invite.mutate({ email, role }, { onSuccess: () => form.reset() });
  }

  return (
    <Card>
      <h2>Staff</h2>
      <form
        onSubmit={handleInvite}
        style={{ display: "flex", gap: 8, marginBottom: 16, alignItems: "center" }}
      >
        <input name="email" type="email" placeholder="new-teammate@company.com" required />
        <select name="role" defaultValue="agent">
          <option value="agent">Agent</option>
          <option value="admin">Admin</option>
        </select>
        <Button type="submit" disabled={invite.isPending}>
          {invite.isPending ? "Inviting…" : "Invite"}
        </Button>
      </form>
      {inviteError && (
        <p role="alert" style={{ color: "#dc2626" }}>
          {inviteError}
        </p>
      )}

      {isLoading && <Spinner />}
      {isError && <p role="alert" style={{ color: "#dc2626" }}>Failed to load staff.</p>}
      {staff && staff.length === 0 && <p>No staff invited yet.</p>}
      {staff && staff.length > 0 && (
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 14 }}>
          <thead>
            <tr style={{ textAlign: "left", borderBottom: "1px solid #e5e7eb" }}>
              <th style={{ padding: "6px 4px" }}>Email</th>
              <th style={{ padding: "6px 4px" }}>Role</th>
              <th style={{ padding: "6px 4px" }}>Status</th>
              <th style={{ padding: "6px 4px" }}>Verified</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {staff.map((s) => (
              <tr key={s.id} style={{ borderBottom: "1px solid #f3f4f6" }}>
                <td style={{ padding: "6px 4px" }}>{s.email}</td>
                <td style={{ padding: "6px 4px" }}>{s.role}</td>
                <td style={{ padding: "6px 4px" }}>{s.is_active ? "Active" : "Deactivated"}</td>
                <td style={{ padding: "6px 4px" }}>{s.email_verified ? "Yes" : "Pending"}</td>
                <td style={{ padding: "6px 4px" }}>
                  <Button
                    variant="ghost"
                    disabled={setActive.isPending}
                    onClick={() => setActive.mutate({ id: s.id, is_active: !s.is_active })}
                  >
                    {s.is_active ? "Deactivate" : "Reactivate"}
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
