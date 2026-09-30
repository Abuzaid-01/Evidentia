"use client";

import { SignIn } from "@clerk/nextjs";
import { ArrowRight, Play, ShieldCheck } from "lucide-react";
import { useRouter } from "next/navigation";

import { Logo } from "@/components/layout/logo";
import { DEV_PERSONAS, writeDevIdentity } from "@/lib/auth/dev-auth";
import { config } from "@/lib/config";

function DevSignIn() {
  const router = useRouter();
  return (
    <div className="w-full max-w-md">
      <div className="mb-6">
        <h2 className="text-xl font-semibold">Welcome to Evidentia</h2>
        <p className="mt-1 text-sm text-text-muted">
          No password needed. <b className="text-text">New here? Use Start demo</b>: the fastest, easiest way to see
          the whole idea in a few clicks.
        </p>
      </div>
      <button
        type="button"
        onClick={() => {
          writeDevIdentity({ user: "asha", org: "jalseva", role: "manager" });
          router.push("/demo");
        }}
        className="mb-4 flex w-full items-center justify-between rounded-xl bg-accent px-4 py-4 text-left text-accent-contrast shadow-card transition hover:opacity-90"
      >
        <div>
          <p className="font-semibold">Start demo</p>
          <p className="text-xs opacity-90">One page, one click per step. Real Cloudinary and AI calls.</p>
        </div>
        <Play className="size-5" />
      </button>
      <p className="mb-1 text-xs font-medium uppercase tracking-wider text-text-subtle">Or explore the full real-world workflow</p>
      <p className="mb-3 text-xs text-text-muted">
        Sign in as a team member: field worker uploads, reviewer verifies, manager approves and publishes, just like a
        real organisation.
      </p>
      <div className="flex flex-col gap-2">
        {DEV_PERSONAS.map((persona) => (
          <button
            key={`${persona.user}-${persona.org}`}
            type="button"
            onClick={() => {
              writeDevIdentity({ user: persona.user, org: persona.org, role: persona.role });
              router.push("/projects");
            }}
            className="group flex items-center justify-between rounded-xl border border-border bg-surface px-4 py-3 text-left shadow-card transition hover:border-accent hover:bg-accent-soft"
          >
            <div>
              <p className="text-sm font-medium">{persona.label}</p>
              <p className="text-xs text-text-muted">
                {persona.description} · org <span className="font-mono">{persona.org}</span>
              </p>
            </div>
            <ArrowRight className="size-4 text-text-subtle transition group-hover:translate-x-0.5 group-hover:text-accent" />
          </button>
        ))}
      </div>
    </div>
  );
}

export default function SignInPage() {
  return (
    <div className="grid min-h-screen lg:grid-cols-2">
      <div className="hidden flex-col justify-between bg-accent p-12 text-accent-contrast lg:flex">
        <Logo className="[&_rect]:fill-accent-contrast [&_path]:stroke-accent [&_span]:text-accent-contrast" />
        <div>
          <h1 className="text-4xl font-semibold leading-tight tracking-tight">
            From field media to evidence you can defend.
          </h1>
          <p className="mt-4 max-w-md text-lg opacity-90">
            Upload once. Cloudinary stores and understands it; your team verifies it; every report sentence
            traces back to the pixel it came from.
          </p>
        </div>
        <p className="flex items-center gap-2 text-sm opacity-80">
          <ShieldCheck className="size-4" /> Private by default · signed uploads · auditable
        </p>
      </div>
      <div className="flex items-center justify-center p-6">
        {config.authMode === "clerk" ? <SignIn /> : <DevSignIn />}
      </div>
    </div>
  );
}
