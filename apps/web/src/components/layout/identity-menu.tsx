"use client";

import { OrganizationSwitcher, UserButton } from "@clerk/nextjs";
import { LogOut } from "lucide-react";
import { useRouter } from "next/navigation";

import { Badge } from "@/components/ui/badge";
import { useMe } from "@/lib/api/hooks";
import { useAuthState } from "@/lib/auth/auth-bridge";
import { humanize } from "@/lib/utils";

export function IdentityMenu() {
  const auth = useAuthState();
  const { data: me } = useMe();
  const router = useRouter();

  if (auth.mode === "clerk") {
    return (
      <div className="flex flex-col gap-3">
        <OrganizationSwitcher hidePersonal afterSelectOrganizationUrl="/projects" />
        <div className="flex items-center gap-2">
          <UserButton />
          {me && <Badge tone="accent">{humanize(me.role)}</Badge>}
        </div>
      </div>
    );
  }

  return (
    <div className="rounded-lg border border-border bg-surface p-3">
      <div className="flex items-center justify-between gap-2">
        <div className="min-w-0">
          <p className="truncate text-sm font-medium">{me?.user.display_name ?? "…"}</p>
          <p className="truncate text-xs text-text-muted">{me?.organization.name ?? ""}</p>
        </div>
        <button
          type="button"
          className="rounded-md p-1.5 text-text-muted hover:bg-surface-muted hover:text-text"
          title="Switch identity"
          onClick={() => {
            auth.signOut();
            router.push("/sign-in");
          }}
        >
          <LogOut className="size-4" />
        </button>
      </div>
      <div className="mt-2 flex flex-wrap gap-1">
        {me && <Badge tone="accent">{humanize(me.role)}</Badge>}
        <Badge tone="warning">Dev auth</Badge>
      </div>
    </div>
  );
}
