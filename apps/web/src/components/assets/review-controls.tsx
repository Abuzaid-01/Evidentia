"use client";

// Basic UI (functional first; styling to be improved later).
import { useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { api, unwrap } from "@/lib/api/client";
import { keys } from "@/lib/api/hooks";
import type { AssetDetail } from "@/lib/api/types";

type Decision = "approve" | "reject";

/** Reviewer actions: decide on each observation, complete the review, and find similar images. */
export function ReviewControls({ asset, canReview }: { asset: AssetDetail; canReview: boolean }) {
  const client = useQueryClient();
  const reviewable = ["ready", "review_required"].includes(asset.state);
  const decidable = asset.observations.filter(
    (o) => ["activity", "condition", "object", "sensitive", "people"].includes(o.ontology_type) && o.status !== "rejected",
  );
  const similar = useQuery({
    queryKey: [...keys.asset(asset.id), "similar"],
    enabled: reviewable,
    retry: false,
    queryFn: async () => unwrap(await api.POST("/v1/search/similar", { body: { asset_id: asset.id, limit: 6, same_project: true } })),
  });

  async function send(body: { decisions: { observation_id: string; decision: Decision }[]; complete: boolean }) {
    try {
      unwrap(await api.POST("/v1/assets/{asset_id}/review", { params: { path: { asset_id: asset.id } }, body }));
      await client.invalidateQueries({ queryKey: keys.asset(asset.id) });
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Review failed");
    }
  }

  return (
    <Card className="p-4 text-sm">
      {canReview && reviewable && (
        <>
          <h2 className="mb-2 font-semibold">Review observations</h2>
          <ul className="flex flex-col gap-1">
            {decidable.map((o) => (
              <li key={o.id} className="flex items-center justify-between gap-2 text-xs">
                <span>
                  {o.ontology_type}: <b>{o.subject}</b> {o.predicate} · {o.status}
                  {o.confidence != null ? ` · ${Math.round(o.confidence * 100)}%` : ""}
                </span>
                {o.status === "proposed" && (
                  <span className="flex gap-1">
                    <Button size="sm" variant="secondary" onClick={() => send({ decisions: [{ observation_id: o.id, decision: "approve" }], complete: false })}>Approve</Button>
                    <Button size="sm" variant="ghost" onClick={() => send({ decisions: [{ observation_id: o.id, decision: "reject" }], complete: false })}>Reject</Button>
                  </span>
                )}
              </li>
            ))}
          </ul>
          <Button size="sm" className="mt-3" onClick={() => send({ decisions: [], complete: true })}>
            Mark review complete
          </Button>
        </>
      )}
      <h2 className="mb-2 mt-4 font-semibold">Visually similar</h2>
      {similar.error ? (
        <p className="text-xs text-text-muted">{similar.error instanceof Error ? similar.error.message : "Unavailable"}</p>
      ) : (
        <div className="flex flex-wrap gap-2">
          {similar.data?.map((s) => (
            <Link key={s.asset.id} href={`/assets/${s.asset.id}`} title={`similarity ${s.similarity}`}>
              {s.asset.thumb_url ? (
                // eslint-disable-next-line @next/next/no-img-element
                <img src={s.asset.thumb_url} alt="" className="h-14 w-20 rounded object-cover" />
              ) : (
                <span className="text-xs">{s.asset.original_filename}</span>
              )}
            </Link>
          ))}
        </div>
      )}
      <p className="mt-3 text-xs text-text-subtle">Asset ID (for linking to claims): <code>{asset.id}</code></p>
    </Card>
  );
}
