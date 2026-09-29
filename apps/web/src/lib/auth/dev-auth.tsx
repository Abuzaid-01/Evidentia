"use client";

import { useCallback, useMemo, useSyncExternalStore, type ReactNode } from "react";

import { AuthContext, type AuthState } from "./auth-bridge";

/** LOCAL DEVELOPMENT ONLY. The API refuses dev tokens outside local/test environments. */
export type DevIdentity = { user: string; org: string; role: string };

const STORAGE_KEY = "evidentia.dev-identity";
const listeners = new Set<() => void>();
let memoryFallback = ""; // used when localStorage is unavailable (e.g. private mode)

export const DEV_PERSONAS: (DevIdentity & { label: string; description: string })[] = [
  { user: "asha", org: "jalseva", role: "manager", label: "Asha · Programme manager", description: "Creates projects and sites, sees everything" },
  { user: "ravi", org: "jalseva", role: "contributor", label: "Ravi · Field contributor", description: "Uploads field photos and videos" },
  { user: "meera", org: "jalseva", role: "reviewer", label: "Meera · Evidence reviewer", description: "Verifies AI observations" },
  { user: "donor", org: "jalseva", role: "viewer", label: "Donor · Viewer", description: "Read-only access" },
  { user: "kiran", org: "greenroots", role: "admin", label: "Kiran · Another organisation", description: "Proves tenant isolation" },
];

function readRaw(): string {
  try {
    return window.localStorage.getItem(STORAGE_KEY) ?? "";
  } catch {
    return memoryFallback;
  }
}

export function writeDevIdentity(identity: DevIdentity | null): void {
  const raw = identity ? JSON.stringify(identity) : "";
  memoryFallback = raw;
  try {
    if (raw) window.localStorage.setItem(STORAGE_KEY, raw);
    else window.localStorage.removeItem(STORAGE_KEY);
  } catch {
    /* storage unavailable: memoryFallback keeps the identity for this page */
  }
  listeners.forEach((notify) => notify());
}

export function devToken(identity: DevIdentity): string {
  return `dev.${identity.user}.${identity.org}.${identity.role}`;
}

function subscribe(onChange: () => void) {
  listeners.add(onChange);
  window.addEventListener("storage", onChange);
  return () => {
    listeners.delete(onChange);
    window.removeEventListener("storage", onChange);
  };
}

export function DevAuthProvider({ children }: { children: ReactNode }) {
  // null on the server (not ready yet), "" when nobody is signed in, JSON when signed in.
  const raw = useSyncExternalStore<string | null>(subscribe, readRaw, () => null);
  const identity = useMemo<DevIdentity | null>(() => {
    if (!raw) return null;
    try {
      return JSON.parse(raw) as DevIdentity;
    } catch {
      return null;
    }
  }, [raw]);

  const getToken = useCallback(async () => (identity ? devToken(identity) : null), [identity]);
  const signOut = useCallback(() => writeDevIdentity(null), []);

  const value = useMemo<AuthState>(
    () => ({
      mode: "dev",
      ready: raw !== null,
      signedIn: !!identity,
      hasOrganization: !!identity,
      getToken,
      signOut,
    }),
    [raw, identity, getToken, signOut],
  );
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
