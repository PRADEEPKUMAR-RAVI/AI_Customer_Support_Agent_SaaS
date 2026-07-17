/** FE-Auth — `/login`. Same split-card shell as `/signup` (pitch panel + theme switch,
 * `AuthBrand.tsx`) rather than the plain `AuthLayout` card — this is the highest-traffic auth
 * entry point, so it earns the same visual investment as signup instead of reading as an
 * afterthought next to it. */

import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { toast } from "sonner";

import { homePathForRole } from "@/app/nav";
import { useAuth } from "@/app/providers";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

import { AuthSplitShell } from "./AuthBrand";

export function LoginPage() {
  const { login } = useAuth();
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    try {
      const role = await login(email, password);
      navigate(homePathForRole(role), { replace: true });
    } catch (err) {
      toast.error("Sign in failed", {
        description: err instanceof Error ? err.message : "Check your email and password.",
      });
    } finally {
      setBusy(false);
    }
  }

  return (
    <AuthSplitShell>
      <div className="space-y-6">
        <div className="space-y-1.5">
          <h1 className="text-xl font-semibold tracking-tight">Welcome back</h1>
          <p className="text-xs text-muted-foreground">Sign in to your support console.</p>
        </div>

        <form onSubmit={onSubmit} className="space-y-4">
          <div className="grid gap-1.5">
            <Label htmlFor="email" className="text-xs">Email</Label>
            <Input
              id="email"
              type="email"
              autoComplete="email"
              placeholder="you@company.com"
              className="text-sm"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
            />
          </div>
          <div className="grid gap-1.5">
            <div className="flex items-center justify-between">
              <Label htmlFor="password" className="text-xs">Password</Label>
              <Link to="/forgot" className="text-xs text-muted-foreground hover:text-foreground">
                Forgot password?
              </Link>
            </div>
            <Input
              id="password"
              type="password"
              placeholder="••••••••"
              autoComplete="current-password"
              className="text-sm placeholder:text-base placeholder:font-bold placeholder:tracking-[0.2em] placeholder:text-foreground/40"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
            />
          </div>

          <Button
            type="submit"
            size="lg"
            className="w-full shadow-lg shadow-brand-900/20 transition-shadow hover:shadow-xl hover:shadow-brand-900/25"
            disabled={busy}
          >
            {busy ? "Signing in…" : "Sign in"}
          </Button>
        </form>

        <p className="text-center text-xs text-muted-foreground">
          New here?{" "}
          <Link to="/signup" className="font-medium text-foreground hover:text-primary">
            Create an account
          </Link>
        </p>
      </div>
    </AuthSplitShell>
  );
}
