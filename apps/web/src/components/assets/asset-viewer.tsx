"use client";

import { Download, ImageOff, Loader2 } from "lucide-react";
import { useRef, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { fetchOriginalUrl, useMediaUrl, useMe, useStreamUrl } from "@/lib/api/hooks";
import type { AssetDetail } from "@/lib/api/types";

import {
  EvidenceVideoPlayer,
  type VideoPlayerHandle,
} from "./evidence-video-player";

const NO_MEDIA = new Set(["awaiting_upload", "expired"]);

interface Props {
  asset: AssetDetail;
  /** Called with the current playback time in ms (for video timeline sync). */
  onTimeUpdate?: (ms: number) => void;
  /** Exposed ref so parent can call seekTo(ms). */
  playerRef?: React.Ref<VideoPlayerHandle>;
}

export function AssetViewer({ asset, onTimeUpdate, playerRef }: Props) {
  const available = !NO_MEDIA.has(asset.state);
  const isVideo = asset.resource_type === "video";

  const { data: me } = useMe();
  const cloudName = me?.cloudinary_cloud_name;

  // Always fetch the review rendition (images always need it; videos use it as fallback)
  const media = useMediaUrl(asset.id, "review", available);

  // For videos, also fetch the signed stream URL (sp_auto / HLS)
  const stream = useStreamUrl(asset.id, available && isVideo);

  const [opening, setOpening] = useState(false);
  const internalPlayerRef = useRef<VideoPlayerHandle>(null);
  // Use the parent's ref if provided, otherwise our own internal one
  const effectiveRef = playerRef ?? internalPlayerRef;

  async function openOriginal() {
    setOpening(true);
    try {
      const original = await fetchOriginalUrl(asset.id);
      window.open(original.url, "_blank", "noopener,noreferrer");
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Could not open original");
    } finally {
      setOpening(false);
    }
  }

  return (
    <Card className="overflow-hidden">
      <div className="flex aspect-[4/3] items-center justify-center bg-[#0b0f0d]">
        {!available ? (
          <ImageOff className="size-8 text-white/40" />
        ) : media.isLoading || (isVideo && stream.isLoading) ? (
          <Loader2 className="size-6 animate-spin text-white/60" />
        ) : isVideo && cloudName ? (
          <EvidenceVideoPlayer
            ref={effectiveRef}
            cloudName={cloudName}
            publicId={asset.cloudinary.public_id}
            assetId={asset.id}
            deliveryType={asset.cloudinary.delivery_type}
            streamUrl={stream.data?.url}
            reviewUrl={media.data?.url}
            onTimeUpdate={onTimeUpdate}
          />
        ) : isVideo && media.data ? (
          /* Fallback: plain <video> if no cloud name available */
          <video src={media.data.url} controls className="size-full object-contain" />
        ) : media.data ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img src={media.data.url} alt={asset.caption ?? "Field media"} className="size-full object-contain" />
        ) : null}
      </div>
      <div className="flex flex-wrap items-center justify-between gap-3 border-t border-border px-4 py-3 text-xs text-text-muted">
        <span className="font-mono">
          {isVideo && stream.data
            ? "sp_auto (adaptive stream)"
            : media.data?.named_transformation ? `t_${media.data.named_transformation}` : "rendition"}
          {" · "}
          {isVideo && stream.data
            ? stream.data.transformation
            : media.data?.transformation}
        </span>
        <Button size="sm" variant="secondary" loading={opening} disabled={!available || !asset.format} onClick={openOriginal}>
          <Download /> Original (expiring link)
        </Button>
      </div>
    </Card>
  );
}
