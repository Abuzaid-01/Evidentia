"use client";

// Demo entry point: pick (or create) a project, then run the one-page demo.
import { useRouter } from "next/navigation";
import { type FormEvent } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/feedback";
import { Input } from "@/components/ui/form";
import { useCreateProject, useProjects } from "@/lib/api/hooks";

export default function DemoStartPage() {
  const router = useRouter();
  const { data: projects, isLoading } = useProjects();
  const create = useCreateProject();

  function onCreate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const name = String(new FormData(event.currentTarget).get("name") || "").trim();
    if (name.length < 2) return;
    create.mutate(
      { name, taxonomy_preset: "water_infrastructure" },
      {
        onSuccess: (project) => router.push(`/projects/${project.id}/demo`),
        onError: (err) => toast.error(err instanceof Error ? err.message : "Could not create project"),
      },
    );
  }

  return (
    <div className="mx-auto flex max-w-2xl flex-col gap-4 text-sm">
      <h1 className="text-2xl font-semibold">Demo mode</h1>
      <p className="text-text-muted">Choose the project to present. Everything in the demo uses the real services.</p>
      {isLoading && <Skeleton className="h-24" />}
      <div className="flex flex-col gap-2">
        {projects?.map((p) => (
          <button
            key={p.id}
            type="button"
            onClick={() => router.push(`/projects/${p.id}/demo`)}
            className="flex items-center justify-between rounded-xl border border-border bg-surface px-4 py-3 text-left transition hover:border-accent hover:bg-accent-soft"
          >
            <span className="font-medium">{p.name}</span>
            <span className="text-xs text-text-muted">{p.stats?.assets_total ?? 0} media</span>
          </button>
        ))}
      </div>
      <form onSubmit={onCreate} className="flex gap-2">
        <Input name="name" placeholder="…or start a new project, e.g. Sewer maintenance demo" className="flex-1" />
        <Button type="submit" loading={create.isPending}>Create</Button>
      </form>
    </div>
  );
}
