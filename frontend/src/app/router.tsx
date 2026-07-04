/** Role-gated routing. The public hosted chat page (`/chat/:widgetKey`) renders full-screen
 * OUTSIDE the authenticated console shell; everything else mounts inside the shell. Feature
 * modules: person-3 (auth/onboarding/staff/tickets/agent-workspace) + person-2 (knowledge/
 * records/analytics/agent-settings) mount under admin/agent. */

import { Link, Navigate, Route, Routes, useParams } from "react-router-dom";

import { Card } from "../components";
import { Chat } from "../components/chat";
import { AgentWorkspacePage } from "../features/agent-workspace/AgentWorkspacePage";
import { AgentSettingsPage } from "../features/agent-settings/AgentSettingsPage";
import { AnalyticsPage } from "../features/analytics/AnalyticsPage";
import { SignupPage } from "../features/auth/SignupPage";
import { VerifyPage } from "../features/auth/VerifyPage";
import { KnowledgePage } from "../features/knowledge/KnowledgePage";
import { OnboardingPage } from "../features/onboarding/OnboardingPage";
import { RecordsPage } from "../features/records/RecordsPage";
import { StaffPage } from "../features/staff/StaffPage";
import { TicketDetailPage } from "../features/tickets/TicketDetailPage";
import { TicketsPage } from "../features/tickets/TicketsPage";
import { AppLayout } from "./layout";
import { useAuth } from "./providers";

function RequireAuth({ children }: { children: JSX.Element }) {
  const { authenticated, ready } = useAuth();
  if (!ready) return <p>Loading…</p>;
  return authenticated ? children : <Navigate to="/login" replace />;
}

function LoginPage() {
  const { login } = useAuth();
  return (
    <Card>
      <h2>Log in</h2>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          const form = e.currentTarget;
          const email = (form.elements.namedItem("email") as HTMLInputElement).value;
          const password = (form.elements.namedItem("password") as HTMLInputElement).value;
          void login(email, password);
        }}
      >
        <input name="email" type="email" placeholder="you@company.com" required />
        <input name="password" type="password" placeholder="password" required />
        <button type="submit">Sign in</button>
      </form>
    </Card>
  );
}

const Placeholder = ({ title }: { title: string }) => (
  <Card>
    <h2>{title}</h2>
    <p>Feature module mounts here.</p>
  </Card>
);

/** Public hosted chat surface — `/chat/{widget_key}` — full-viewport, no console chrome/auth. */
function HostedChat() {
  const { widgetKey } = useParams();
  return (
    <div style={{ position: "fixed", inset: 0, display: "flex", justifyContent: "center", background: "#f9fafb" }}>
      <div style={{ width: "100%", maxWidth: 480, height: "100%", boxShadow: "0 0 24px rgba(0,0,0,0.08)" }}>
        <Chat widgetKey={widgetKey ?? ""} />
      </div>
    </div>
  );
}

function AdminSection() {
  return (
    <div>
      <nav style={{ display: "flex", gap: 14, marginBottom: 16, fontSize: 14, flexWrap: "wrap" }}>
        <Link to="/admin/onboarding">Onboarding</Link>
        <Link to="/admin/knowledge">Knowledge</Link>
        <Link to="/admin/records">Records</Link>
        <Link to="/admin/staff">Staff</Link>
        <Link to="/admin/tickets">Tickets</Link>
        <Link to="/admin/analytics">Analytics</Link>
        <Link to="/admin/settings">Settings</Link>
      </nav>
      <Routes>
        <Route path="/" element={<Navigate to="onboarding" replace />} />
        <Route path="onboarding" element={<OnboardingPage />} />
        <Route path="knowledge" element={<KnowledgePage />} />
        <Route path="records" element={<RecordsPage />} />
        <Route path="staff" element={<StaffPage />} />
        <Route path="tickets" element={<TicketsPage />} />
        <Route path="tickets/:id" element={<TicketDetailPage />} />
        <Route path="analytics" element={<AnalyticsPage />} />
        <Route path="settings" element={<AgentSettingsPage />} />
        <Route path="*" element={<Placeholder title="Admin — not found" />} />
      </Routes>
    </div>
  );
}

function AgentSection() {
  return (
    <div>
      <nav style={{ display: "flex", gap: 14, marginBottom: 16, fontSize: 14 }}>
        <Link to="/agent">Workspace</Link>
      </nav>
      <Routes>
        <Route path="/" element={<AgentWorkspacePage />} />
        <Route path="tickets/:id" element={<TicketDetailPage />} />
      </Routes>
    </div>
  );
}

function Shell() {
  return (
    <AppLayout>
      <Routes>
        <Route path="/" element={<Navigate to="/admin" replace />} />
        <Route path="/login" element={<LoginPage />} />
        <Route path="/signup" element={<SignupPage />} />
        <Route path="/verify" element={<VerifyPage />} />
        <Route
          path="/admin/*"
          element={
            <RequireAuth>
              <AdminSection />
            </RequireAuth>
          }
        />
        <Route
          path="/agent/*"
          element={
            <RequireAuth>
              <AgentSection />
            </RequireAuth>
          }
        />
        <Route path="*" element={<Placeholder title="Not found" />} />
      </Routes>
    </AppLayout>
  );
}

export function AppRouter() {
  return (
    <Routes>
      <Route path="/chat/:widgetKey" element={<HostedChat />} />
      <Route path="/*" element={<Shell />} />
    </Routes>
  );
}
