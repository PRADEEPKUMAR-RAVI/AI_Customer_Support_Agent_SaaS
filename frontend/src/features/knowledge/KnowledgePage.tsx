/** FE-Knowledge admin screen: upload/paste sources + live ingestion-status list. */

import { useAuth } from "../../app/providers";
import { Card } from "../../components";
import { hasPermission } from "../../lib/rbac";
import { SourceList } from "./SourceList";
import { UploadForm } from "./UploadForm";

export function KnowledgePage() {
  const { role } = useAuth();
  // Deny only when the role is known and lacks the permission. Role is null until the SPA
  // derives it from the JWT (FE-Shell TODO), so a null role passes through for the POC.
  if (role && !hasPermission(role, "kb:manage")) {
    return (
      <Card>
        <p>You don't have permission to manage the knowledge base.</p>
      </Card>
    );
  }
  return (
    <div style={{ display: "grid", gap: 16, maxWidth: 760 }}>
      <h2>Knowledge base</h2>
      <UploadForm />
      <SourceList />
    </div>
  );
}
