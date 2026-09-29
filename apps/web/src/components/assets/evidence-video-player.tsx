"use client";

import { Film, Loader2 } from "lucide-react";
import {
  forwardRef,
  useCallback,
  useEffect,
  useId,
  useImperativeHandle,
  useRef,
  useState,
} from "react";

import { config } from "@/lib/config";

import type { VideoPlayer } from "cloudinary-video-player";

/**
 * Imperative handle exposed via ref so parent components (observation panel,
 * search results) can seek the player to a specific millisecond.
 */
export interface VideoPlayerHandle {
  seekTo: (ms: number) => void;
  currentTime: () => number;
}

interface Props {
  /** Cloudinary cloud name (from /me). */
  cloudName: string;
  /** The public_id of the video asset in Cloudinary. */
  publicId: string;
  /** Asset UUID — used to fetch chapters from the API. */
  assetId: string;
  /** Delivery type, almost always "authenticated". */
  deliveryType?: string;
  /** Optional signed streaming URL (sp_auto / m3u8). */
  streamUrl?: string;
  /** Fallback signed review URL (plain mp4). */
  reviewUrl?: string;
  /** Called whenever the player's current time crosses a segment boundary. */
  onTimeUpdate?: (ms: number) => void;
  /** Called when the player starts playing a new segment via seekTo. */
  onSegmentSeek?: (ms: number) => void;
}

/**
 * Cloudinary Video Player with:
 * - Adaptive streaming (sp_auto / HLS / DASH)
 * - WebVTT chapters built from timestamped observations
 * - Imperative seek API for citation → video segment linking
 */
export const EvidenceVideoPlayer = forwardRef<VideoPlayerHandle, Props>(
  function EvidenceVideoPlayer(
    {
      cloudName,
      publicId,
      assetId,
      deliveryType = "authenticated",
      streamUrl,
      reviewUrl,
      onTimeUpdate,
      onSegmentSeek,
    },
    ref,
  ) {
    const reactId = useId();
    const videoId = `ev-player-${reactId.replace(/:/g, "")}`;
    const playerRef = useRef<VideoPlayer | null>(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);

    // Expose seekTo via imperative handle
    useImperativeHandle(
      ref,
      () => ({
        seekTo(ms: number) {
          const player = playerRef.current;
          if (player) {
            player.currentTime(ms / 1000);
            player.play();
            onSegmentSeek?.(ms);
          }
        },
        currentTime() {
          return ((playerRef.current?.currentTime() as number) ?? 0) * 1000;
        },
      }),
      [onSegmentSeek],
    );

    // Chapters URL — served by the API
    const chaptersUrl = `${config.apiBaseUrl}/v1/assets/${assetId}/chapters.vtt`;

    const initPlayer = useCallback(async () => {
      const el = document.getElementById(videoId);
      if (!el) return;
      try {
        // Dynamic import so SSR doesn't fail (cloudinary-video-player is browser-only)
        const cldVideoPlayer = await import("cloudinary-video-player");
        await import("cloudinary-video-player/cld-video-player.min.css");

        const player = cldVideoPlayer.videoPlayer(videoId, {
          cloud_name: cloudName,
          secure: true,
          controls: true,
          fluid: true,
          bigPlayButton: "init",
          showJumpControls: true,
          playbackRates: [0.5, 1, 1.25, 1.5, 2],
          colors: { accent: "#34c28c", base: "#0d1210", text: "#e7ede9" },
          posterOptions: { transformation: { quality: "auto" } },
          logoOnclickUrl: "",
          logoImageUrl: "",
        });

        playerRef.current = player;

        // Decide source: prefer the signed stream if available, else the review mp4
        if (streamUrl) {
          player.source(streamUrl, { sourceType: "hls" });
        } else if (reviewUrl) {
          player.source(reviewUrl);
        } else {
          player.source(publicId, {
            type: deliveryType,
            transformation: { streaming_profile: "auto" },
          });
        }

        // Load chapters — the player supports a textTracks API via videojs
        try {
          player.videojs.addRemoteTextTrack(
            {
              kind: "chapters",
              src: chaptersUrl,
              srclang: "en",
              label: "Segments",
              default: true,
            },
            false,
          );
        } catch {
          // Chapters are best-effort; the API might return empty VTT
        }

        // Time update for parent components
        if (onTimeUpdate) {
          player.on("timeupdate", () => {
            onTimeUpdate(Math.round((player.currentTime() as number) * 1000));
          });
        }

        player.on("ready", () => setLoading(false));
        player.on("error", () => {
          setError("Could not load video. The signed URL may have expired.");
          setLoading(false);
        });

        // Safety: if ready fired before we attached
        if (player.videojs?.readyState?.() >= 1) {
          setLoading(false);
        }
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to initialize video player");
        setLoading(false);
      }
    // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [cloudName, publicId, deliveryType, streamUrl, reviewUrl, chaptersUrl, videoId]);

    useEffect(() => {
      initPlayer();
      return () => {
        if (playerRef.current) {
          try {
            playerRef.current.dispose();
          } catch {
            // Player may already be disposed
          }
          playerRef.current = null;
        }
      };
      // eslint-disable-next-line react-hooks/exhaustive-deps
    }, []);

    return (
      <div className="relative w-full overflow-hidden rounded-lg bg-[#0b0f0d]">
        {loading && (
          <div className="absolute inset-0 z-10 flex items-center justify-center">
            <Loader2 className="size-6 animate-spin text-white/60" />
          </div>
        )}
        {error ? (
          <div className="flex aspect-video flex-col items-center justify-center gap-2 text-sm text-danger">
            <Film className="size-6" />
            <p>{error}</p>
          </div>
        ) : (
          <video
            id={videoId}
            className="cld-video-player cld-fluid w-full"
            playsInline
          />
        )}
      </div>
    );
  },
);
