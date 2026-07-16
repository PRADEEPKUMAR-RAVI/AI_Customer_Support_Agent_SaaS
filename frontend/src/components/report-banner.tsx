import { AlertCircle, CheckCircle2 } from "lucide-react";
import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

interface ReportBannerProps {
  ok: boolean;
  heading: ReactNode;
  children?: ReactNode;
  className?: string;
}

/** Canonical ok/fail report box: colored border + icon + heading, with room underneath for
 * detail content (row errors, missing headers, a connector's per-check list, ...). Consolidates
 * what used to be three hand-rolled variants (the dataset `ValidationReport`, the connector
 * `TestResult`, and onboarding's inline upload-report block). */
export function ReportBanner({ ok, heading, children, className }: ReportBannerProps) {
  return (
    <div
      className={cn(
        "space-y-2 rounded-lg border p-3 text-sm",
        ok ? "border-success/30 bg-success/10" : "border-destructive/30 bg-destructive/5",
        className
      )}
    >
      <div className="flex items-start gap-2.5">
        {ok ? (
          <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-success" />
        ) : (
          <AlertCircle className="mt-0.5 size-4 shrink-0 text-destructive" />
        )}
        <p className={cn("font-medium", ok ? "text-success" : "text-destructive")}>{heading}</p>
      </div>
      {children}
    </div>
  );
}
