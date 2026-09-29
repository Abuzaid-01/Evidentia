import { Copy, EyeOff, FileVideo, ImageOff, Users } from "lucide-react";
import Link from "next/link";

import { Card } from "@/components/ui/card";
import type { AssetSummary } from "@/lib/api/types";
import { formatDate, formatDuration, humanize, percent } from "@/lib/utils";

import { StateBadge } from "./state-badge";

export function AssetCard({ asset }: { asset: AssetSummary }) {
  const flags = (asset.flags ?? {}) as { people_present?: boolean; sensitive?: string[] };
  const duplicate = !!asset.exact_duplicate_of_id;
  return (
    <Link href={`/assets/${asset.id}`} className="group">
      <Card className="overflow-hidden transition group-hover:-translate-y-0.5 group-hover:border-accent/50">
        <div className="relative aspect-[4/3] bg-surface-muted">
          {asset.thumb_url ? (
            // Signed Cloudinary rendition (t_ev_thumb: smart-cropped, f_auto/q_auto)
            // eslint-disable-next-line @next/next/no-img-element
            <img src={asset.thumb_url} alt={asset.caption ?? asset.original_filename ?? "Field media"} loading="lazy" className="size-full object-cover" />
          ) : (
            <div className="flex size-full items-center justify-center text-text-subtle">
              <ImageOff className="size-6" />
            </div>
          )}
          <div className="absolute left-2 top-2">
            <StateBadge state={asset.state} />
          </div>
          <div className="absolute bottom-2 right-2 flex gap-1">
            {asset.resource_type === "video" && (
              <span className="flex items-center gap-1 rounded-md bg-black/60 px-1.5 py-0.5 text-[11px] text-white">
                <FileVideo className="size-3" />
                {formatDuration(asset.duration_seconds)}
              </span>
            )}
            {flags.people_present && (
              <span className="rounded-md bg-black/60 p-1 text-white" title="People visible">
                <Users className="size-3" />
              </span>
            )}
            {!!flags.sensitive?.length && (
              <span className="rounded-md bg-black/60 p-1 text-white" title={`Sensitive: ${flags.sensitive.join(", ")}`}>
                <EyeOff className="size-3" />
              </span>
            )}
            {duplicate && (
              <span className="rounded-md bg-black/60 p-1 text-white" title="Exact duplicate">
                <Copy className="size-3" />
              </span>
            )}
          </div>
        </div>
        <div className="p-3">
          <p className="line-clamp-2 min-h-10 text-sm">{asset.caption ?? asset.original_filename ?? "—"}</p>
          <div className="mt-2 flex items-center justify-between gap-2 text-xs text-text-muted">
            <span className="truncate">
              {asset.top_activity ? (
                <>
                  {humanize(asset.top_activity)} <span className="text-text-subtle">· {percent(asset.top_activity_confidence)}</span>
                </>
              ) : (
                "No activity yet"
              )}
            </span>
            <span className="shrink-0">{formatDate(asset.capture_time)}</span>
          </div>
        </div>
      </Card>
    </Link>
  );
}
