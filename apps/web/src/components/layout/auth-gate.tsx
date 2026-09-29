"use client";

import { CreateOrganization } from "@clerk/nextjs";
import { Loader2 } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, type ReactNode } from "react";

import { useAuthState } from "@/lib/auth/auth-bridge";
import { useOrgEventStream } from "@/lib/events/use-org-events";

import { Logo } from "./logo";

function LiveEvents() {
  useOrgEventStream();
  return null;
}

/** Client-side gate: signed in + an active organization, otherwise route to the right step. */
export function AuthGate({ children }: { children: ReactNode }) {
  const auth = useAuthState();
  const router = useRouter();

  useEffect(() => {
    if (auth.ready && !auth.signedIn) router.replace("/sign-in");
  }, [auth.ready, auth.signedIn, router]);

  if (!auth.ready || !auth.signedIn) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <Loader2 className="size-6 animate-spin text-text-muted" />
      </div>
    );
  }

  if (!auth.hasOrganization) {
    return (
      <div className="flex min-h-screen flex-col items-center justify-center gap-6 p-6">
        <Logo />
        <p className="max-w-sm text-center text-sm text-text-muted">
          Evidence belongs to an organisation. Create one (or ask an admin to invite you) to continue.
        </p>
        <CreateOrganization afterCreateOrganizationUrl="/projects" />
      </div>
    );
  }

  return (
    <>
      <LiveEvents />
      {children}
    </>
  );
}
