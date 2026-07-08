/** FE-Knowledge admin screen: add sources (file/paste/URL) + a live ingestion-status list. */

import { ShieldAlert } from "lucide-react";

import { EmptyState } from "@/components/empty-state";
import { PageHeader } from "@/components/page-header";

import { useAuth } from "../../app/providers";
import { hasPermission } from "../../lib/rbac";
import { SourceList } from "./SourceList";
import { UploadForm } from "./UploadForm";

export function KnowledgePage() {
  const { role } = useAuth();
  // Deny only when the role is known and lacks the permission. Role is null until the SPA
  // derives it from the JWT (FE-Shell TODO), so a null role passes through for the POC.
  if (role && !hasPermission(role, "kb:manage")) {
    return (
      <>
        <PageHeader
          title="Knowledge base"
          description="Sources the assistant is grounded in."
        />
        <EmptyState
          icon={ShieldAlert}
          title="No access"
          description="You don't have permission to manage the knowledge base. Ask an admin for the kb:manage permission."
        />
      </>
    );
  }

  return (
    <>
      <PageHeader
        title="Knowledge base"
        description="Add and manage the sources the assistant answers from. Everything is chunked, embedded, and searched per tenant."
        actions={<UploadForm />}
      />
      <SourceList />
    </>
  );
}
