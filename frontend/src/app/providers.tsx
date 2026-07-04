/** App-wide providers: Auth context, TanStack Query, and a minimal theme/toast surface. */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useState,
  type PropsWithChildren,
} from "react";

import { bootstrapSession, login as apiLogin, logout as apiLogout } from "../lib/auth";
import type { Role } from "../lib/rbac";

interface AuthState {
  authenticated: boolean;
  ready: boolean; // boot silent-refresh finished
  role: Role | null;
  login: (email: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthState | null>(null);

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within <Providers>");
  return ctx;
}

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: false } },
});

export function Providers({ children }: PropsWithChildren) {
  const [authenticated, setAuthenticated] = useState(false);
  const [ready, setReady] = useState(false);
  const [role, setRole] = useState<Role | null>(null);

  useEffect(() => {
    // Boot-time silent refresh — gate protected queries on `ready`.
    bootstrapSession()
      .then((ok) => setAuthenticated(ok))
      .finally(() => setReady(true));
  }, []);

  const value = useMemo<AuthState>(
    () => ({
      authenticated,
      ready,
      role,
      async login(email, password) {
        await apiLogin(email, password);
        setAuthenticated(true);
        setRole("admin"); // refined from the JWT/`/me` endpoint as features land
      },
      async logout() {
        await apiLogout();
        setAuthenticated(false);
        setRole(null);
      },
    }),
    [authenticated, ready, role]
  );

  return (
    <QueryClientProvider client={queryClient}>
      <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
    </QueryClientProvider>
  );
}
