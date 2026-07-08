/** App-wide providers: Auth context (identity from the JWT), TanStack Query, tooltips, toasts. */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useState,
  type PropsWithChildren,
} from "react";

import { Toaster } from "@/components/ui/sonner";
import { TooltipProvider } from "@/components/ui/tooltip";

import { bootstrapSession, login as apiLogin, logout as apiLogout } from "../lib/auth";
import type { Role } from "../lib/rbac";
import { type Me, readMe } from "../lib/useMe";

interface AuthState {
  authenticated: boolean;
  ready: boolean; // boot silent-refresh finished
  role: Role | null;
  email: string | null;
  login: (email: string, password: string) => Promise<Role | null>;
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
  const [me, setMe] = useState<Me | null>(null);

  useEffect(() => {
    // Boot-time silent refresh — gate protected queries on `ready`.
    bootstrapSession()
      .then((ok) => {
        setAuthenticated(ok);
        if (ok) setMe(readMe());
      })
      .finally(() => setReady(true));
  }, []);

  const value = useMemo<AuthState>(
    () => ({
      authenticated,
      ready,
      role: me?.role ?? null,
      email: me?.email ?? null,
      async login(email, password) {
        await apiLogin(email, password);
        const identity = readMe(); // role/email decoded from the fresh access-token JWT
        setAuthenticated(true);
        setMe(identity);
        return identity?.role ?? null;
      },
      async logout() {
        await apiLogout();
        setAuthenticated(false);
        setMe(null);
      },
    }),
    [authenticated, ready, me]
  );

  return (
    <QueryClientProvider client={queryClient}>
      <TooltipProvider delayDuration={200}>
        <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
        <Toaster position="top-right" richColors />
      </TooltipProvider>
    </QueryClientProvider>
  );
}
