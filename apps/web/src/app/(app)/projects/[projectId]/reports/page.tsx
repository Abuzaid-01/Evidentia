"use client";

// Basic UI (functional first; styling to be improved later).
import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { type FormEvent } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { ErrorState } from "@/components/ui/feedback";
import { Input, Select } from "@/components/ui/form";
import { PageHeader } from "@/components/ui/page-header";
import { api, unwrap } from "@/lib/api/client";

export default function ReportsPage() {
  const { projectId } = useParams<{ projectId: string }>();
  const router = useRouter();
  const reports = useQuery({
    queryKey: ["projects", projectId, "reports"],
    queryFn: async () => unwrap(await api.GET("/v1/projects/{project_id}/reports", { params: { path: { project_id: projectId } } })),
  });

  async function create(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    try {
      const report = unwrap(
        await api.POST("/v1/projects/{project_id}/reports", {
          params: { path: { project_id: projectId } },
          body: {
            title: String(form.get("title")),
            period_start: String(form.get("period_start") || "") || null,
            period_end: String(form.get("period_end") || "") || null,
            audience: form.get("audience") as "internal" | "external",
          },
        }),
      );
      router.push(`/reports/${report.id}`);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed");
    }
  }

  return (
    <>
      <PageHeader title="Reports" description="Built only from approved claims. Every sentence is cited; published versions are frozen and verifiable." />
      <h2 className="mb-2 text-sm font-semibold">New report (includes every approved claim in the period)</h2>
      <form onSubmit={create} className="mb-6 flex flex-wrap items-center gap-2">
        <Input name="title" required minLength={3} placeholder="Q3 2026 water access report" className="flex-1" />
        <label className="text-xs text-text-muted">from</label>
        <Input name="period_start" type="date" className="w-40" />
        <label className="text-xs text-text-muted">to</label>
        <Input name="period_end" type="date" className="w-40" />
        <Select name="audience" className="w-32" defaultValue="internal">
          <option value="internal">internal</option>
          <option value="external">external</option>
        </Select>
        <Button type="submit">Create</Button>
      </form>

      {reports.error && <ErrorState error={reports.error} />}
      <table className="w-full text-left text-sm">
        <thead className="text-xs text-text-muted">
          <tr><th>Title</th><th>Period</th><th>Audience</th><th>Claims</th><th>Status</th><th>Version</th></tr>
        </thead>
        <tbody>
          {reports.data?.map((r) => (
            <tr key={r.id} className="border-t border-border">
              <td className="py-1"><Link className="text-accent hover:underline" href={`/reports/${r.id}`}>{r.title}</Link></td>
              <td>{r.period_start ?? "…"} → {r.period_end ?? "…"}</td>
              <td>{r.audience}</td>
              <td>{r.claim_ids.length}</td>
              <td>{r.status}</td>
              <td>{r.latest_version || "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  );
}
