"use client";

// Basic UI (functional first; styling to be improved later).
import { Film } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useState, type FormEvent } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ErrorState } from "@/components/ui/feedback";
import { Input } from "@/components/ui/form";
import { PageHeader } from "@/components/ui/page-header";
import { api, unwrap } from "@/lib/api/client";
import type { SearchResponse } from "@/lib/api/types";

export default function SearchPage() {
  const { projectId } = useParams<{ projectId: string }>();
  const [query, setQuery] = useState("");
  const [data, setData] = useState<SearchResponse | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(false);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setLoading(true);
    setError(null);
    try {
      setData(unwrap(await api.POST("/v1/search", { body: { project_id: projectId, query, limit: 30, use_llm_planner: true } })));
    } catch (err) {
      setError(err);
    } finally {
      setLoading(false);
    }
  }

  function click(assetId: string, rank: number) {
    if (!data) return;
    void api.POST("/v1/search/{query_id}/feedback", {
      params: { path: { query_id: data.query_id } },
      body: { asset_id: assetId, action: "click", rank },
    });
  }

  const f = data?.plan.filters;
  return (
    <>
      <PageHeader title="Search evidence" description='e.g. "pipe installation at site A in August", "verified videos of the tank"' />
      <form onSubmit={onSubmit} className="mb-4 flex gap-2">
        <Input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search in plain language…" />
        <Button type="submit" loading={loading}>Search</Button>
      </form>
      {error !== null && <ErrorState error={error} />}
      {data && (
        <div className="mb-4 rounded border border-border bg-surface p-3 text-xs text-text-muted">
          <div>planner: {data.plan.planner} · {data.took_ms} ms · text: &ldquo;{data.plan.semantic_text}&rdquo;</div>
          <div>
            filters: sites {f?.site_ids?.length ?? 0}, activities [{f?.activities?.join(", ")}], dates {f?.date_from ?? "…"} → {f?.date_to ?? "…"}
            {f?.media_type ? `, ${f.media_type}` : ""}
            {f?.verified_only ? ", verified only" : ""}
          </div>
          <div>retrievers: {Object.entries(data.retrievers).map(([k, v]) => `${k}=${(v as { hits?: number }).hits ?? "err"}`).join(" · ")}</div>
          {!!data.plan.warnings?.length && <div className="text-warning">{data.plan.warnings.join("; ")}</div>}
        </div>
      )}
      {data && data.results.length > 0 && (data.query_terms?.length ?? 0) > 0 && data.complete_matches === 0 && (
        <div className="mb-2 rounded border border-warning/40 bg-warning/10 p-2 text-sm text-warning">
          No evidence matches every word of your search. Showing the closest partial matches; each one lists the words it doesn&apos;t mention.
        </div>
      )}
      {data && data.results.length === 0 && <div className="mb-2 text-sm text-text-muted">No matching evidence.</div>}
      <ol className="flex flex-col gap-2">
        {data?.results.map((r, i) => {
          const isVideo = r.asset.resource_type === "video";
          return (
            <li key={r.asset.id} className="flex gap-3 rounded border border-border bg-surface p-2">
              {r.asset.thumb_url && (
                <div className="relative h-20 w-28 shrink-0">
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img src={r.asset.thumb_url} alt="" className="h-full w-full rounded object-cover" />
                  {isVideo && (
                    <div className="absolute bottom-1 right-1 flex items-center gap-0.5 rounded bg-black/60 px-1 py-0.5 text-[10px] text-white">
                      <Film className="size-3" />
                      {r.asset.duration_seconds ? `${Math.floor(r.asset.duration_seconds / 60)}:${Math.round(r.asset.duration_seconds % 60).toString().padStart(2, "0")}` : "video"}
                    </div>
                  )}
                </div>
              )}
              <div className="min-w-0 text-sm">
                <Link href={`/assets/${r.asset.id}`} onClick={() => click(r.asset.id, i + 1)} className="font-medium text-accent hover:underline">
                  {i + 1}. {r.asset.caption ?? r.asset.original_filename}
                </Link>
                <div className="text-xs text-text-muted">
                  {r.asset.capture_time?.slice(0, 10)} · {r.asset.state} · score {r.score.toFixed(4)}
                </div>
                <div className="text-xs">Why: {r.reasons.join(", ")}</div>
                {r.matched_observations.length > 0 && (
                  <div className="mt-1 flex flex-wrap gap-1">
                    {r.matched_observations.map((o) => (
                      <Badge key={o.id} tone="outline" className="text-[11px]">
                        {o.subject} ({o.status}{o.confidence ? ` ${Math.round(o.confidence * 100)}%` : ""})
                      </Badge>
                    ))}
                  </div>
                )}
              </div>
            </li>
          );
        })}
      </ol>
      {data && data.results.length === 0 && <p className="text-sm text-text-muted">No results.</p>}
    </>
  );
}
