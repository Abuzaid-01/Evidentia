"use client";

// Basic UI (functional first; styling to be improved later).
import { useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useState, type FormEvent } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { ErrorState, Skeleton } from "@/components/ui/feedback";
import { Input, Select } from "@/components/ui/form";
import { api, unwrap } from "@/lib/api/client";

type Action = "validate" | "submit" | "approve" | "reject" | "retract";
type Relation = "supports" | "contradicts" | "context";

export default function ClaimPage() {
  const { claimId } = useParams<{ claimId: string }>();
  const client = useQueryClient();
  const [note, setNote] = useState("");
  const [assetId, setAssetId] = useState("");
  const key = ["claims", claimId];
  const claim = useQuery({
    queryKey: key,
    queryFn: async () => unwrap(await api.GET("/v1/claims/{claim_id}", { params: { path: { claim_id: claimId } } })),
  });
  const projectId = claim.data?.project_id;
  const metrics = useQuery({
    queryKey: ["projects", projectId, "metrics"],
    enabled: !!projectId,
    queryFn: async () => unwrap(await api.GET("/v1/projects/{project_id}/metrics", { params: { path: { project_id: projectId! } } })),
  });
  const asset = useQuery({
    queryKey: ["assets", assetId],
    enabled: /^[0-9a-f-]{36}$/.test(assetId),
    queryFn: async () => unwrap(await api.GET("/v1/assets/{asset_id}", { params: { path: { asset_id: assetId } } })),
  });

  const refresh = () => client.invalidateQueries({ queryKey: key });
  async function run(promise: Promise<{ error?: unknown; data?: unknown; response: Response }>) {
    try {
      unwrap(await promise);
      await refresh();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed");
    }
  }

  function act(action: Action) {
    const path = { params: { path: { claim_id: claimId } } };
    const body = { note: note || null, override: false };
    if (action === "validate") return run(api.POST("/v1/claims/{claim_id}/validate", path));
    if (action === "submit") return run(api.POST("/v1/claims/{claim_id}/submit", { ...path, body }));
    if (action === "approve") return run(api.POST("/v1/claims/{claim_id}/approve", { ...path, body }));
    if (action === "reject") return run(api.POST("/v1/claims/{claim_id}/reject", { ...path, body }));
    return run(api.POST("/v1/claims/{claim_id}/retract", { ...path, body }));
  }

  function addEvidence(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    return run(
      api.POST("/v1/claims/{claim_id}/evidence", {
        params: { path: { claim_id: claimId } },
        body: {
          asset_id: assetId,
          observation_id: String(form.get("observation_id") || "") || null,
          relation: form.get("relation") as Relation,
          note: String(form.get("note") || "") || null,
        },
      }),
    );
  }

  if (claim.error) return <ErrorState error={claim.error} />;
  if (!claim.data) return <Skeleton className="h-64" />;
  const c = claim.data;
  const rules = c.rule_check as { passed?: boolean; problems?: string[] } | null;
  const validation = c.validation as { reasoning?: string; unsupported_parts?: string[]; reason?: string } | null;
  const linkedMetricIds = new Set(c.metrics.map((m) => m.id));

  return (
    <div className="flex flex-col gap-5 text-sm">
      <div>
        <Link href={`/projects/${c.project_id}/claims`} className="text-xs text-accent">← Claims</Link>
        <h1 className="mt-1 text-lg font-semibold">{c.statement}</h1>
        <p className="text-xs text-text-muted">
          {c.claim_type} · status <b>{c.status}</b> · support <b>{c.support_level}</b> · validation {c.validation_verdict ?? "not run"}
        </p>
      </div>

      <section>
        <h2 className="font-semibold">Evidence rules: {rules?.passed ? "✅ passed" : "❌ not met"}</h2>
        <ul className="list-disc pl-5 text-xs">{rules?.problems?.map((p) => <li key={p}>{p}</li>)}</ul>
        {validation && (
          <p className="mt-1 text-xs text-text-muted">
            LLM: {validation.reasoning ?? validation.reason}
            {validation.unsupported_parts?.length ? ` · unsupported: ${validation.unsupported_parts.join("; ")}` : ""}
          </p>
        )}
      </section>

      <section className="flex flex-wrap items-center gap-2">
        <Input value={note} onChange={(e) => setNote(e.target.value)} placeholder="Note (required for reject/retract)" className="w-72" />
        {(["validate", "submit", "approve", "reject", "retract"] as Action[]).map((a) => (
          <Button key={a} size="sm" variant="secondary" onClick={() => act(a)}>{a}</Button>
        ))}
      </section>

      <section>
        <h2 className="font-semibold">Linked evidence</h2>
        <ul className="flex flex-col gap-1">
          {c.evidence.map((e) => (
            <li key={e.id} className="flex items-center gap-2 text-xs">
              {e.thumb_url && (
                // eslint-disable-next-line @next/next/no-img-element
                <img src={e.thumb_url} alt="" className="h-10 w-14 rounded object-cover" />
              )}
              <span>{e.verified ? "✅" : "⚠️"} {e.relation}: {e.pair_summary ?? e.observation_summary ?? "whole asset"} — </span>
              {e.pair_id ? (
                <Link href={`/before-after/${e.pair_id}`} className="text-accent">open comparison</Link>
              ) : (
                <Link href={`/assets/${e.asset_id}`} className="text-accent">{e.asset_caption ?? e.asset_id}</Link>
              )}
              <button className="text-danger" onClick={() => run(api.DELETE("/v1/claims/{claim_id}/evidence/{link_id}", { params: { path: { claim_id: claimId, link_id: e.id } } }))}>
                remove
              </button>
            </li>
          ))}
        </ul>
        <form onSubmit={addEvidence} className="mt-2 flex flex-wrap gap-2">
          <Input value={assetId} onChange={(e) => setAssetId(e.target.value.trim())} placeholder="Asset ID (from the asset page URL)" className="w-80" />
          <Select name="observation_id" className="w-72">
            <option value="">Whole asset</option>
            {asset.data?.observations.map((o) => (
              <option key={o.id} value={o.id}>{o.ontology_type}: {o.subject} ({o.status})</option>
            ))}
          </Select>
          <Select name="relation" className="w-36" defaultValue="supports">
            <option value="supports">supports</option>
            <option value="contradicts">contradicts</option>
            <option value="context">context</option>
          </Select>
          <Input name="note" placeholder="note" className="w-40" />
          <Button type="submit" size="sm">Link</Button>
        </form>
      </section>

      <section>
        <h2 className="font-semibold">Metrics</h2>
        <ul className="text-xs">
          {metrics.data?.map((m) => {
            const linked = linkedMetricIds.has(m.id);
            const path = { params: { path: { claim_id: claimId, metric_id: m.id } } };
            return (
              <li key={m.id}>
                <label>
                  <input
                    type="checkbox"
                    checked={linked}
                    onChange={() => run(linked ? api.DELETE("/v1/claims/{claim_id}/metrics/{metric_id}", path) : api.PUT("/v1/claims/{claim_id}/metrics/{metric_id}", path))}
                  />{" "}
                  {m.name} = {m.value} {m.unit} ({m.source_type}: {m.source_reference})
                </label>
              </li>
            );
          })}
        </ul>
      </section>
    </div>
  );
}
