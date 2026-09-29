"use client";

import { AlertTriangle, ArrowLeft, Copy, GitFork, RefreshCw, Share2, Sparkles } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useRef, useState } from "react";
import { toast } from "sonner";

import { AssetViewer } from "@/components/assets/asset-viewer";
import { AssetPairs } from "@/components/before-after/asset-pairs";
import type { VideoPlayerHandle } from "@/components/assets/evidence-video-player";
import { LineageModal } from "@/components/assets/lineage-modal";
import { LineagePanel } from "@/components/assets/lineage-panel";
import { ObservationsPanel } from "@/components/assets/observations-panel";
import { ProvenancePanel } from "@/components/assets/provenance-panel";
import { ReviewControls } from "@/components/assets/review-controls";
import { RunsPanel } from "@/components/assets/runs-panel";
import { StateBadge } from "@/components/assets/state-badge";
import { VideoSegments } from "@/components/assets/video-segments";
import { ShareDialog } from "@/components/share/share-dialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { ErrorState, Skeleton } from "@/components/ui/feedback";
import { useAsset, useMe, useReanalyze } from "@/lib/api/hooks";
import { hasRole } from "@/lib/api/types";
import { humanize, percent } from "@/lib/utils";

export default function AssetPage() {
  const { assetId } = useParams<{ assetId: string }>();
  const asset = useAsset(assetId);
  const { data: me } = useMe();
  const reanalyze = useReanalyze(assetId);

  // Lineage and Share dialogs
  const [lineageOpen, setLineageOpen] = useState(false);
  const [shareOpen, setShareOpen] = useState(false);

  // Video player state — coordinate seek between components
  const playerRef = useRef<VideoPlayerHandle>(null);
  const [currentTimeMs, setCurrentTimeMs] = useState(0);

  const handleTimeUpdate = useCallback((ms: number) => {
    setCurrentTimeMs(ms);
  }, []);

  const handleSeek = useCallback((ms: number) => {
    playerRef.current?.seekTo(ms);
  }, []);

  if (asset.error) return <ErrorState error={asset.error} onRetry={() => asset.refetch()} />;
  if (!asset.data) {
    return (
      <div className="grid gap-6 lg:grid-cols-[1.2fr_1fr]">
        <Skeleton className="aspect-[4/3]" />
        <Skeleton className="h-96" />
      </div>
    );
  }

  const a = asset.data;
  const reasons = (a.review_reasons ?? []) as string[];
  const canReanalyze = hasRole(me?.role, "reviewer") && ["ready", "review_required", "failed_permanent"].includes(a.state);
  const isVideo = a.resource_type === "video";

  return (
    <>
      <div className="mb-5 flex flex-wrap items-center justify-between gap-3">
        <div className="min-w-0">
          <Link href={`/projects/${a.project_id}/media`} className="mb-2 inline-flex items-center gap-1 text-sm text-text-muted hover:text-text">
            <ArrowLeft className="size-4" /> Media library
          </Link>
          <div className="flex flex-wrap items-center gap-2">
            <h1 className="truncate text-xl font-semibold tracking-tight">{a.original_filename ?? a.id}</h1>
            <StateBadge state={a.state} />
            <Badge tone="outline">generation {a.analysis_generation}</Badge>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Button
            variant="secondary"
            onClick={() => setLineageOpen(true)}
          >
            <GitFork className="size-4" /> Lineage
          </Button>
          <Button
            variant="secondary"
            onClick={() => setShareOpen(true)}
          >
            <Share2 className="size-4" /> Share
          </Button>
          {canReanalyze && (
            <Button
              variant="secondary"
              loading={reanalyze.isPending}
              onClick={async () => {
                try {
                  await reanalyze.mutateAsync();
                  toast.success("Re-analysis queued. Previous observations are kept as history.");
                } catch (error) {
                  toast.error(error instanceof Error ? error.message : "Could not re-analyse");
                }
              }}
            >
              <RefreshCw /> Re-analyse
            </Button>
          )}
        </div>
      </div>

      <div className="grid gap-6 lg:grid-cols-[1.2fr_1fr]">
        <div className="flex flex-col gap-6">
          <AssetViewer
            asset={a}
            onTimeUpdate={isVideo ? handleTimeUpdate : undefined}
            playerRef={playerRef}
          />
          <ReviewControls asset={a} canReview={hasRole(me?.role, "reviewer")} />

          {/* Video timeline — only for video assets with segment observations */}
          {isVideo && (
            <VideoSegments
              observations={a.observations}
              currentTimeMs={currentTimeMs}
              onSeek={handleSeek}
            />
          )}

          <ObservationsPanel
            observations={a.observations}
            onSeek={isVideo ? handleSeek : undefined}
          />
          <RunsPanel runs={a.analysis_runs} />
        </div>

        <div className="flex flex-col gap-6">
          <Card className="p-5">
            <div className="flex items-center gap-2 text-xs font-medium uppercase tracking-wider text-accent">
              <Sparkles className="size-3.5" /> AI summary
            </div>
            <p className="mt-2 text-base leading-relaxed">{a.caption ?? "No caption yet."}</p>
            {a.top_activity && (
              <p className="mt-3 text-sm text-text-muted">
                Most likely activity: <span className="font-medium text-text">{humanize(a.top_activity)}</span> ({percent(a.top_activity_confidence)})
              </p>
            )}
            {a.state_reason && a.state === "failed_permanent" && (
              <p className="mt-3 rounded-lg bg-danger-soft px-3 py-2 text-sm text-danger">{a.state_reason}</p>
            )}
          </Card>

          {reasons.length > 0 && (
            <Card className="border-warning/40 p-5">
              <div className="flex items-center gap-2 text-sm font-semibold text-warning">
                <AlertTriangle className="size-4" /> Why this needs a human
              </div>
              <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-text-muted">
                {reasons.map((reason) => (
                  <li key={reason}>{reason}</li>
                ))}
              </ul>
              {a.review_priority !== null && (
                <p className="mt-3 text-xs text-text-subtle">Review priority score: {a.review_priority?.toFixed(2)}</p>
              )}
            </Card>
          )}

          {(a.exact_duplicate_of_id || a.near_duplicates.length > 0) && (
            <Card className="p-5">
              <div className="flex items-center gap-2 text-sm font-semibold">
                <Copy className="size-4" /> Possible duplicates
              </div>
              <ul className="mt-2 space-y-1 text-sm">
                {a.exact_duplicate_of_id && (
                  <li>
                    <Link className="text-accent hover:underline" href={`/assets/${a.exact_duplicate_of_id}`}>
                      Identical file (SHA-256 match)
                    </Link>
                  </li>
                )}
                {a.near_duplicates.map((d) => (
                  <li key={d.asset_id}>
                    <Link className="text-accent hover:underline" href={`/assets/${d.asset_id}`}>
                      Visually similar (pHash distance {d.distance})
                    </Link>
                  </li>
                ))}
              </ul>
            </Card>
          )}

          {!isVideo && ["ready", "review_required"].includes(a.state) && (
            <AssetPairs asset={a} canSuggest={hasRole(me?.role, "contributor")} />
          )}
          <ProvenancePanel asset={a} />
          <LineagePanel asset={a} />
        </div>
      </div>

      <LineageModal
        assetId={a.id}
        open={lineageOpen}
        onClose={() => setLineageOpen(false)}
      />
      <ShareDialog
        projectId={a.project_id}
        targetType="evidence"
        targetId={a.id}
        defaultTitle={`Evidence Share: ${a.original_filename ?? a.id}`}
        open={shareOpen}
        onClose={() => setShareOpen(false)}
      />
    </>
  );
}
