import { Badge, type BadgeTone } from "@/components/ui/badge";
import type { PairStatus, PairSummary } from "@/lib/api/types";

const STATUS: Record<PairStatus, { tone: BadgeTone; label: string }> = {
  candidate: { tone: "neutral", label: "Queued" },
  analyzing: { tone: "info", label: "Analysing" },
  analyzed: { tone: "warning", label: "Needs review" },
  failed: { tone: "danger", label: "Failed" },
  confirmed: { tone: "accent", label: "Confirmed" },
  rejected: { tone: "outline", label: "Rejected" },
};

export function PairStatusBadge({ status }: { status: PairStatus }) {
  const s = STATUS[status];
  return <Badge tone={s.tone}>{s.label}</Badge>;
}

export function GradeBadge({ grade }: { grade: PairSummary["alignment_grade"] }) {
  if (!grade) return null;
  const tone: BadgeTone = grade === "strong" ? "accent" : grade === "partial" ? "info" : "danger";
  return <Badge tone={tone}>{grade === "none" ? "not aligned" : `${grade} alignment`}</Badge>;
}

export const PENDING: PairStatus[] = ["candidate", "analyzing"];
