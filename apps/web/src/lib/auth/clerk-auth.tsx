"use client";

import { ClerkProvider, useAuth, useClerk } from "@clerk/nextjs";
import { useMemo, type ReactNode } from "react";

import { AuthContext, type AuthState } from "./auth-bridge";

function ClerkBridge({ children }: { children: ReactNode }) {
  const { isLoaded, isSignedIn, orgId, getToken } = useAuth();
  const clerk = useClerk();

  const value = useMemo<AuthState>(
    () => ({
      mode: "clerk",
      ready: isLoaded,
      signedIn: !!isSignedIn,
      hasOrganization: !!orgId,
      getToken: () => getToken(),
      signOut: () => void clerk.signOut({ redirectUrl: "/sign-in" }),
    }),
    [isLoaded, isSignedIn, orgId, getToken, clerk],
  );
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function ClerkAuthProvider({ children }: { children: ReactNode }) {
  return (
    <ClerkProvider>
      <ClerkBridge>{children}</ClerkBridge>
    </ClerkProvider>
  );
}
