import { Bot, CheckCircle2, Clock, Link2, Play } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Card, CardHeader } from "@/components/ui/card";
import { ConfidenceBar } from "@/components/ui/feedback";
import type { Observation } from "@/lib/api/types";
import { humanize } from "@/lib/utils";

import { formatClock, spanLabel } from "./video-segments";

const ORDER = ["activity", "condition", "object", "people", "sensitive", "document_text", "quality", "scene"] as const;
const TITLES: Record<string, string> = {
  activity: "Activities",
  condition: "Conditions",
  object: "Objects",
  people: "People",
  sensitive: "Sensitive content",
  document_text: "Text in image (OCR, untrusted)",
  quality: "Quality",
  scene: "Captions",
};

interface Segment {
  start_ms: number;
  end_ms: number;
}

function parseSpan(span: Record<string, unknown> | null): Segment | null {
  if (!span || span.type !== "segment") return null;
  const start = span.start_ms;
  const end = span.end_ms;
  if (typeof start !== "number" || typeof end !== "number" || end <= start) return null;
  return { start_ms: Math.round(start), end_ms: Math.round(end) };
}

function describe(o: Observation): string {
  const value = (o.value ?? {}) as Record<string, unknown>;
  if (o.ontology_type === "scene") return String(value.text ?? "");
  if (o.ontology_type === "document_text") return String(value.text ?? "");
  if (o.ontology_type === "quality") return String(value.issue ?? "Quality analysis recorded");
  if (o.ontology_type === "people") return value.count_estimate ? `About ${value.count_estimate} people visible` : "People visible";
  if (o.ontology_type === "condition") return `${humanize(o.subject)} — ${humanize(o.predicate)}`;
  if (o.ontology_type === "object" && typeof value.count === "number") return `${humanize(o.subject)} × ${value.count}`;
  return humanize(o.subject);
}

function sourceLabel(o: Observation): string {
  const value = (o.value ?? {}) as Record<string, unknown>;
  if (value.method === "ai_vision_tagging" || value.via === "cloudinary_captioning") return "Cloudinary AI";
  return o.source_provider ? humanize(o.source_provider) : "AI";
}

interface Props {
  observations: Observation[];
  /** Called when user clicks a segment timestamp to seek the video player. */
  onSeek?: (ms: number) => void;
}

export function ObservationsPanel({ observations, onSeek }: Props) {
  const current = observations.filter((o) => o.status !== "superseded");
  const groups = ORDER.map((type) => ({ type, items: current.filter((o) => o.ontology_type === type) })).filter(
    (g) => g.items.length,
  );

  return (
    <Card>
      <CardHeader
        title="What the media appears to show"
        description="Observations, not claims. Each is typed, scored and linked to the analysis run that produced it."
      />
      {groups.length === 0 ? (
        <p className="px-5 py-4 text-sm text-text-muted">No observations yet.</p>
      ) : (
        <div className="divide-y divide-border">
          {groups.map((group) => (
            <div key={group.type} className="px-5 py-3">
              <p className="mb-2 text-xs font-medium uppercase tracking-wider text-text-subtle">{TITLES[group.type]}</p>
              <ul className="flex flex-col gap-2">
                {group.items.map((o) => {
                  const value = (o.value ?? {}) as Record<string, unknown>;
                  const corroborated = (o.review_signals as { corroborated_by?: string[] } | null)?.corroborated_by ?? [];
                  const segment = parseSpan(o.evidence_span as Record<string, unknown> | null);
                  return (
                    <li key={o.id} className="flex items-start justify-between gap-4">
                      <div className="min-w-0">
                        <p className="text-sm">
                          {describe(o)}
                          {o.predicate === "tagged" && <span className="text-text-subtle"> (tag match)</span>}
                        </p>
                        {typeof value.rationale === "string" && (
                          <p className="mt-0.5 text-xs text-text-muted">{value.rationale}</p>
                        )}
                        <div className="mt-1 flex flex-wrap gap-1">
                          <Badge tone="outline">
                            <Bot /> {sourceLabel(o)}
                          </Badge>
                          {o.status === "verified" && (
                            <Badge tone="accent">
                              <CheckCircle2 /> Verified
                            </Badge>
                          )}
                          {corroborated.map((c) => (
                            <Badge key={c} tone="info">
                              <Link2 /> {humanize(c)}
                            </Badge>
                          ))}
                          {segment && onSeek ? (
                            <button
                              type="button"
                              onClick={() => onSeek(segment.start_ms)}
                              className="inline-flex items-center gap-1 rounded-full border border-accent/30 bg-accent-soft px-2 py-0.5 font-mono text-[11px] text-accent transition-colors hover:border-accent hover:bg-accent/20"
                              title={`Jump to ${formatClock(segment.start_ms)}`}
                            >
                              <Play className="size-2.5 fill-accent" />
                              {spanLabel(segment.start_ms, segment.end_ms)}
                            </button>
                          ) : segment ? (
                            <Badge tone="neutral" className="font-mono">
                              <Clock className="size-3" />
                              {spanLabel(segment.start_ms, segment.end_ms)}
                            </Badge>
                          ) : o.evidence_span ? (
                            <Badge tone="neutral" className="font-mono">
                              {String((o.evidence_span as { type?: string }).type)}
                            </Badge>
                          ) : null}
                        </div>
                      </div>
                      {o.ontology_type !== "scene" && o.ontology_type !== "document_text" && (
                        <ConfidenceBar value={o.confidence} />
                      )}
                    </li>
                  );
                })}
              </ul>
            </div>
          ))}
        </div>
      )}
    </Card>
  );
}
