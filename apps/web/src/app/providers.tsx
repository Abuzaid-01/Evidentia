"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";
import { Toaster } from "sonner";

import { ApiError, setTokenGetter } from "@/lib/api/client";
import { useAuthState } from "@/lib/auth/auth-bridge";
import { ClerkAuthProvider } from "@/lib/auth/clerk-auth";
import { DevAuthProvider } from "@/lib/auth/dev-auth";
import { config } from "@/lib/config";

function TokenWiring({ children }: { children: ReactNode }) {
  const { getToken } = useAuthState();
  // Set during render (idempotent), not in an effect: children's queries may fire before a
  // parent's effects run, and must already carry the session token.
  setTokenGetter(getToken);
  return <>{children}</>;
}

export function Providers({ children }: { children: ReactNode }) {
  const [queryClient] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            staleTime: 15_000,
            refetchOnWindowFocus: false,
            retry: (count, error) =>
              !(error instanceof ApiError && error.status >= 400 && error.status < 500) && count < 2,
          },
        },
      }),
  );

  const AuthProvider = config.authMode === "clerk" ? ClerkAuthProvider : DevAuthProvider;
  return (
    <AuthProvider>
      <TokenWiring>
        <QueryClientProvider client={queryClient}>
          {children}
          <Toaster richColors position="bottom-right" />
        </QueryClientProvider>
      </TokenWiring>
    </AuthProvider>
  );
}
