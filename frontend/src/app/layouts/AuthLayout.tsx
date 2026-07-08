import { MessagesSquare } from "lucide-react";
import { Outlet } from "react-router-dom";

/** Centered, single-column shell for the unauthenticated auth flows (login/signup/verify/reset). */
export function AuthLayout() {
  return (
    <div className="grid min-h-svh place-items-center bg-gradient-to-b from-background to-muted/40 px-4 py-10">
      <div className="w-full max-w-sm">
        <div className="mb-6 flex items-center justify-center gap-2.5">
          <div className="grid size-9 place-items-center rounded-xl bg-gradient-to-br from-primary to-primary/70 text-primary-foreground shadow-sm">
            <MessagesSquare className="size-5" />
          </div>
          <span className="text-lg font-semibold tracking-tight">Helm</span>
        </div>
        <Outlet />
      </div>
    </div>
  );
}
