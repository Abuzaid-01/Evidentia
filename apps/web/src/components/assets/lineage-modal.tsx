"use client";

import { Copy, ExternalLink, GitFork, Layers, ShieldCheck, Sparkles, X } from "lucide-react";
import { useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { useAssetLineage } from "@/lib/api/hooks";
import { formatBytes } from "@/lib/utils";

interface LineageModalProps {
  assetId: string;
  open: boolean;
  onClose: () => void;
}

export function LineageModal({ assetId, open, onClose }: LineageModalProps) {
  const { data: lineage, isLoading } = useAssetLineage(open ? assetId : "");
  const [copiedId, setCopiedId] = useState<string | null>(null);

  if (!open) return null;

  const copyText = (id: string, text: string) => {
    navigator.clipboard.writeText(text);
    setCopiedId(id);
    setTimeout(() => setCopiedId(null), 2000);
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4 backdrop-blur-sm">
      <div className="flex max-h-[90vh] w-full max-w-4xl flex-col rounded-xl border border-border bg-surface shadow-2xl">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-border px-6 py-4">
          <div className="flex items-center gap-2.5">
            <div className="flex size-9 items-center justify-center rounded-lg bg-accent-soft text-accent">
              <GitFork className="size-5" />
            </div>
            <div>
              <h2 className="text-base font-semibold text-text">Evidence Lineage & Provenance</h2>
              <p className="text-xs text-text-muted">
                Trace original Cloudinary asset through every applied transformation
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="rounded-lg p-1.5 text-text-muted hover:bg-surface-muted hover:text-text transition-colors"
          >
            <X className="size-5" />
          </button>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto p-6 space-y-6">
          {isLoading && (
            <div className="flex items-center justify-center py-12 text-sm text-text-muted">
              Loading lineage graph...
            </div>
          )}

          {lineage && (
            <>
              {/* Root Asset Card */}
              <div className="rounded-lg border border-accent/30 bg-accent-soft/30 p-4">
                <div className="flex items-center justify-between mb-3">
                  <div className="flex items-center gap-2">
                    <span className="text-xs font-semibold uppercase tracking-wider text-accent">
                      Original Root Evidence
                    </span>
                    <Badge tone="outline" className="border-accent/40 text-accent text-[10px]">
                      Authentic
                    </Badge>
                  </div>
                  <span className="font-mono text-xs text-text-muted">
                    {lineage.public_id}
                  </span>
                </div>
                <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-xs">
                  <div>
                    <span className="text-text-subtle block">Filename</span>
                    <span className="font-medium text-text truncate block">{lineage.original_filename ?? "raw"}</span>
                  </div>
                  <div>
                    <span className="text-text-subtle block">Size</span>
                    <span className="font-medium text-text">{lineage.bytes ? formatBytes(lineage.bytes) : "—"}</span>
                  </div>
                  <div>
                    <span className="text-text-subtle block">Format</span>
                    <span className="font-medium uppercase text-text">{lineage.format ?? "—"}</span>
                  </div>
                  <div>
                    <span className="text-text-subtle block">Capture Provenance</span>
                    <span className="font-medium text-text capitalize">{lineage.capture_time_source}</span>
                  </div>
                </div>
              </div>

              {/* Transformation Lineage Tree */}
              <div>
                <div className="flex items-center gap-2 mb-3">
                  <Layers className="size-4 text-accent" />
                  <h3 className="text-xs font-semibold uppercase tracking-wider text-text-muted">
                    Derived Renditions ({lineage.derivatives.length})
                  </h3>
                </div>

                {lineage.derivatives.length === 0 ? (
                  <p className="text-xs text-text-muted py-2">No derivatives registered yet.</p>
                ) : (
                  <div className="space-y-3">
                    {lineage.derivatives.map((deriv, idx) => (
                      <Card key={deriv.id} className="p-4 border-border bg-surface-muted/40">
                        <div className="flex flex-wrap items-center justify-between gap-2 mb-2">
                          <div className="flex items-center gap-2">
                            <span className="text-xs font-mono font-medium text-text">
                              #{idx + 1} {deriv.purpose}
                            </span>
                            {deriv.named_transformation && (
                              <Badge tone="neutral" className="text-[10px]">
                                {deriv.named_transformation}
                              </Badge>
                            )}
                            {deriv.generative ? (
                              <Badge tone="outline" className="border-amber-500/40 bg-amber-500/10 text-amber-400 text-[10px] gap-1">
                                <Sparkles className="size-3" />
                                Illustrative / Generative
                              </Badge>
                            ) : (
                              <Badge tone="outline" className="border-emerald-500/40 bg-emerald-500/10 text-emerald-400 text-[10px] gap-1">
                                <ShieldCheck className="size-3" />
                                Audit Evidence
                              </Badge>
                            )}
                          </div>
                          <div className="flex items-center gap-1.5">
                            <Button
                              size="sm"
                              variant="ghost"
                              className="h-7 px-2 text-xs"
                              onClick={() => copyText(deriv.id, deriv.transformation)}
                            >
                              <Copy className="size-3 mr-1" />
                              {copiedId === deriv.id ? "Copied" : "Copy Transform"}
                            </Button>
                            <a
                              href={deriv.url}
                              target="_blank"
                              rel="noreferrer"
                              className="inline-flex h-7 items-center gap-1 rounded-md px-2 text-xs text-accent hover:bg-accent-soft transition-colors"
                            >
                              <ExternalLink className="size-3" />
                              View
                            </a>
                          </div>
                        </div>

                        <div className="rounded bg-black/40 p-2 font-mono text-[11px] text-text-muted break-all border border-border/50">
                          {deriv.transformation}
                        </div>
                      </Card>
                    ))}
                  </div>
                )}
              </div>

              {/* Associations (Claims, Before/After, Campaigns) */}
              {(lineage.claims.length > 0 || lineage.campaigns.length > 0 || lineage.pairs.length > 0) && (
                <div className="grid grid-cols-1 md:grid-cols-3 gap-4 pt-2 border-t border-border">
                  {lineage.claims.length > 0 && (
                    <div>
                      <h4 className="text-xs font-semibold text-text-muted uppercase tracking-wider mb-2">
                        Cited in Claims ({lineage.claims.length})
                      </h4>
                      <div className="space-y-1.5">
                        {lineage.claims.map((c) => (
                          <div key={c.claim_id} className="rounded border border-border bg-surface p-2 text-xs">
                            <span className="font-medium text-text line-clamp-2">{c.statement}</span>
                            <span className="text-[10px] text-accent uppercase block mt-1">{c.status}</span>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}

                  {lineage.campaigns.length > 0 && (
                    <div>
                      <h4 className="text-xs font-semibold text-text-muted uppercase tracking-wider mb-2">
                        Campaign Studio ({lineage.campaigns.length})
                      </h4>
                      <div className="space-y-1.5">
                        {lineage.campaigns.map((camp) => (
                          <div key={camp.campaign_id} className="rounded border border-border bg-surface p-2 text-xs">
                            <span className="font-medium text-text block">{camp.title}</span>
                            <span className="text-[10px] text-text-muted line-clamp-1">{camp.headline}</span>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}

                  {lineage.pairs.length > 0 && (
                    <div>
                      <h4 className="text-xs font-semibold text-text-muted uppercase tracking-wider mb-2">
                        Before / After Pairs ({lineage.pairs.length})
                      </h4>
                      <div className="space-y-1.5">
                        {lineage.pairs.map((p) => (
                          <div key={p.id} className="rounded border border-border bg-surface p-2 text-xs">
                            <span className="font-medium text-text capitalize">Role: {p.role}</span>
                            <span className="text-[10px] text-text-muted block mt-0.5">{p.change_summary ?? p.status}</span>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              )}
            </>
          )}
        </div>

        {/* Footer */}
        <div className="flex justify-end border-t border-border px-6 py-3">
          <Button variant="secondary" onClick={onClose}>
            Close
          </Button>
        </div>
      </div>
    </div>
  );
}
