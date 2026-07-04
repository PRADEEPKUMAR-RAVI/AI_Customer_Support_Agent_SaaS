/** Minimal design-system primitives so feature modules have a consistent starting point. */

import type { ButtonHTMLAttributes, PropsWithChildren } from "react";

export function Button(
  props: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "primary" | "ghost" }
) {
  const { variant = "primary", style, ...rest } = props;
  const base: React.CSSProperties = {
    padding: "8px 14px",
    borderRadius: 8,
    border: "1px solid transparent",
    cursor: "pointer",
    fontSize: 14,
  };
  const variants: Record<string, React.CSSProperties> = {
    primary: { background: "#2563eb", color: "#fff" },
    ghost: { background: "transparent", color: "#2563eb", borderColor: "#2563eb" },
  };
  return <button style={{ ...base, ...variants[variant], ...style }} {...rest} />;
}

export function Card({ children }: PropsWithChildren) {
  return (
    <div style={{ border: "1px solid #e5e7eb", borderRadius: 12, padding: 16, background: "#fff" }}>
      {children}
    </div>
  );
}

export function Spinner() {
  return <span role="status" aria-live="polite">Loading…</span>;
}
