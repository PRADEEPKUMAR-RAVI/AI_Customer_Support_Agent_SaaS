import { ShieldAlert } from "lucide-react";
import { Outlet } from "react-router-dom";

import { ThemeToggle } from "@/components/theme-toggle";

/** Platform-operator shell — deliberately distinct from the tenant console. Cross-tenant,
 * platform-scoped principal only (never a tenant JWT). */
export function OpsLayout() {
  return (
    <div className="min-h-svh bg-background">
      <header className="flex h-14 items-center gap-3 border-b px-4 md:px-8">
        <ShieldAlert className="size-5 text-primary" />
        <span className="font-semibold tracking-tight">Platform operator</span>
        <span className="rounded-full bg-warning/20 px-2 py-0.5 text-xs font-medium text-warning-foreground">
          cross-tenant
        </span>
        <div className="ml-auto">
          <ThemeToggle />
        </div>
      </header>
      <main className="mx-auto w-full max-w-6xl px-4 py-8 md:px-8">
        <Outlet />
      </main>
    </div>
  );
}
