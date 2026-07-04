/** FE-Auth — `/signup`. Workspace name + email + password + industry pick in one step: the
 * backend's `SignupRequest` already requires an industry (it provisions the record schema +
 * default agent_settings atomically), so there is no separate "pick an industry" screen for
 * the walking skeleton — this form *is* the Phase-1 "industry pick". */

import { useState } from "react";
import { Link } from "react-router-dom";

import { Button, Card } from "../../components";
import { signup, type Industry } from "../../lib/auth";

const INDUSTRIES: { value: Industry; label: string }[] = [
  { value: "retail", label: "Retail / E-commerce" },
  { value: "logistics", label: "Logistics / Courier" },
  { value: "telecom", label: "Telecom / ISP" },
  { value: "healthcare", label: "Healthcare / Clinic" },
  { value: "travel", label: "Travel / Hospitality" },
];

export function SignupPage() {
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);

  async function handleSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    const form = e.currentTarget;
    try {
      await signup({
        workspace_name: (form.elements.namedItem("workspace_name") as HTMLInputElement).value,
        email: (form.elements.namedItem("email") as HTMLInputElement).value,
        password: (form.elements.namedItem("password") as HTMLInputElement).value,
        industry: (form.elements.namedItem("industry") as HTMLSelectElement).value as Industry,
      });
      setDone(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Signup failed");
    } finally {
      setSubmitting(false);
    }
  }

  if (done) {
    return (
      <Card>
        <h2>Check your email</h2>
        <p>We sent a verification link to finish setting up your workspace.</p>
        <Link to="/login">Back to log in</Link>
      </Card>
    );
  }

  return (
    <Card>
      <h2>Create your workspace</h2>
      <form onSubmit={(e) => void handleSubmit(e)} style={{ display: "grid", gap: 10, maxWidth: 360 }}>
        <input name="workspace_name" placeholder="Workspace name" required />
        <input name="email" type="email" placeholder="you@company.com" required />
        <input name="password" type="password" placeholder="password (min 8 chars)" minLength={8} required />
        <select name="industry" defaultValue={INDUSTRIES[0].value} required>
          {INDUSTRIES.map((i) => (
            <option key={i.value} value={i.value}>
              {i.label}
            </option>
          ))}
        </select>
        {error && <p role="alert" style={{ color: "#dc2626" }}>{error}</p>}
        <Button type="submit" disabled={submitting}>
          {submitting ? "Creating…" : "Create workspace"}
        </Button>
      </form>
      <p style={{ marginTop: 12 }}>
        Already have an account? <Link to="/login">Log in</Link>
      </p>
    </Card>
  );
}
