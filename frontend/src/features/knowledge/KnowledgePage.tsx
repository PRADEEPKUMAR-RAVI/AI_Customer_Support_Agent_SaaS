/** FE-Knowledge admin screen: add sources (file/paste/URL) + a live ingestion-status list. */

import { useEffect } from "react";

import { NoAccessState } from "@/components/no-access-state";
import { usePageBanner } from "@/lib/pageBanner";

import { useAuth } from "../../app/providers";
import { hasPermission } from "../../lib/rbac";
import { SourceList } from "./SourceList";
import { UploadForm } from "./UploadForm";

export function KnowledgePage() {
  const { role } = useAuth();
  // Deny only when the role is known and lacks the permission. Role is null until the SPA
  // derives it from the JWT (FE-Shell TODO), so a null role passes through for the POC.
  const canManage = !role || hasPermission(role, "kb:manage");

  useEffect(() => {
    usePageBanner.getState().set({
      title: "Knowledge base",
      subtitle: canManage
        ? "Add and manage the docs, FAQs, and pages your agent answers from."
        : "The content your agent answers from.",
    });
    return () => usePageBanner.getState().clear();
  }, [canManage]);

  if (!canManage) {
    return (
      <NoAccessState description="You don't have permission to manage the knowledge base. Ask an admin for the kb:manage permission." />
    );
  }

  return (
    <>
      <div className="flex justify-end pb-6">
        <UploadForm />
      </div>
      <SourceList />
    </>
  );
}
