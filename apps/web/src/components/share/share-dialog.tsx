"use client";

import { Check, Copy, ExternalLink, Globe, ShieldCheck, X } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Input, Select } from "@/components/ui/form";
import { useCreateShareLink } from "@/lib/api/hooks";

interface ShareDialogProps {
  projectId: string;
  targetType: "report" | "evidence" | "campaign";
  targetId: string;
  defaultTitle?: string;
  open: boolean;
  onClose: () => void;
}

export function ShareDialog({
  projectId,
  targetType,
  targetId,
  defaultTitle = "External Evidence Share",
  open,
  onClose,
}: ShareDialogProps) {
  const [title, setTitle] = useState(defaultTitle);
  const [days, setDays] = useState("14");
  const [copied, setCopied] = useState(false);
  const [createdUrl, setCreatedUrl] = useState<string | null>(null);

  const createMutation = useCreateShareLink(projectId);

  if (!open) return null;

  const handleCreate = async () => {
    try {
      const res = await createMutation.mutateAsync({
        title,
        target_type: targetType,
        target_id: targetId,
        expires_in_days: parseInt(days, 10),
      });
      const fullUrl = `${window.location.origin}/share/${res.token}`;
      setCreatedUrl(fullUrl);
    } catch (e) {
      console.error(e);
    }
  };

  const copyUrl = () => {
    if (!createdUrl) return;
    navigator.clipboard.writeText(createdUrl);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4 backdrop-blur-sm">
      <div className="w-full max-w-md rounded-xl border border-border bg-surface p-6 shadow-2xl">
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-2">
            <div className="flex size-8 items-center justify-center rounded-lg bg-accent-soft text-accent">
              <Globe className="size-4" />
            </div>
            <h3 className="text-base font-semibold text-text">Create Public Share Link</h3>
          </div>
          <button onClick={onClose} className="rounded-lg p-1 text-text-muted hover:text-text">
            <X className="size-5" />
          </button>
        </div>

        {/* Security Alert */}
        <div className="mb-4 flex items-start gap-2.5 rounded-lg border border-accent/30 bg-accent-soft/20 p-3 text-xs text-text-muted">
          <ShieldCheck className="size-4 shrink-0 text-accent mt-0.5" />
          <span>
            External shares guarantee privacy: all human faces are automatically pixelated on the CDN edge, and precise GPS coordinates are stripped.
          </span>
        </div>

        {!createdUrl ? (
          <div className="space-y-4">
            <div>
              <label className="block text-xs font-medium text-text-muted mb-1">Link Title</label>
              <Input
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                placeholder="e.g. Rampura Site Audit"
              />
            </div>

            <div>
              <label className="block text-xs font-medium text-text-muted mb-1">Expires After</label>
              <Select value={days} onChange={(e) => setDays(e.target.value)}>
                <option value="7">7 Days</option>
                <option value="14">14 Days</option>
                <option value="30">30 Days</option>
                <option value="90">90 Days</option>
              </Select>
            </div>

            <div className="flex justify-end gap-2 pt-2">
              <Button variant="secondary" onClick={onClose}>
                Cancel
              </Button>
              <Button onClick={handleCreate} disabled={createMutation.isPending || !title.trim()}>
                {createMutation.isPending ? "Generating..." : "Generate Share Link"}
              </Button>
            </div>
          </div>
        ) : (
          <div className="space-y-4">
            <div className="rounded-lg border border-border bg-surface-muted p-3">
              <span className="block text-[11px] font-medium uppercase tracking-wider text-text-subtle mb-1">
                Shareable Link (Read-Only)
              </span>
              <div className="flex items-center gap-2">
                <input
                  type="text"
                  readOnly
                  value={createdUrl}
                  className="w-full bg-transparent font-mono text-xs text-text outline-none"
                />
                <Button size="sm" variant="secondary" onClick={copyUrl} className="h-7 px-2 shrink-0">
                  {copied ? <Check className="size-3 text-emerald-400" /> : <Copy className="size-3" />}
                  <span className="ml-1 text-xs">{copied ? "Copied" : "Copy"}</span>
                </Button>
              </div>
            </div>

            <div className="flex justify-between items-center pt-2">
              <a
                href={createdUrl}
                target="_blank"
                rel="noreferrer"
                className="inline-flex items-center gap-1.5 text-xs text-accent hover:underline"
              >
                <ExternalLink className="size-3.5" />
                Test Open in New Tab
              </a>
              <Button variant="secondary" onClick={onClose}>
                Done
              </Button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
