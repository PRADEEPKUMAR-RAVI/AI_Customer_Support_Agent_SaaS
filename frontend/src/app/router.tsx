/** Role-gated routing. Feature modules (onboarding, knowledge, records, tickets, workspace,
 * analytics) mount under the admin/agent shells as the two juniors build them. */

import { Link, Navigate, Route, Routes } from "react-router-dom";

import { Card } from "../components";
import { AgentSettingsPage } from "../features/agent-settings/AgentSettingsPage";
import { AnalyticsPage } from "../features/analytics/AnalyticsPage";
import { KnowledgePage } from "../features/knowledge/KnowledgePage";
import { RecordsPage } from "../features/records/RecordsPage";
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

function AdminHome() {
  return (
    <Card>
      <h2>Admin</h2>
      <ul>
        <li>
          <Link to="knowledge">Knowledge base</Link>
        </li>
        <li>
          <Link to="records">Customer records</Link>
        </li>
        <li>
          <Link to="analytics">Analytics</Link>
        </li>
        <li>
          <Link to="settings">Agent settings</Link>
        </li>
      </ul>
    </Card>
  );
}

function AdminRoutes() {
  return (
    <Routes>
      <Route index element={<AdminHome />} />
      <Route path="knowledge" element={<KnowledgePage />} />
      <Route path="records" element={<RecordsPage />} />
      <Route path="analytics" element={<AnalyticsPage />} />
      <Route path="settings" element={<AgentSettingsPage />} />
      <Route path="*" element={<Placeholder title="Admin — not found" />} />
    </Routes>
  );
}

export function AppRouter() {
  return (
    <AppLayout>
      <Routes>
        <Route path="/" element={<Navigate to="/admin" replace />} />
        <Route path="/login" element={<LoginPage />} />
        <Route path="/signup" element={<Placeholder title="Sign up (FE-Auth)" />} />
        <Route path="/verify" element={<Placeholder title="Verify email (FE-Auth)" />} />
        <Route
          path="/admin/*"
          element={
            <RequireAuth>
              <AdminRoutes />
            </RequireAuth>
          }
        />
        <Route
          path="/agent/*"
          element={
            <RequireAuth>
              <Placeholder title="Agent workspace (tickets / queue)" />
            </RequireAuth>
          }
        />
        <Route path="*" element={<Placeholder title="Not found" />} />
      </Routes>
    </AppLayout>
  );
}
