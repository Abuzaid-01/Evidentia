"use client";

// Basic UI (functional first; styling to be improved later).
import { useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useParams } from "next/navigation";
import { type FormEvent } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { ErrorState } from "@/components/ui/feedback";
import { Input, Select } from "@/components/ui/form";
import { PageHeader } from "@/components/ui/page-header";
import { api, unwrap } from "@/lib/api/client";

type ClaimType = "descriptive" | "progress" | "outcome" | "metric";
type SourceType = "field_survey" | "sensor" | "operational_record" | "third_party" | "visual_count";

export default function ClaimsPage() {
  const { projectId } = useParams<{ projectId: string }>();
  const client = useQueryClient();
  const claims = useQuery({
    queryKey: ["projects", projectId, "claims"],
    queryFn: async () => unwrap(await api.GET("/v1/projects/{project_id}/claims", { params: { path: { project_id: projectId } } })),
  });
  const metrics = useQuery({
    queryKey: ["projects", projectId, "metrics"],
    queryFn: async () => unwrap(await api.GET("/v1/projects/{project_id}/metrics", { params: { path: { project_id: projectId } } })),
  });

  async function createClaim(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    try {
      await unwrap(
        await api.POST("/v1/projects/{project_id}/claims", {
          params: { path: { project_id: projectId } },
          body: { statement: String(form.get("statement")), claim_type: form.get("claim_type") as ClaimType },
        }),
      );
      event.currentTarget.reset();
      await client.invalidateQueries({ queryKey: ["projects", projectId, "claims"] });
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed");
    }
  }

  async function createMetric(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    try {
      await unwrap(
        await api.POST("/v1/projects/{project_id}/metrics", {
          params: { path: { project_id: projectId } },
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
      event.currentTarget.reset();
      await client.invalidateQueries({ queryKey: ["projects", projectId, "metrics"] });
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed");
    }
  }

  return (
    <>
      <PageHeader title="Claims & metrics" description="Claims need verified evidence; numbers need a sourced metric." />
      <h2 className="mb-2 text-sm font-semibold">New claim</h2>
      <form onSubmit={createClaim} className="mb-6 flex flex-wrap gap-2">
        <Input name="statement" required minLength={5} placeholder="The storage tank at Site B was structurally completed" className="flex-1" />
        <Select name="claim_type" className="w-40" defaultValue="descriptive">
          <option value="descriptive">descriptive</option>
          <option value="progress">progress</option>
          <option value="outcome">outcome</option>
          <option value="metric">metric</option>
        </Select>
        <Button type="submit">Create</Button>
      </form>

      {claims.error && <ErrorState error={claims.error} />}
      <table className="mb-8 w-full text-left text-sm">
        <thead className="text-xs text-text-muted">
          <tr><th>Statement</th><th>Type</th><th>Status</th><th>Support</th></tr>
        </thead>
        <tbody>
          {claims.data?.map((c) => (
            <tr key={c.id} className="border-t border-border">
              <td className="py-1"><Link className="text-accent hover:underline" href={`/claims/${c.id}`}>{c.statement}</Link></td>
              <td>{c.claim_type}</td>
              <td>{c.status}</td>
              <td>{c.support_level}</td>
            </tr>
          ))}
        </tbody>
      </table>

      <h2 className="mb-2 text-sm font-semibold">Metrics (measured values with a source)</h2>
      <form onSubmit={createMetric} className="mb-4 grid grid-cols-2 gap-2 md:grid-cols-3">
        <Input name="name" required placeholder="Households connected" />
        <Input name="value" required type="number" step="any" placeholder="142" />
        <Input name="unit" placeholder="households" />
        <Input name="method" required placeholder="Door-to-door survey" />
        <Select name="source_type" defaultValue="field_survey">
          <option value="field_survey">field_survey</option>
          <option value="sensor">sensor</option>
          <option value="operational_record">operational_record</option>
          <option value="third_party">third_party</option>
          <option value="visual_count">visual_count</option>
        </Select>
        <Input name="source_reference" required placeholder="Form HH-7, 30 Sep" />
        <Button type="submit" className="w-fit">Add metric</Button>
      </form>
      <ul className="text-sm">
        {metrics.data?.map((m) => (
          <li key={m.id} className="font-mono text-xs">
            {m.id.slice(0, 8)} · {m.name} = {m.value} {m.unit} ({m.source_type}: {m.source_reference})
          </li>
        ))}
      </ul>
    </>
  );
}
