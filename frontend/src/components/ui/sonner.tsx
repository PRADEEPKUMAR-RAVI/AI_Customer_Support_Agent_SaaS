import {
  CircleCheckIcon,
  InfoIcon,
  Loader2Icon,
  OctagonXIcon,
  TriangleAlertIcon,
} from "lucide-react"
import { Toaster as Sonner, type ToasterProps } from "sonner"

import { useTheme } from "@/lib/useTheme"

/** The single toast surface for the whole app — every `toast.success/error/warning/info(...)`
 * call (see `src/lib/useToastMutation.ts` and the many feature pages) renders through this one
 * `<Toaster>`, mounted once in `providers.tsx`. Styled from the same semantic tokens as
 * everything else (`success`/`destructive`/`warning`/`info` in `globals.css`) rather than
 * sonner's own defaults, so a toast reads as part of Relay, not a bolted-on library widget —
 * and it never needs restyling per call site: get the tone right here once, everywhere inherits
 * it. Text stays neutral (`--popover-foreground`) at every tone; only the icon, the border, and
 * a soft background tint carry the color, so a long error description stays as readable as the
 * title. */
const Toaster = ({ ...props }: ToasterProps) => {
  const { resolvedTheme } = useTheme()

  return (
    <Sonner
      theme={resolvedTheme}
      className="toaster group"
      icons={{
        success: <CircleCheckIcon className="size-4 text-success" />,
        info: <InfoIcon className="size-4 text-info" />,
        warning: <TriangleAlertIcon className="size-4 text-warning" />,
        error: <OctagonXIcon className="size-4 text-destructive" />,
        loading: <Loader2Icon className="size-4 animate-spin text-muted-foreground" />,
      }}
      style={
        {
          "--normal-bg": "var(--popover)",
          "--normal-text": "var(--popover-foreground)",
          "--normal-border": "var(--border)",
          "--border-radius": "var(--radius)",

          "--success-bg": "color-mix(in oklab, var(--success) 10%, var(--popover))",
          "--success-border": "color-mix(in oklab, var(--success) 35%, var(--border))",
          "--success-text": "var(--popover-foreground)",

          "--error-bg": "color-mix(in oklab, var(--destructive) 10%, var(--popover))",
          "--error-border": "color-mix(in oklab, var(--destructive) 35%, var(--border))",
          "--error-text": "var(--popover-foreground)",

          "--warning-bg": "color-mix(in oklab, var(--warning) 12%, var(--popover))",
          "--warning-border": "color-mix(in oklab, var(--warning) 40%, var(--border))",
          "--warning-text": "var(--popover-foreground)",

          "--info-bg": "color-mix(in oklab, var(--info) 10%, var(--popover))",
          "--info-border": "color-mix(in oklab, var(--info) 35%, var(--border))",
          "--info-text": "var(--popover-foreground)",
        } as React.CSSProperties
      }
      toastOptions={{
        classNames: {
          toast: "shadow-lg",
          title: "font-medium",
          description: "text-muted-foreground",
          actionButton: "!bg-primary !text-primary-foreground",
          cancelButton: "!bg-secondary !text-secondary-foreground",
        },
      }}
      {...props}
    />
  )
}

export { Toaster }
