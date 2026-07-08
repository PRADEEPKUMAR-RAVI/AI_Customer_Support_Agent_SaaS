/**
 * Typed mirror of design tokens for JS/SVG consumers (mainly Recharts, which needs color
 * strings). These reference the CSS variables from globals.css, so charts theme automatically
 * in light/dark. Keep in sync with `src/styles/globals.css`.
 */

/** Categorical palette — assign in fixed slot order, never cycle. Validated colorblind-safe. */
export const CHART_COLORS = [
  "var(--color-chart-1)",
  "var(--color-chart-2)",
  "var(--color-chart-3)",
  "var(--color-chart-4)",
  "var(--color-chart-5)",
  "var(--color-chart-6)",
  "var(--color-chart-7)",
  "var(--color-chart-8)",
] as const;

/** Canonical escalation reasons → a fixed chart slot, so a reason is the same color everywhere. */
export const ESCALATION_REASON_COLOR: Record<string, string> = {
  no_grounding: "var(--color-chart-8)", // orange — out-of-scope / no KB
  explicit: "var(--color-chart-1)", // blue — human requested
  sensitive: "var(--color-chart-6)", // red — sensitive
  dispute: "var(--color-chart-5)", // violet — billing/dispute
  n_fails: "var(--color-chart-3)", // yellow — repeated failure
  proactive: "var(--color-chart-2)", // aqua — proactive offer
  timeout: "var(--color-chart-7)", // magenta — timeout
};

/** Chart chrome (axes/grid/ink) — reference tokens so text never wears a series color. */
export const CHART_CHROME = {
  grid: "var(--color-border)",
  axis: "var(--color-muted-foreground)",
  ink: "var(--color-foreground)",
} as const;

/** Motion tokens (ms) — keep flashy stuff off; honor prefers-reduced-motion (handled in CSS). */
export const MOTION = {
  instant: 100,
  fast: 150,
  base: 200,
  slow: 250,
} as const;
