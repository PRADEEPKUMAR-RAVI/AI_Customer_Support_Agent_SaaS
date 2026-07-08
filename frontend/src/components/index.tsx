/** Backwards-compatible primitives. The original inline-styled Button/Card/Spinner are kept as
 * thin shims over the shadcn design system so not-yet-restyled feature pages stay consistent and
 * keep compiling during the redesign. New code should import from `@/components/ui/*` directly. */

import { Loader2 } from "lucide-react";
import type { ButtonHTMLAttributes, PropsWithChildren } from "react";

import { Button as UiButton } from "@/components/ui/button";

export function Button({
  variant = "primary",
  ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "primary" | "ghost" }) {
  return <UiButton variant={variant === "ghost" ? "ghost" : "default"} {...rest} />;
}

export function Card({ children }: PropsWithChildren) {
  return (
    <div className="rounded-xl border bg-card p-4 text-card-foreground shadow-sm">{children}</div>
  );
}

export function Spinner() {
  return (
    <span role="status" aria-live="polite" className="inline-flex items-center gap-2 text-sm text-muted-foreground">
      <Loader2 className="size-4 animate-spin" />
      Loading…
    </span>
  );
}
