/** Application routes. Three shells: AuthLayout (public auth flows), ConsoleLayout (authenticated
 * admin + agent console, RBAC-gated per route), and OpsLayout (platform operator). The public
 * hosted chat page renders full-bleed outside every shell. */

import { Loader2 } from "lucide-react";
import { Navigate, Outlet, Route, Routes, useLocation, useParams } from "react-router-dom";

import { homePathForRole } from "@/app/nav";
import { Chat } from "@/components/chat";
import { EmptyState } from "@/components/empty-state";
import { NoAccessState } from "@/components/no-access-state";
import { hasPermission } from "@/lib/rbac";

import { AgentSettingsPage } from "../features/agent-settings/AgentSettingsPage";
import { AgentWorkspacePage } from "../features/agent-workspace/AgentWorkspacePage";
import { AnalyticsPage } from "../features/analytics/AnalyticsPage";
import { ForgotPage } from "../features/auth/ForgotPage";
import { LoginPage } from "../features/auth/LoginPage";
import { ResetPage } from "../features/auth/ResetPage";
import { SignupPage } from "../features/auth/SignupPage";
import { VerifyPage } from "../features/auth/VerifyPage";
import { ChannelsPage } from "../features/channels/ChannelsPage";
import { KnowledgePage } from "../features/knowledge/KnowledgePage";
import { LandingPage } from "../features/landing/LandingPage";
import { OnboardingPage } from "../features/onboarding/OnboardingPage";
import { useOnboardingStatus } from "../features/onboarding/useOnboardingStatus";
import { OpsPage } from "../features/ops/OpsPage";
import { OverviewPage } from "../features/overview/OverviewPage";
import { RecordsPage } from "../features/records/RecordsPage";
import { StaffPage } from "../features/staff/StaffPage";
import { TicketDetailPage } from "../features/tickets/TicketDetailPage";
import { TicketsPage } from "../features/tickets/TicketsPage";
import { AuthLayout } from "./layouts/AuthLayout";
import { ConsoleLayout } from "./layouts/ConsoleLayout";
import { OpsLayout } from "./layouts/OpsLayout";
import { useAuth } from "./providers";

function FullPageLoader() {
  return (
    <div className="grid min-h-svh place-items-center text-muted-foreground">
      <Loader2 className="size-6 animate-spin" aria-label="Loading" />
    </div>
  );
}

function RequireAuth() {
  const { authenticated, ready } = useAuth();
  if (!ready) return <FullPageLoader />;
  return authenticated ? <Outlet /> : <Navigate to="/login" replace />;
}

/** The inverse of `RequireAuth`, guarding every sign-in/sign-up/reset page: an already-signed-in
 * visitor is bounced straight to their console home instead of ever rendering the page. This is
 * what actually stops the browser Back button from surfacing "Reset your password" (or Login,
 * Signup, Verify) after a successful sign-in — `navigate(..., { replace: true })` at each step
 * only rewrites ONE history entry, so a multi-step flow (forgot -> emailed reset link -> login)
 * still leaves earlier entries in the stack for Back to walk into. Guarding the routes themselves
 * closes it regardless of how the URL was reached — Back button, a stale bookmark, or a link
 * pasted from an old email — matching how Gmail/most SaaS consoles behave. */
function RequireGuest() {
  const { authenticated, ready, role } = useAuth();
  if (!ready) return <FullPageLoader />;
  return authenticated ? <Navigate to={homePathForRole(role)} replace /> : <Outlet />;
}

/** Forces admins through /onboarding until the required setup steps are done — derived from
 * resource state (see `useOnboardingStatus`), not a stored flag, so it can never drift from the
 * wizard's own step checklist. Agents (and any other non-admin role) aren't gated: they can't
 * complete these admin-only steps anyway. */
function RequireOnboarding() {
  const { role } = useAuth();
  const { data, isLoading } = useOnboardingStatus();
  const location = useLocation();

  if (role !== "admin") return <Outlet />;
  if (isLoading) return <FullPageLoader />;
  if (data && !data.completed && location.pathname !== "/onboarding") {
    return <Navigate to="/onboarding" replace />;
  }
  return <Outlet />;
}

function Guard({ perm, children }: { perm: string; children: JSX.Element }) {
  const { role } = useAuth();
  if (hasPermission(role, perm)) return children;
  return <NoAccessState />;
}

function NotFound() {
  return <EmptyState title="Page not found" description="The page you're looking for doesn't exist." />;
}

/** Public hosted chat surface — /chat/{widget_key} — full-viewport, no console chrome or auth. */
function HostedChat() {
  const { widgetKey } = useParams();
  return (
    <div className="fixed inset-0 flex justify-center bg-muted/40">
      <div className="h-full w-full max-w-[480px] bg-background shadow-xl">
        <Chat widgetKey={widgetKey ?? ""} />
      </div>
    </div>
  );
}

export function AppRouter() {
  return (
    <Routes>
      <Route path="/chat/:widgetKey" element={<HostedChat />} />
      <Route path="/" element={<LandingPage />} />

      <Route element={<RequireGuest />}>
        {/* Full-bleed split layout of their own — not the shared centered AuthLayout column. */}
        <Route path="/signup" element={<SignupPage />} />
        <Route path="/login" element={<LoginPage />} />
        <Route path="/forgot" element={<ForgotPage />} />

        <Route element={<AuthLayout />}>
          <Route path="/verify" element={<VerifyPage />} />
          <Route path="/reset" element={<ResetPage />} />
        </Route>
      </Route>

      <Route element={<RequireAuth />}>
        <Route element={<RequireOnboarding />}>
          <Route element={<ConsoleLayout />}>
            <Route path="/overview" element={<OverviewPage />} />
            <Route path="/tickets" element={<Guard perm="tickets:read"><TicketsPage /></Guard>} />
            <Route path="/tickets/:id" element={<Guard perm="tickets:read"><TicketDetailPage /></Guard>} />
            <Route path="/inbox" element={<Guard perm="agents:queue"><AgentWorkspacePage /></Guard>} />
            <Route path="/onboarding" element={<Guard perm="settings:manage"><OnboardingPage /></Guard>} />
            <Route path="/knowledge" element={<Guard perm="kb:manage"><KnowledgePage /></Guard>} />
            <Route path="/records" element={<Guard perm="records:manage"><RecordsPage /></Guard>} />
            <Route path="/settings" element={<Guard perm="settings:manage"><AgentSettingsPage /></Guard>} />
            <Route path="/channels" element={<Guard perm="settings:manage"><ChannelsPage /></Guard>} />
            <Route path="/staff" element={<Guard perm="staff:manage"><StaffPage /></Guard>} />
            <Route path="/analytics" element={<Guard perm="analytics:read"><AnalyticsPage /></Guard>} />
            <Route path="*" element={<NotFound />} />
          </Route>
        </Route>
      </Route>

      <Route path="/ops" element={<OpsLayout />}>
        <Route index element={<OpsPage />} />
      </Route>
    </Routes>
  );
}
