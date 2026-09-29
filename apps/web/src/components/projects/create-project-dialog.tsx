"use client";

import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { Field, Input, Select, Textarea } from "@/components/ui/form";
import { useCreateProject, useTaxonomyPresets } from "@/lib/api/hooks";
import { humanize } from "@/lib/utils";

export function CreateProjectDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const router = useRouter();
  const presets = useTaxonomyPresets();
  const create = useCreateProject();
  const [preset, setPreset] = useState("water_infrastructure");

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    try {
      const project = await create.mutateAsync({
        name: String(form.get("name")),
        description: String(form.get("description") || "") || null,
        starts_on: String(form.get("starts_on") || "") || null,
        ends_on: String(form.get("ends_on") || "") || null,
        taxonomy_preset: preset,
      });
      toast.success("Project created");
      onClose();
      router.push(`/projects/${project.id}`);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Could not create project");
    }
  }

  const activities = presets.data?.find((p) => p.name === preset)?.activities ?? [];

  return (
    <Dialog open={open} onClose={onClose} title="New project" description="A programme or campaign you collect field evidence for.">
      <form onSubmit={onSubmit} className="flex flex-col gap-4">
        <Field label="Name">
          <Input name="name" required minLength={2} placeholder="Community Water Access" autoFocus />
        </Field>
        <Field label="Description">
          <Textarea name="description" placeholder="What the programme delivers, and where." />
        </Field>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Starts">
            <Input name="starts_on" type="date" />
          </Field>
          <Field label="Ends">
            <Input name="ends_on" type="date" />
          </Field>
        </div>
        <Field label="Activity taxonomy" hint="Drives AI tagging questions and upload labels. You can version it later.">
          <Select value={preset} onChange={(e) => setPreset(e.target.value)}>
            {(presets.data ?? []).map((p) => (
              <option key={p.name} value={p.name}>
                {humanize(p.name)}
              </option>
            ))}
          </Select>
        </Field>
        {activities.length > 0 && (
          <div className="flex flex-wrap gap-1.5">
            {activities.map((a) => (
              <span key={a.key} className="rounded-full bg-surface-muted px-2 py-0.5 text-xs text-text-muted">
                {a.label}
              </span>
            ))}
          </div>
        )}
        <div className="mt-2 flex justify-end gap-2">
          <Button type="button" variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" loading={create.isPending}>
            Create project
          </Button>
        </div>
      </form>
    </Dialog>
  );
}
