"use client";

import {
  AlertTriangle,
  Check,
  Copy,
  ExternalLink,
  GitFork,
  Layers,
  Share2,
  ShieldCheck,
  Sparkles,
} from "lucide-react";
import { useState } from "react";

import { LineageModal } from "@/components/assets/lineage-modal";
import { ShareDialog } from "@/components/share/share-dialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input, Select } from "@/components/ui/form";
import { useCampaigns, useCreateCampaign } from "@/lib/api/hooks";
import type { AssetSummary, Campaign } from "@/lib/api/types";

interface CampaignStudioProps {
  projectId: string;
  assets: AssetSummary[];
}

const FORMAT_LABELS: Record<string, { name: string; desc: string; ratio: string }> = {
  "1:1": { name: "1:1 Square", desc: "Instagram Feed, LinkedIn", ratio: "aspect-square" },
  "4:5": { name: "4:5 Portrait", desc: "Instagram Portrait, Facebook", ratio: "aspect-[4/5]" },
  "9:16": { name: "9:16 Story/Reel", desc: "Instagram Stories, TikTok, Shorts", ratio: "aspect-[9/16]" },
  "16:9": { name: "16:9 Landscape", desc: "Web Banners, YouTube, X", ratio: "aspect-video" },
};

export function CampaignStudio({ projectId, assets }: CampaignStudioProps) {
  const { data: campaigns } = useCampaigns(projectId);
  const createMutation = useCreateCampaign(projectId);

  const [selectedAssetId, setSelectedAssetId] = useState<string>(assets[0]?.id ?? "");
  const [title, setTitle] = useState("Community Impact Highlight");
  const [headline, setHeadline] = useState("Clean Drinking Water Restored");
  const [statText, setStatText] = useState("2,400 People Served");
  const [brandTag, setBrandTag] = useState("EVIDENTIA VERIFIED");
  const [selectedFormats, setSelectedFormats] = useState<string[]>(["1:1", "4:5", "9:16", "16:9"]);
  const [generativeFill, setGenerativeFill] = useState(false);
  const [generativeRestore, setGenerativeRestore] = useState(false);
  const [selectedCampaign, setSelectedCampaign] = useState<Campaign | null>(null);

  // Modals state
  const [lineageAssetId, setLineageAssetId] = useState<string | null>(null);
  const [shareTarget, setShareTarget] = useState<{ id: string; type: "campaign" | "evidence" } | null>(null);
  const [copiedUrl, setCopiedUrl] = useState<string | null>(null);

  const toggleFormat = (fmt: string) => {
    setSelectedFormats((prev) =>
      prev.includes(fmt) ? prev.filter((f) => f !== fmt) : [...prev, fmt]
    );
  };

  const handleGenerate = async () => {
    if (!selectedAssetId || selectedFormats.length === 0) return;
    try {
      const res = await createMutation.mutateAsync({
        title,
        headline,
        stat_text: statText.trim() || null,
        brand_tag: brandTag.trim() || null,
        asset_id: selectedAssetId,
        formats: selectedFormats,
        generative_fill: generativeFill,
        generative_restore: generativeRestore,
        redact: true, // MANDATORY
      });
      setSelectedCampaign(res);
    } catch (e) {
      console.error(e);
    }
  };

  const copyUrl = (url: string) => {
    navigator.clipboard.writeText(url);
    setCopiedUrl(url);
    setTimeout(() => setCopiedUrl(null), 2000);
  };

  const activeCampaign = selectedCampaign || campaigns?.[0] || null;

  return (
    <div className="space-y-8">
      {/* Top Banner */}
      <div className="rounded-xl border border-border bg-gradient-to-r from-surface to-surface-muted p-6">
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
          <div>
            <div className="flex items-center gap-2 mb-1.5">
              <Sparkles className="size-5 text-accent" />
              <h2 className="text-lg font-semibold text-text">Campaign Studio & Social Delivery</h2>
              <Badge tone="outline" className="border-emerald-500/40 text-emerald-400 text-xs gap-1">
                <ShieldCheck className="size-3" />
                Mandatory Face Redaction
              </Badge>
            </div>
            <p className="text-sm text-text-muted max-w-2xl">
              Turn verified field evidence into publication-ready social media cards (1:1, 4:5, 9:16, 16:9).
              Every output automatically applies face pixelation, records full transformation lineage, and flags generative edits as illustrative.
            </p>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-12 gap-8">
        {/* Creator Configuration Panel */}
        <div className="lg:col-span-4 space-y-6">
          <Card className="p-5 border-border bg-surface space-y-4">
            <h3 className="text-sm font-semibold uppercase tracking-wider text-text-muted flex items-center gap-2">
              <Layers className="size-4 text-accent" />
              Configure Asset
            </h3>

            {/* Evidence Picker */}
            <div>
              <label className="block text-xs font-medium text-text-muted mb-1.5">Select Approved Evidence</label>
              {assets.length === 0 ? (
                <p className="text-xs text-text-subtle">No ready assets found in this project.</p>
              ) : (
                <Select
                  value={selectedAssetId}
                  onChange={(e) => setSelectedAssetId(e.target.value)}
                  className="w-full text-xs"
                >
                  {assets.map((a) => (
                    <option key={a.id} value={a.id}>
                      {a.original_filename ?? a.id.slice(0, 8)} ({a.format?.toUpperCase() ?? "IMG"})
                    </option>
                  ))}
                </Select>
              )}
            </div>

            {/* Campaign Title & Headline */}
            <div>
              <label className="block text-xs font-medium text-text-muted mb-1">Campaign Title</label>
              <Input
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                placeholder="Campaign / Post Name"
                className="text-xs"
              />
            </div>

            <div>
              <label className="block text-xs font-medium text-text-muted mb-1">Headline Text Overlay</label>
              <Input
                value={headline}
                onChange={(e) => setHeadline(e.target.value)}
                placeholder="e.g. Clean Drinking Water Restored"
                className="text-xs"
              />
            </div>

            {/* Stat & Brand Tag */}
            <div>
              <label className="block text-xs font-medium text-text-muted mb-1">Stat / Verified Metric Highlight</label>
              <Input
                value={statText}
                onChange={(e) => setStatText(e.target.value)}
                placeholder="e.g. 2,400 People Served"
                className="text-xs"
              />
            </div>

            <div>
              <label className="block text-xs font-medium text-text-muted mb-1">Brand Frame / Label</label>
              <Input
                value={brandTag}
                onChange={(e) => setBrandTag(e.target.value)}
                placeholder="e.g. EVIDENTIA VERIFIED"
                className="text-xs"
              />
            </div>

            {/* Aspect Ratios Selection */}
            <div>
              <label className="block text-xs font-medium text-text-muted mb-2">Social Formats to Generate</label>
              <div className="grid grid-cols-2 gap-2">
                {Object.entries(FORMAT_LABELS).map(([fmt, info]) => {
                  const active = selectedFormats.includes(fmt);
                  return (
                    <button
                      key={fmt}
                      type="button"
                      onClick={() => toggleFormat(fmt)}
                      className={`flex flex-col items-start p-2.5 rounded-lg border text-left transition-all ${
                        active
                          ? "border-accent bg-accent-soft/40 text-text"
                          : "border-border bg-surface-muted/30 text-text-muted hover:border-border-strong"
                      }`}
                    >
                      <span className="text-xs font-semibold">{info.name}</span>
                      <span className="text-[10px] text-text-subtle truncate w-full">{info.desc}</span>
                    </button>
                  );
                })}
              </div>
            </div>

            {/* Generative Effects Toggles */}
            <div className="pt-2 border-t border-border space-y-3">
              <div className="flex items-center justify-between">
                <div>
                  <span className="text-xs font-medium text-text block">Generative Fill (b_gen_fill)</span>
                  <span className="text-[10px] text-text-subtle">Expands background canvas to fit aspect ratio</span>
                </div>
                <input
                  type="checkbox"
                  checked={generativeFill}
                  onChange={(e) => setGenerativeFill(e.target.checked)}
                  className="rounded border-border accent-accent size-4"
                />
              </div>

              <div className="flex items-center justify-between">
                <div>
                  <span className="text-xs font-medium text-text block">Generative Restore (e_gen_restore)</span>
                  <span className="text-[10px] text-text-subtle">Enhances details & reduces compression artifacts</span>
                </div>
                <input
                  type="checkbox"
                  checked={generativeRestore}
                  onChange={(e) => setGenerativeRestore(e.target.checked)}
                  className="rounded border-border accent-accent size-4"
                />
              </div>

              {(generativeFill || generativeRestore) && (
                <div className="flex items-start gap-2 rounded-lg border border-amber-500/30 bg-amber-500/10 p-2.5 text-[11px] text-amber-300">
                  <AlertTriangle className="size-4 shrink-0 mt-0.5" />
                  <span>
                    Generative edits are strictly labelled <strong>Illustrative</strong> and watermarked. They can never be linked to claims as audit evidence.
                  </span>
                </div>
              )}
            </div>

            {/* Submit Button */}
            <Button
              className="w-full text-xs"
              onClick={handleGenerate}
              disabled={createMutation.isPending || !selectedAssetId || selectedFormats.length === 0}
            >
              {createMutation.isPending ? "Generating via Cloudinary..." : "Generate Campaign Renditions"}
            </Button>
          </Card>

          {/* Past Campaigns List */}
          {campaigns && campaigns.length > 0 && (
            <Card className="p-4 border-border bg-surface space-y-2">
              <h4 className="text-xs font-semibold uppercase tracking-wider text-text-muted mb-2">
                Recent Campaigns ({campaigns.length})
              </h4>
              <div className="space-y-1.5 max-h-48 overflow-y-auto">
                {campaigns.map((c) => (
                  <button
                    key={c.id}
                    onClick={() => setSelectedCampaign(c)}
                    className={`w-full text-left p-2 rounded-md border text-xs transition-colors flex items-center justify-between ${
                      activeCampaign?.id === c.id
                        ? "border-accent bg-accent-soft/30 text-text font-medium"
                        : "border-transparent hover:bg-surface-muted text-text-muted"
                    }`}
                  >
                    <span className="truncate">{c.title}</span>
                    <Badge tone="neutral" className="text-[10px]">
                      {Object.keys(c.renditions).length} cards
                    </Badge>
                  </button>
                ))}
              </div>
            </Card>
          )}
        </div>

        {/* Live Preview Display Gallery */}
        <div className="lg:col-span-8 space-y-6">
          {activeCampaign ? (
            <div>
              <div className="flex items-center justify-between mb-4">
                <div>
                  <h3 className="text-base font-semibold text-text">{activeCampaign.title}</h3>
                  <p className="text-xs text-text-muted">
                    Headline: &quot;{activeCampaign.headline}&quot; • Created {new Date(activeCampaign.created_at).toLocaleDateString()}
                  </p>
                </div>
                <div className="flex items-center gap-2">
                  <Button
                    size="sm"
                    variant="secondary"
                    className="text-xs gap-1.5"
                    onClick={() => setLineageAssetId(activeCampaign.asset_id)}
                  >
                    <GitFork className="size-3.5" />
                    Inspect Lineage
                  </Button>
                  <Button
                    size="sm"
                    variant="secondary"
                    className="text-xs gap-1.5"
                    onClick={() => setShareTarget({ id: activeCampaign.id, type: "campaign" })}
                  >
                    <Share2 className="size-3.5" />
                    Share Publicly
                  </Button>
                </div>
              </div>

              {/* Grid of Generated Formats */}
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                {Object.entries(activeCampaign.renditions).map(([fmt, rend]) => {
                  const info = FORMAT_LABELS[fmt] ?? { name: fmt, desc: "", ratio: "aspect-square" };
                  return (
                    <Card key={fmt} className="overflow-hidden border-border bg-surface flex flex-col">
                      {/* Image Header with Ratio */}
                      <div className="p-3 border-b border-border flex items-center justify-between bg-surface-muted/30">
                        <div className="flex items-center gap-1.5">
                          <span className="text-xs font-semibold text-text">{info.name}</span>
                          <span className="text-[10px] text-text-subtle">({fmt})</span>
                        </div>
                        <Badge tone="outline" className="text-[10px] border-emerald-500/40 text-emerald-400">
                          Redacted
                        </Badge>
                      </div>

                      {/* Image Card Container */}
                      <div className="relative w-full bg-black/90 flex items-center justify-center p-2 min-h-[300px]">
                        {/* eslint-disable-next-line @next/next/no-img-element */}
                        <img
                          src={rend.url}
                          alt={`${activeCampaign.title} ${fmt}`}
                          className="max-h-[360px] w-auto object-contain rounded shadow"
                          loading="lazy"
                        />
                      </div>

                      {/* Card Footer Actions */}
                      <div className="p-3 border-t border-border flex items-center justify-between bg-surface">
                        <div className="text-[11px] font-mono text-text-muted truncate max-w-[140px]">
                          {rend.purpose}
                        </div>
                        <div className="flex items-center gap-1.5">
                          <Button
                            size="sm"
                            variant="ghost"
                            className="h-7 px-2 text-xs"
                            onClick={() => copyUrl(rend.url)}
                          >
                            {copiedUrl === rend.url ? <Check className="size-3 text-emerald-400 mr-1" /> : <Copy className="size-3 mr-1" />}
                            {copiedUrl === rend.url ? "Copied" : "Copy URL"}
                          </Button>
                          <a
                            href={rend.url}
                            target="_blank"
                            rel="noreferrer"
                            className="inline-flex h-7 items-center gap-1 rounded-md bg-accent-soft px-2.5 text-xs text-accent hover:bg-accent-soft/80 transition-colors"
                          >
                            <ExternalLink className="size-3" />
                            Open
                          </a>
                        </div>
                      </div>
                    </Card>
                  );
                })}
              </div>
            </div>
          ) : (
            <Card className="flex flex-col items-center justify-center py-20 text-center border-dashed border-border bg-surface-muted/20">
              <Sparkles className="size-10 text-accent/50 mb-3" />
              <h4 className="text-sm font-semibold text-text mb-1">No Campaign Assets Generated Yet</h4>
              <p className="text-xs text-text-muted max-w-sm">
                Select an approved evidence asset on the left and click &quot;Generate Campaign Renditions&quot; to build multi-format social cards with automatic privacy redaction.
              </p>
            </Card>
          )}
        </div>
      </div>

      {/* Lineage Modal */}
      {lineageAssetId && (
        <LineageModal
          assetId={lineageAssetId}
          open={!!lineageAssetId}
          onClose={() => setLineageAssetId(null)}
        />
      )}

      {/* Share Dialog */}
      {shareTarget && (
        <ShareDialog
          projectId={projectId}
          targetType={shareTarget.type}
          targetId={shareTarget.id}
          open={!!shareTarget}
          onClose={() => setShareTarget(null)}
        />
      )}
    </div>
  );
}
