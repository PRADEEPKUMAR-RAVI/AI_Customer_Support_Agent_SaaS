/** FE-Auth — `/verify`. The email verification link lands here with `?token=...`. */

import { AlertCircle, CheckCircle2, Loader2 } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { Button } from "@/components/ui/button";
import {
  Card,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";

import { verifyEmail } from "../../lib/auth";

type Status = "verifying" | "verified" | "error";

export function VerifyPage() {
  const [params] = useSearchParams();
  const token = params.get("token");
  const [status, setStatus] = useState<Status>("verifying");
  const [error, setError] = useState<string | null>(null);
  const started = useRef(false);

  useEffect(() => {
    // Guard against React 18 StrictMode's double-invoke — the token is single-use, so a second
    // call would fail and clobber a successful verification.
    if (started.current) return;
    started.current = true;

    if (!token) {
      setStatus("error");
      setError("This verification link is missing its token.");
      return;
    }
    verifyEmail(token)
      .then(() => setStatus("verified"))
      .catch((err: unknown) => {
        setStatus("error");
        setError(err instanceof Error ? err.message : "Verification failed");
      });
  }, [token]);

  if (status === "verifying") {
    return (
      <Card>
        <CardHeader className="items-center text-center">
          <div className="mb-1 grid size-11 place-items-center rounded-full bg-muted text-muted-foreground">
            <Loader2 className="size-6 animate-spin" aria-label="Verifying" />
          </div>
          <CardTitle className="text-xl">Verifying your email</CardTitle>
          <CardDescription>Hang tight while we confirm your link.</CardDescription>
        </CardHeader>
      </Card>
    );
  }

  if (status === "verified") {
    return (
      <Card>
        <CardHeader className="items-center text-center">
          <div className="mb-1 grid size-11 place-items-center rounded-full bg-success/10 text-success">
            <CheckCircle2 className="size-6" />
          </div>
          <CardTitle className="text-xl">Email verified</CardTitle>
          <CardDescription>Your account is ready. Sign in to get started.</CardDescription>
        </CardHeader>
        <CardFooter>
          <Button asChild className="w-full">
            <Link to="/login">Continue to sign in</Link>
          </Button>
        </CardFooter>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader className="items-center text-center">
        <div className="mb-1 grid size-11 place-items-center rounded-full bg-destructive/10 text-destructive">
          <AlertCircle className="size-6" />
        </div>
        <CardTitle className="text-xl">Verification failed</CardTitle>
        <CardDescription role="alert">
          {error ?? "We couldn't verify this link. It may have expired or already been used."}
        </CardDescription>
      </CardHeader>
      <CardFooter className="flex-col gap-3">
        <Button asChild variant="outline" className="w-full">
          <Link to="/signup">Create a new account</Link>
        </Button>
        <p className="text-center text-sm text-muted-foreground">
          Already verified?{" "}
          <Link to="/login" className="font-medium text-primary hover:underline">
            Sign in
          </Link>
        </p>
      </CardFooter>
    </Card>
  );
}
