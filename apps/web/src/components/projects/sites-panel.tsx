"use client";

import { MapPin, Plus } from "lucide-react";
import { useState, type FormEvent } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/feedback";
import { Field, Input } from "@/components/ui/form";
import { useCreateSite, useSites } from "@/lib/api/hooks";

function AddSiteForm({ projectId, onDone }: { projectId: string; onDone: () => void }) {
  const create = useCreateSite(projectId);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const lat = String(form.get("latitude") || "");
    const lng = String(form.get("longitude") || "");
    try {
      await create.mutateAsync({
        name: String(form.get("name")),
        code: String(form.get("code")),
        latitude: lat ? Number(lat) : null,
        longitude: lng ? Number(lng) : null,
        radius_m: Number(form.get("radius_m") || 1000),
      });
      toast.success("Site added");
      onDone();
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Could not add site");
    }
  }

  return (
    <form onSubmit={onSubmit} className="grid gap-3 border-t border-border bg-surface-muted/50 px-5 py-4 sm:grid-cols-2">
      <Field label="Name">
        <Input name="name" required placeholder="Village A" />
      </Field>
      <Field label="Code" hint="Short unique id, e.g. A or BRM-01">
        <Input name="code" required pattern="[A-Za-z0-9_-]+" placeholder="A" />
      </Field>
      <Field label="Latitude">
        <Input name="latitude" type="number" step="any" min={-90} max={90} placeholder="25.75" />
      </Field>
      <Field label="Longitude">
        <Input name="longitude" type="number" step="any" min={-180} max={180} placeholder="71.39" />
      </Field>
      <Field label="Radius (m)" hint="Photos with GPS outside this radius get flagged for review.">
        <Input name="radius_m" type="number" min={10} defaultValue={1000} />
      </Field>
      <div className="flex items-end justify-end gap-2">
        <Button type="button" variant="ghost" onClick={onDone}>
          Cancel
        </Button>
        <Button type="submit" loading={create.isPending}>
          Add site
        </Button>
      </div>
    </form>
  );
}

export function SitesPanel({ projectId, canEdit }: { projectId: string; canEdit: boolean }) {
  const sites = useSites(projectId);
  const [adding, setAdding] = useState(false);

  return (
    <Card>
      <CardHeader
        title="Sites"
        description="Where evidence is collected. GPS in photos is checked against these."
        action={
          canEdit &&
          !adding && (
            <Button size="sm" variant="secondary" onClick={() => setAdding(true)}>
              <Plus /> Add site
            </Button>
          )
        }
      />
      {sites.isLoading ? (
        <CardBody>
          <Skeleton className="h-16" />
        </CardBody>
      ) : sites.data?.length ? (
        <ul className="divide-y divide-border">
          {sites.data.map((site) => (
            <li key={site.id} className="flex items-center gap-3 px-5 py-3">
              <span className="flex size-8 items-center justify-center rounded-lg bg-accent-soft font-mono text-xs font-semibold text-accent">
                {site.code}
              </span>
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-medium">{site.name}</p>
                <p className="text-xs text-text-muted">
                  {site.latitude !== null && site.longitude !== null ? (
                    <span className="inline-flex items-center gap-1 font-mono">
                      <MapPin className="size-3" />
                      {site.latitude?.toFixed(4)}, {site.longitude?.toFixed(4)} · r {site.radius_m} m
                    </span>
                  ) : (
                    "No coordinates"
                  )}
                </p>
              </div>
            </li>
          ))}
        </ul>
      ) : (
        !adding && <CardBody className="text-sm text-text-muted">No sites yet.</CardBody>
      )}
      {adding && <AddSiteForm projectId={projectId} onDone={() => setAdding(false)} />}
    </Card>
  );
}
