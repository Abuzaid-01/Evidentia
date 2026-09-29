"use client";

import { createContext, useContext } from "react";

/**
 * One interface over two auth backends (Clerk in real deployments, a dev identity locally), so the
 * rest of the app never imports Clerk directly.
 */
export type AuthState = {
  mode: "clerk" | "dev";
  ready: boolean;
  signedIn: boolean;
  hasOrganization: boolean;
  getToken: () => Promise<string | null>;
  signOut: () => void;
};

export const AuthContext = createContext<AuthState | null>(null);

export function useAuthState(): AuthState {
  const value = useContext(AuthContext);
  if (!value) throw new Error("useAuthState must be used inside <AuthProvider>");
  return value;
}
