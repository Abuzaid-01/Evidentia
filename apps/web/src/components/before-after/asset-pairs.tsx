"use client";

import { GitCompareArrows } from "lucide-react";
import Link from "next/link";
import { toast } from "sonner";

import { GradeBadge, PairStatusBadge } from "@/components/before-after/badges";
import { Button } from "@/components/ui/button";
import { Card, CardHeader } from "@/components/ui/card";
import { usePairs, useSuggestPairs } from "@/lib/api/hooks";
import type { AssetDetail } from "@/lib/api/types";
import { formatDate } from "@/lib/utils";

/** Comparisons this photo takes part in, and a shortcut to find earlier photos of the same place. */
export function AssetPairs({ asset, canSuggest }: { asset: AssetDetail; canSuggest: boolean }) {
  const pairs = usePairs(asset.project_id, { asset_id: asset.id });
  const suggest = useSuggestPairs(asset.project_id);
  const items = pairs.data ?? [];
  const canAnchor = canSuggest && Boolean(asset.capture_time);

  if (!items.length && !canAnchor) return null;
  return (
    <Card>
      <CardHeader
        title={
          <span className="flex items-center gap-2">
            <GitCompareArrows className="size-4 text-accent" /> Before / after
          </span>
        }
        action={
          canAnchor && (
            <Button
              size="sm"
              variant="secondary"
              loading={suggest.isPending}
              onClick={async () => {
                try {
                  const out = await suggest.mutateAsync({
                    anchor_asset_id: asset.id,
                    max_distance_m: 250,
                    min_gap_days: 7,
                    per_anchor: 3,
                    limit: 3,
                  });
                  toast[out.pairs.length ? "success" : "info"](
                    out.pairs.length ? `${out.pairs.length} earlier photos queued for alignment` : "No earlier photos of this place found",
                  );
                } catch (error) {
                  toast.error(error instanceof Error ? error.message : "Could not search");
                }
              }}
            >
              Find earlier photos
            </Button>
          )
        }
      />
      {items.length > 0 && (
        <ul className="divide-y divide-border text-sm">
          {items.map((p) => {
            const other = p.after.id === asset.id ? p.before : p.after;
            return (
              <li key={p.id}>
                <Link href={`/before-after/${p.id}`} className="flex items-center gap-3 px-5 py-2.5 hover:bg-surface-muted">
                  {other.thumb_url && (
                    // eslint-disable-next-line @next/next/no-img-element
                    <img src={other.thumb_url} alt="" className="h-10 w-14 rounded object-cover" />
                  )}
                  <span className="flex-1 truncate">
                    {p.after.id === asset.id ? "Before" : "After"}: {formatDate(other.capture_time)}
                  </span>
                  <GradeBadge grade={p.alignment_grade} />
                  <PairStatusBadge status={p.status} />
                </Link>
              </li>
            );
          })}
        </ul>
      )}
    </Card>
  );
}
