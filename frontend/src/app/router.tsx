/** Role-gated routing. Feature modules (onboarding, knowledge, records, tickets, workspace,
 * analytics) mount under the admin/agent shells as the two juniors build them. */

import { Navigate, Route, Routes } from "react-router-dom";

import { Card } from "../components";
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
              <Placeholder title="Admin (onboarding / knowledge / records / settings / analytics)" />
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
