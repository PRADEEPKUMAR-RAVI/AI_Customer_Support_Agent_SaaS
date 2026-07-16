import { ShieldAlert } from "lucide-react";

import { EmptyState } from "@/components/empty-state";

interface NoAccessStateProps {
  description?: string;
  className?: string;
}

/** Canonical "you don't have permission" placeholder — used both standalone (the router's
 * route-level `Guard`) and beneath a `PageHeader` (a feature page gated by one specific
 * permission). Consolidates what used to be four near-identical inline copies plus a differently
 * worded version in the router. */
export function NoAccessState({
  description = "Your role doesn't have permission to view this page. Ask an admin if you need it.",
  className,
}: NoAccessStateProps) {
  return (
    <EmptyState icon={ShieldAlert} title="No access" description={description} className={className} />
  );
}
