"use client";

import {
  AlertCircle,
  Calendar,
  GitFork,
  MapPin,
  ShieldCheck,
} from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";

import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { useSharedContent } from "@/lib/api/hooks";
import { formatDate } from "@/lib/utils";

type RenditionEntry = {
  url: string;
  width?: number;
  height?: number;
};

type ClaimEntry = {
  id?: string;
  statement: string;
  status?: string;
};

type SharedEvidenceData = {
  media_url: string;
  caption?: string | null;
  capture_time?: string | null;
  verified_activities?: string[];
};

type SharedCampaignData = {
  title: string;
  headline: string;
  stat_text?: string | null;
  generative: boolean;
  renditions?: Record<string, RenditionEntry>;
};

type SharedReportData = {
  title: string;
  published_at: string;
  version: number;
  manifest?: {
    report?: { summary?: string };
    claims?: ClaimEntry[];
  };
};

export default function PublicSharePage() {
  const { token } = useParams<{ token: string }>();
  const { data: shared, isLoading, error } = useSharedContent(token);

  if (isLoading) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-background px-4">
        <div className="text-center space-y-2">
          <div className="size-8 animate-spin rounded-full border-2 border-accent border-t-transparent mx-auto" />
          <p className="text-sm text-text-muted">Resolving verified evidence share...</p>
        </div>
      </div>
    );
  }

  if (error || !shared) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-background px-4">
        <Card className="max-w-md p-6 text-center border-border bg-surface">
          <AlertCircle className="size-10 text-danger mx-auto mb-3" />
          <h2 className="text-base font-semibold text-text mb-1">Share Link Unavailable</h2>
          <p className="text-xs text-text-muted mb-4">
            This share link does not exist, has expired, or was revoked by the program administrators.
          </p>
          <Link
            href="/"
            className="inline-flex h-8 items-center rounded-lg bg-surface-muted px-4 text-xs font-medium text-text hover:bg-border transition-colors"
          >
            Return to Evidentia
          </Link>
        </Card>
      </div>
    );
  }

  const { data, target_type, lineage } = shared;
  const evidenceData = data as unknown as SharedEvidenceData;
  const campaignData = data as unknown as SharedCampaignData;
  const reportData = data as unknown as SharedReportData;

  return (
    <div className="min-h-screen bg-background text-text">
      {/* Top Navbar */}
      <header className="sticky top-0 z-30 border-b border-border bg-surface/80 backdrop-blur px-6 py-3.5 flex items-center justify-between">
        <div className="flex items-center gap-2.5">
          <div className="flex size-7 items-center justify-center rounded-md bg-accent text-white font-bold text-xs">
            E
          </div>
          <div>
            <span className="font-semibold text-sm tracking-tight text-text">Evidentia</span>
            <span className="text-[10px] text-text-subtle ml-2 uppercase tracking-wider">Public Evidence Viewer</span>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <Badge tone="outline" className="border-emerald-500/40 bg-emerald-500/10 text-emerald-400 text-xs gap-1 py-1">
            <ShieldCheck className="size-3.5" />
            Verified & Privacy Redacted
          </Badge>
        </div>
      </header>

      {/* Main Content Container */}
      <main className="mx-auto max-w-5xl px-4 py-8 space-y-8">
        {/* Banner */}
        <div className="space-y-2 border-b border-border pb-6">
          <div className="flex items-center gap-2 text-xs text-text-muted">
            <span>{shared.project_name}</span>
            <span>•</span>
            <span className="capitalize">{target_type} Share</span>
          </div>
          <h1 className="text-2xl font-bold tracking-tight text-text">{shared.title}</h1>
          <p className="text-xs text-text-subtle">
            Public link active until {new Date(shared.expires_at).toLocaleDateString()} · Access strictly read-only
          </p>
        </div>

        {/* Evidence View */}
        {target_type === "evidence" && (
          <div className="space-y-6">
            <div className="overflow-hidden rounded-xl border border-border bg-black/90 shadow-xl">
              <div className="relative aspect-video w-full flex items-center justify-center">
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img
                  src={evidenceData.media_url}
                  alt={evidenceData.caption ?? "Evidence"}
                  className="max-h-[600px] w-auto object-contain"
                />
                <div className="absolute bottom-3 left-3 rounded-md bg-black/70 px-2.5 py-1 text-[11px] font-medium text-emerald-400 border border-emerald-500/30 flex items-center gap-1.5 backdrop-blur">
                  <ShieldCheck className="size-3.5" />
                  Faces pixelated on CDN edge (e_pixelate_faces)
                </div>
              </div>
            </div>

            {/* Details Card */}
            <Card className="p-6 border-border bg-surface space-y-4">
              <h2 className="text-sm font-semibold uppercase tracking-wider text-text-muted">
                Evidence Information
              </h2>
              {evidenceData.caption && (
                <p className="text-sm text-text font-medium leading-relaxed">{evidenceData.caption}</p>
              )}

              <div className="grid grid-cols-2 sm:grid-cols-3 gap-4 pt-2 border-t border-border text-xs">
                <div>
                  <span className="text-text-subtle block mb-0.5">Capture Date</span>
                  <span className="font-medium text-text flex items-center gap-1">
                    <Calendar className="size-3 text-accent" />
                    {evidenceData.capture_time ? formatDate(evidenceData.capture_time) : "Undated"}
                  </span>
                </div>
                <div>
                  <span className="text-text-subtle block mb-0.5">Privacy Protection</span>
                  <span className="font-medium text-emerald-400 flex items-center gap-1">
                    <ShieldCheck className="size-3" />
                    Faces Redacted
                  </span>
                </div>
                <div>
                  <span className="text-text-subtle block mb-0.5">Location Privacy</span>
                  <span className="font-medium text-text flex items-center gap-1">
                    <MapPin className="size-3 text-text-muted" />
                    GPS Coarsened
                  </span>
                </div>
              </div>

              {evidenceData.verified_activities && evidenceData.verified_activities.length > 0 && (
                <div className="pt-2">
                  <span className="text-xs text-text-subtle block mb-1.5">Verified Field Activities</span>
                  <div className="flex flex-wrap gap-1.5">
                    {evidenceData.verified_activities.map((act: string) => (
                      <Badge key={act} tone="neutral" className="text-xs capitalize">
                        {act.replace(/_/g, " ")}
                      </Badge>
                    ))}
                  </div>
                </div>
              )}
            </Card>

            {/* Lineage */}
            {lineage && lineage.length > 0 && (
              <Card className="p-6 border-border bg-surface space-y-4">
                <div className="flex items-center gap-2">
                  <GitFork className="size-4 text-accent" />
                  <h2 className="text-sm font-semibold uppercase tracking-wider text-text-muted">
                    Transformation Lineage ({lineage.length})
                  </h2>
                </div>
                <p className="text-xs text-text-muted">
                  Every transformation applied to this asset is tracked cryptographically back to the original Cloudinary upload.
                </p>
                <div className="space-y-2.5">
                  {lineage.map((item, idx) => (
                    <div key={item.id} className="rounded-lg border border-border bg-surface-muted/40 p-3 text-xs space-y-1">
                      <div className="flex items-center justify-between">
                        <span className="font-mono font-medium text-text">#{idx + 1} {item.purpose}</span>
                        {item.generative && (
                          <Badge tone="outline" className="border-amber-500/40 text-amber-400 text-[10px]">
                            Generative
                          </Badge>
                        )}
                      </div>
                      <div className="rounded bg-black/40 p-1.5 font-mono text-[11px] text-text-muted break-all border border-border/40">
                        {item.transformation}
                      </div>
                    </div>
                  ))}
                </div>
              </Card>
            )}
          </div>
        )}

        {/* Campaign View */}
        {target_type === "campaign" && (
          <div className="space-y-6">
            <Card className="p-6 border-border bg-surface space-y-3">
              <div className="flex items-center justify-between">
                <h2 className="text-base font-bold text-text">{campaignData.title}</h2>
                {campaignData.generative && (
                  <Badge tone="outline" className="border-amber-500/40 text-amber-400 text-xs">
                    Illustrative Presentation
                  </Badge>
                )}
              </div>
              <p className="text-sm text-text font-medium">&quot;{campaignData.headline}&quot;</p>
              {campaignData.stat_text && (
                <div className="inline-block rounded-md bg-emerald-500/10 border border-emerald-500/30 px-3 py-1 text-xs font-semibold text-emerald-400">
                  {campaignData.stat_text}
                </div>
              )}
            </Card>

            {campaignData.renditions && (
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                {Object.entries(campaignData.renditions).map(([fmt, rend]) => (
                  <Card key={fmt} className="overflow-hidden border-border bg-surface">
                    <div className="p-3 border-b border-border flex items-center justify-between bg-surface-muted/30">
                      <span className="text-xs font-semibold text-text">{fmt} Format</span>
                      <Badge tone="outline" className="text-[10px] border-emerald-500/40 text-emerald-400">
                        Redacted
                      </Badge>
                    </div>
                    <div className="relative w-full bg-black/90 p-2 flex items-center justify-center min-h-[260px]">
                      {/* eslint-disable-next-line @next/next/no-img-element */}
                      <img
                        src={rend.url}
                        alt={`${campaignData.title} ${fmt}`}
                        className="max-h-[340px] w-auto object-contain rounded"
                      />
                    </div>
                  </Card>
                ))}
              </div>
            )}
          </div>
        )}

        {/* Report View */}
        {target_type === "report" && (
          <Card className="p-6 border-border bg-surface space-y-6">
            <div className="border-b border-border pb-4">
              <h2 className="text-xl font-bold text-text">{reportData.title}</h2>
              <p className="text-xs text-text-muted mt-1">
                Published {formatDate(reportData.published_at)} · Version {reportData.version}
              </p>
            </div>

            {reportData.manifest && (
              <div className="space-y-4 text-xs">
                <div>
                  <h3 className="font-semibold uppercase tracking-wider text-text-subtle mb-2">
                    Executive Summary
                  </h3>
                  <p className="text-text leading-relaxed">
                    {reportData.manifest.report?.summary ?? "Report summary and verified impact findings."}
                  </p>
                </div>

                {reportData.manifest.claims && reportData.manifest.claims.length > 0 && (
                  <div>
                    <h3 className="font-semibold uppercase tracking-wider text-text-subtle mb-2">
                      Verified Claims ({reportData.manifest.claims.length})
                    </h3>
                    <div className="space-y-2">
                      {reportData.manifest.claims.map((c, i) => (
                        <div key={i} className="rounded-lg border border-border bg-surface-muted/30 p-3">
                          <p className="font-medium text-text">{c.statement}</p>
                          <span className="text-[10px] text-accent uppercase block mt-1">Status: Approved</span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            )}
          </Card>
        )}
      </main>

      {/* Footer */}
      <footer className="border-t border-border mt-16 py-6 text-center text-xs text-text-subtle">
        Powered by Evidentia on Cloudinary • Traceable field evidence architecture
      </footer>
    </div>
  );
}
