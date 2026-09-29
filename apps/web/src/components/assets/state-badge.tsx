import { AlertTriangle, CheckCircle2, Clock, Loader2, XCircle } from "lucide-react";

import { Badge, type BadgeTone } from "@/components/ui/badge";
import type { AssetState } from "@/lib/api/types";

const META: Record<AssetState, { label: string; tone: BadgeTone; icon: "spin" | "ok" | "warn" | "fail" | "wait" }> = {
  awaiting_upload: { label: "Awaiting upload", tone: "neutral", icon: "wait" },
  uploaded: { label: "Uploaded", tone: "info", icon: "spin" },
  registered: { label: "Registering", tone: "info", icon: "spin" },
  metadata_ready: { label: "Reading metadata", tone: "info", icon: "spin" },
  dedup_checked: { label: "Checking duplicates", tone: "info", icon: "spin" },
  analyzing: { label: "AI analysing", tone: "info", icon: "spin" },
  indexed: { label: "Indexing", tone: "info", icon: "spin" },
  review_required: { label: "Needs review", tone: "warning", icon: "warn" },
  ready: { label: "Ready", tone: "accent", icon: "ok" },
  expired: { label: "Expired", tone: "neutral", icon: "fail" },
  failed_retryable: { label: "Retrying", tone: "warning", icon: "spin" },
  failed_permanent: { label: "Failed", tone: "danger", icon: "fail" },
};

export const PROCESSING_STATES: AssetState[] = [
  "uploaded",
  "registered",
  "metadata_ready",
  "dedup_checked",
  "analyzing",
  "indexed",
  "failed_retryable",
];

export function StateBadge({ state }: { state: AssetState }) {
  const meta = META[state];
  const Icon = { spin: Loader2, ok: CheckCircle2, warn: AlertTriangle, fail: XCircle, wait: Clock }[meta.icon];
  return (
    <Badge tone={meta.tone}>
      <Icon className={meta.icon === "spin" ? "animate-spin" : undefined} />
      {meta.label}
    </Badge>
  );
}

export function stateLabel(state: AssetState): string {
  return META[state].label;
}
