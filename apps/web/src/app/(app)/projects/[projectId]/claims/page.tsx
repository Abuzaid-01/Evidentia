"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronRight, Plus } from "lucide-react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";
import { toast } from "sonner";

import { Badge, type BadgeTone } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { ErrorState, Skeleton } from "@/components/ui/feedback";
import { Input, Select } from "@/components/ui/form";
import { PageHeader } from "@/components/ui/page-header";
import { api, unwrap } from "@/lib/api/client";

type ClaimType = "descriptive" | "progress" | "outcome" | "metric";
type SourceType = "field_survey" | "sensor" | "operational_record" | "third_party" | "visual_count";

const STATUS_TONE: Record<string, BadgeTone> = {
  draft: "neutral",
  in_review: "warning",
  approved: "accent",
  rejected: "danger",
  retracted: "outline",
};
const TYPE_HINT: Record<ClaimType, string> = {
  descriptive: "What is visibly there",
  progress: "What changed over time",
  outcome: "An effect on people (needs a metric)",
  metric: "A number (needs a metric)",
};

export default function ClaimsPage() {
  const { projectId } = useParams<{ projectId: string }>();
  const router = useRouter();
  const client = useQueryClient();
  const [creating, setCreating] = useState(false);
  const [addingMetric, setAddingMetric] = useState(false);
  const [claimType, setClaimType] = useState<ClaimType>("descriptive");
  const pp = { params: { path: { project_id: projectId } } };

  const claims = useQuery({
    queryKey: ["projects", projectId, "claims"],
    queryFn: async () => unwrap(await api.GET("/v1/projects/{project_id}/claims", pp)),
  });
  const metrics = useQuery({
    queryKey: ["projects", projectId, "metrics"],
    queryFn: async () => unwrap(await api.GET("/v1/projects/{project_id}/metrics", pp)),
  });

  async function createClaim(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (creating) return;
    const form = event.currentTarget;
    const statement = String(new FormData(form).get("statement") || "").trim();
    if (statement.length < 5) return toast.error("Write the claim as a full sentence");
    setCreating(true);
    try {
      const claim = unwrap(await api.POST("/v1/projects/{project_id}/claims", { ...pp, body: { statement, claim_type: claimType } }));
      form.reset();
      await client.invalidateQueries({ queryKey: ["projects", projectId, "claims"] });
      toast.success("Claim created: now add proof");
      router.push(`/claims/${claim.id}`);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not create the claim");
      setCreating(false);
    }
  }

  async function createMetric(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (addingMetric) return;
    const formEl = event.currentTarget;
    const form = new FormData(formEl);
    setAddingMetric(true);
    try {
      unwrap(
        await api.POST("/v1/projects/{project_id}/metrics", {
          ...pp,
          body: {
            name: String(form.get("name")),
            value: String(form.get("value")),
            unit: String(form.get("unit") || "") || null,
            method: String(form.get("method")),
            source_type: form.get("source_type") as SourceType,
            source_reference: String(form.get("source_reference")),
          },
        }),
      );
      formEl.reset();
      await client.invalidateQueries({ queryKey: ["projects", projectId, "metrics"] });
      toast.success("Metric added");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not add the metric");
    } finally {
      setAddingMetric(false);
    }
  }

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Claims & metrics"
        description="A claim is a statement you want to put in a report. It needs photo proof verified by a person; any number in it needs a metric with a source."
      />

      <Card>
        <CardHeader title="New claim" description={TYPE_HINT[claimType]} />
        <CardBody>
          <form onSubmit={createClaim} className="flex flex-wrap gap-2">
            <Input name="statement" required minLength={5} placeholder="e.g. Workers cleaned the open manhole on Main Street" className="min-w-64 flex-1" disabled={creating} />
            <Select value={claimType} onChange={(e) => setClaimType(e.target.value as ClaimType)} className="w-40" disabled={creating}>
              <option value="descriptive">descriptive</option>
              <option value="progress">progress</option>
              <option value="outcome">outcome</option>
              <option value="metric">metric</option>
            </Select>
            <Button type="submit" loading={creating}>{!creating && <Plus />} Create claim</Button>
          </form>
        </CardBody>
      </Card>

      <Card>
        <CardHeader title="Claims" description="Open a claim to add proof and send it for approval." />
        <CardBody className="p-0">
          {claims.error && <ErrorState error={claims.error} />}
          {!claims.data && !claims.error && <Skeleton className="m-4 h-24" />}
          {claims.data?.length === 0 && <p className="p-4 text-sm text-text-muted">No claims yet: write your first one above.</p>}
          <ul className="divide-y divide-border">
            {claims.data?.map((c) => (
              <li key={c.id}>
                <Link href={`/claims/${c.id}`} className="group flex items-center gap-3 px-4 py-3 transition-colors hover:bg-surface-muted">
                  <span className="min-w-0 flex-1 truncate text-sm font-medium group-hover:text-accent">{c.statement}</span>
                  <Badge tone="outline">{c.claim_type}</Badge>
                  <Badge tone={STATUS_TONE[c.status]}>{c.status.replace("_", " ")}</Badge>
                  <ChevronRight className="size-4 text-text-subtle transition-transform group-hover:translate-x-0.5" />
                </Link>
              </li>
            ))}
          </ul>
        </CardBody>
      </Card>

      <Card>
        <CardHeader title="Metrics" description="Measured numbers with a declared source. A claim may only state a number that one of these backs up." />
        <CardBody className="flex flex-col gap-4">
          <form onSubmit={createMetric} className="grid grid-cols-1 gap-2 md:grid-cols-3">
            <Input name="name" required placeholder="What was measured, e.g. Manholes cleaned" />
            <Input name="value" required type="number" step="any" placeholder="Value, e.g. 4" />
            <Input name="unit" placeholder="Unit, e.g. manholes" />
            <Input name="method" required placeholder="How it was measured, e.g. Job sheet count" />
            <Select name="source_type" defaultValue="operational_record">
              <option value="field_survey">field survey</option>
              <option value="sensor">sensor</option>
              <option value="operational_record">operational record</option>
              <option value="third_party">third party</option>
              <option value="visual_count">visual count</option>
            </Select>
            <Input name="source_reference" required placeholder="Source, e.g. Job sheets Sep 2026" />
            <Button type="submit" loading={addingMetric} className="w-fit">{!addingMetric && <Plus />} Add metric</Button>
          </form>
          {metrics.data && metrics.data.length > 0 && (
            <ul className="flex flex-col gap-1 text-sm">
              {metrics.data.map((m) => (
                <li key={m.id} className="flex flex-wrap items-center gap-2 rounded-lg border border-border px-3 py-2">
                  <b>{m.name}</b> = {Number(m.value)} {m.unit}
                  <span className="text-xs text-text-muted">{m.source_type.replace("_", " ")}: {m.source_reference}</span>
                </li>
              ))}
            </ul>
          )}
        </CardBody>
      </Card>
    </div>
  );
}
