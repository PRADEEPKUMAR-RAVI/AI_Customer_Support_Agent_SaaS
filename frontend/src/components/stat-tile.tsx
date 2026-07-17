import type { LucideIcon } from "lucide-react";
import type { ReactNode } from "react";

import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

const TILE_TONE = {
  neutral: "bg-secondary text-muted-foreground",
  ai: "bg-ai-accent/15 text-ai-accent",
  success: "bg-success/15 text-success",
  info: "bg-blue-500/15 text-blue-600 dark:text-blue-400",
} as const;

interface StatTileProps {
  icon: LucideIcon;
  label: string;
  value: ReactNode;
  hint?: ReactNode;
  loading?: boolean;
  /** Warning-tinted icon chip for a figure that needs attention (e.g. a nonzero dead-letter count). */
  alert?: boolean;
  /** Color the icon chip carries when not `alert` — pick the tone that matches what the figure
   * means (e.g. "ai" for anything automation-resolved, "success" for a healthy/good number). */
  tone?: keyof typeof TILE_TONE;
  className?: string;
}

/** Canonical KPI tile: label + icon chip, a big tabular-nums figure, an optional hint line.
 * Consolidates what used to be three near-identical local components (Overview's KpiCard,
 * Analytics' StatCard, Ops' StatCard) — callers own their own value formatting/error fallback
 * ("—" on error, `.toLocaleString()`, etc.) and just hand this the final display value. */
export function StatTile({
  icon: Icon,
  label,
  value,
  hint,
  loading,
  alert,
  tone = "neutral",
  className,
}: StatTileProps) {
  return (
    <Card className={cn("gap-0 py-5 shadow-sm transition-shadow hover:shadow-md", className)}>
      <CardContent className="px-5">
        <div className="flex items-center justify-between gap-2">
          <span className="text-sm font-medium text-muted-foreground">{label}</span>
          <span
            className={cn(
              "grid size-9 shrink-0 place-items-center rounded-lg",
              alert ? "bg-warning/20 text-warning-foreground" : TILE_TONE[tone]
            )}
          >
            <Icon className="size-4" />
          </span>
        </div>
        <div className="mt-3">
          {loading ? (
            <Skeleton className="h-8 w-24" />
          ) : (
            <span className="font-display text-3xl font-semibold tracking-tight tabular-nums">{value}</span>
          )}
        </div>
        {loading ? (
          <Skeleton className="mt-2.5 h-3 w-28" />
        ) : hint ? (
          <p className="mt-2 text-xs text-muted-foreground">{hint}</p>
        ) : null}
      </CardContent>
    </Card>
  );
}
