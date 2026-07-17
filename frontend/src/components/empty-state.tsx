import type { LucideIcon } from "lucide-react";
import { Inbox } from "lucide-react";
import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

interface EmptyStateProps {
  icon?: LucideIcon;
  title: string;
  description?: ReactNode;
  action?: ReactNode;
  className?: string;
}

/** Friendly empty state: icon + one-line explanation + an optional primary action. Use for
 * "nothing created yet" (with a CTA) and "no results" (with a clear-filters action). */
export function EmptyState({ icon: Icon = Inbox, title, description, action, className }: EmptyStateProps) {
  return (
    <div
      className={cn(
        "flex flex-col items-center justify-center rounded-xl border border-dashed bg-card/50 px-6 py-14 text-center",
        className
      )}
    >
      <div className="mb-4 grid size-11 place-items-center rounded-full bg-secondary text-muted-foreground">
        <Icon className="size-5" />
      </div>
      <h3 className="text-sm font-medium">{title}</h3>
      {description ? (
        <p className="mt-1 max-w-sm text-xs text-muted-foreground">{description}</p>
      ) : null}
      {action ? <div className="mt-5">{action}</div> : null}
    </div>
  );
}
