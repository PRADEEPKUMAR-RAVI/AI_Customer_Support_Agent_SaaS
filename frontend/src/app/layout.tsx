import type { PropsWithChildren } from "react";
import { Link } from "react-router-dom";

import { useAuth } from "./providers";

export function AppLayout({ children }: PropsWithChildren) {
  const { authenticated, logout } = useAuth();
  return (
    <div style={{ fontFamily: "system-ui, sans-serif", color: "#111827" }}>
      <header
        style={{
          display: "flex",
          gap: 16,
          alignItems: "center",
          padding: "12px 20px",
          borderBottom: "1px solid #e5e7eb",
        }}
      >
        <strong>CS Agent Console</strong>
        <nav style={{ display: "flex", gap: 12, fontSize: 14 }}>
          <Link to="/admin">Admin</Link>
          <Link to="/agent">Agent</Link>
        </nav>
        <div style={{ marginLeft: "auto" }}>
          {authenticated ? (
            <button onClick={() => void logout()}>Log out</button>
          ) : (
            <Link to="/login">Log in</Link>
          )}
        </div>
      </header>
      <main style={{ padding: 20 }}>{children}</main>
    </div>
  );
}
