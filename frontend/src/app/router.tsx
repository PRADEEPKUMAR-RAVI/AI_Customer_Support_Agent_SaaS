/** Role-gated routing. Feature modules (knowledge, records, analytics, agent workspace) mount
 * under the admin/agent shells as person-2/person-1 build them. */

import { Link, Navigate, Route, Routes } from "react-router-dom";

import { Card } from "../components";
import { AgentWorkspacePage } from "../features/agent-workspace/AgentWorkspacePage";
import { SignupPage } from "../features/auth/SignupPage";
import { VerifyPage } from "../features/auth/VerifyPage";
import { OnboardingPage } from "../features/onboarding/OnboardingPage";
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

function AdminSection() {
  return (
    <div>
      <nav style={{ display: "flex", gap: 14, marginBottom: 16, fontSize: 14 }}>
        <Link to="/admin/onboarding">Onboarding</Link>
        <Link to="/admin/staff">Staff</Link>
        <Link to="/admin/tickets">Tickets</Link>
      </nav>
      <Routes>
        <Route path="/" element={<Navigate to="onboarding" replace />} />
        <Route path="onboarding" element={<OnboardingPage />} />
        <Route path="staff" element={<StaffPage />} />
        <Route path="tickets" element={<TicketsPage />} />
        <Route path="tickets/:id" element={<TicketDetailPage />} />
        <Route path="knowledge" element={<Placeholder title="Knowledge (person-2)" />} />
        <Route path="records" element={<Placeholder title="Records (person-2)" />} />
        <Route path="analytics" element={<Placeholder title="Analytics (person-2)" />} />
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

export function AppRouter() {
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
