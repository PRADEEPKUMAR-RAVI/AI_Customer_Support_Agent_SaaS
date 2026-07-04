/** FE-Auth — `/verify`. The email verification link lands here with `?token=...`. */

import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { Card, Spinner } from "../../components";
import { verifyEmail } from "../../lib/auth";

type Status = "verifying" | "verified" | "error";

export function VerifyPage() {
  const [params] = useSearchParams();
  const token = params.get("token");
  const [status, setStatus] = useState<Status>("verifying");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!token) {
      setStatus("error");
      setError("Missing verification token.");
      return;
    }
    verifyEmail(token)
      .then(() => setStatus("verified"))
      .catch((err: unknown) => {
        setStatus("error");
        setError(err instanceof Error ? err.message : "Verification failed");
      });
  }, [token]);

  return (
    <Card>
      <h2>Email verification</h2>
      {status === "verifying" && <Spinner />}
      {status === "verified" && (
        <>
          <p>Your email is verified.</p>
          <Link to="/login">Continue to log in</Link>
        </>
      )}
      {status === "error" && <p role="alert" style={{ color: "#dc2626" }}>{error}</p>}
    </Card>
  );
}
