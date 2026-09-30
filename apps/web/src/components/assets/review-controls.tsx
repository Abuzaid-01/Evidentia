"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, CheckCheck, X } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { api, unwrap } from "@/lib/api/client";
import { keys } from "@/lib/api/hooks";
import type { AssetDetail } from "@/lib/api/types";

type Decision = "approve" | "reject";

const label = (value: string) => value.replace(/_/g, " ");

/** Reviewer actions: decide on each observation, complete the review, and find similar images. */
export function ReviewControls({ asset, canReview }: { asset: AssetDetail; canReview: boolean }) {
  const client = useQueryClient();
  const [busy, setBusy] = useState<string | null>(null);
  const reviewable = ["ready", "review_required"].includes(asset.state);
  const decidable = asset.observations.filter(
    (o) =>
      ["activity", "condition", "object", "sensitive", "people"].includes(o.ontology_type) &&
      ["proposed", "verified", "rejected"].includes(o.status),
  );
  const pending = decidable.filter((o) => o.status === "proposed");
  const similar = useQuery({
    queryKey: [...keys.asset(asset.id), "similar"],
    enabled: reviewable,
    retry: false,
    queryFn: async () => unwrap(await api.POST("/v1/search/similar", { body: { asset_id: asset.id, limit: 6, same_project: true } })),
  });

  async function send(
    key: string,
    body: { decisions: { observation_id: string; decision: Decision }[]; complete: boolean },
    success: string,
  ) {
    setBusy(key);
    try {
      unwrap(await api.POST("/v1/assets/{asset_id}/review", { params: { path: { asset_id: asset.id } }, body }));
      await client.invalidateQueries({ queryKey: keys.asset(asset.id) });
      toast.success(success);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Review failed");
    } finally {
      setBusy(null);
    }
  }

  const decide = (id: string, subject: string, decision: Decision) =>
    send(id, { decisions: [{ observation_id: id, decision }], complete: false }, decision === "approve" ? `Verified: ${label(subject)}` : `Rejected: ${label(subject)}`);

  return (
    <Card className="p-4 text-sm">
      {canReview && reviewable && (
        <>
          <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
            <div>
              <h2 className="font-semibold">Review what the AI found</h2>
              <p className="text-xs text-text-muted">
                {pending.length ? `${pending.length} finding${pending.length === 1 ? "" : "s"} waiting for a decision.` : "Every finding has been decided."}
              </p>
            </div>
            {pending.length > 1 && (
              <Button
                size="sm"
                variant="secondary"
                loading={busy === "all"}
                disabled={!!busy}
                onClick={() =>
                  send("all", { decisions: pending.map((o) => ({ observation_id: o.id, decision: "approve" as const })), complete: false }, `Verified ${pending.length} findings`)
                }
              >
                {busy !== "all" && <CheckCheck />} Approve all
              </Button>
            )}
          </div>

          <ul className="flex flex-col divide-y divide-border rounded-lg border border-border">
            {decidable.map((o) => (
              <li key={o.id} className="flex items-center justify-between gap-3 px-3 py-2">
                <span className="min-w-0 text-xs">
                  <span className="text-text-muted">{o.ontology_type}: </span>
                  <b className="text-sm">{label(o.subject)}</b> {label(o.predicate)}
                  {o.confidence != null && <span className="text-text-muted"> · {Math.round(o.confidence * 100)}%</span>}
                </span>
                {o.status === "proposed" ? (
                  <span className="flex shrink-0 gap-1.5">
                    <Button size="sm" loading={busy === o.id} disabled={!!busy} onClick={() => decide(o.id, o.subject, "approve")}>
                      {busy !== o.id && <Check />} Approve
                    </Button>
                    <Button size="sm" variant="secondary" disabled={!!busy} onClick={() => decide(o.id, o.subject, "reject")}>
                      <X /> Reject
                    </Button>
                  </span>
                ) : o.status === "verified" ? (
                  <Badge tone="accent" className="shrink-0"><Check /> Verified</Badge>
                ) : (
                  <Badge tone="danger" className="shrink-0"><X /> Rejected</Badge>
                )}
              </li>
            ))}
          </ul>

          <Button
            size="sm"
            className="mt-3"
            loading={busy === "complete"}
            disabled={!!busy}
            onClick={() => send("complete", { decisions: [], complete: true }, "Review completed: this photo can now be used as proof")}
          >
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
