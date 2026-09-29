"use client";

import { Clock, Film, MessageSquareText, Play } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Card, CardHeader } from "@/components/ui/card";
import type { Observation } from "@/lib/api/types";
import { humanize } from "@/lib/utils";

/** Parsed evidence span with start/end in milliseconds. */
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

/** Format ms → "01:23" or "1:02:03". */
export function formatClock(ms: number): string {
  const total = Math.max(0, Math.round(ms / 1000));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const seconds = total % 60;
  if (hours) {
    return `${hours.toString().padStart(2, "0")}:${minutes.toString().padStart(2, "0")}:${seconds.toString().padStart(2, "0")}`;
  }
  return `${minutes.toString().padStart(2, "0")}:${seconds.toString().padStart(2, "0")}`;
}

/** Format a span as "00:21–00:37". */
export function spanLabel(start_ms: number, end_ms: number): string {
  return `${formatClock(start_ms)}–${formatClock(end_ms)}`;
}

interface SegmentObs {
  observation: Observation;
  segment: Segment;
}

function describeSegment(o: Observation): string {
  const value = (o.value ?? {}) as Record<string, unknown>;
  if (o.ontology_type === "scene") return String(value.text ?? "").slice(0, 200);
  if (o.ontology_type === "document_text") return String(value.text ?? "").slice(0, 200);
  if (o.ontology_type === "activity") {
    const rationale = String(value.rationale ?? "").trim();
    return rationale ? `${humanize(o.subject)}: ${rationale}` : humanize(o.subject);
  }
  return humanize(o.subject);
}

function iconFor(o: Observation) {
  if (o.ontology_type === "document_text" && o.subject === "speech") {
    return <MessageSquareText className="size-3.5 shrink-0 text-info" />;
  }
  return <Film className="size-3.5 shrink-0 text-accent" />;
}

interface Props {
  observations: Observation[];
  /** Currently playing time in ms — highlights the active segment. */
  currentTimeMs?: number;
  /** Called when user clicks a segment to seek. */
  onSeek?: (ms: number) => void;
}

/**
 * Video timeline: clickable segment cards for every observation that has a
 * time span. Grouped by time order, with the active segment highlighted.
 */
export function VideoSegments({ observations, currentTimeMs, onSeek }: Props) {
  const segments: SegmentObs[] = observations
    .filter((o) => o.status !== "superseded")
    .map((o) => {
      const seg = parseSpan(o.evidence_span as Record<string, unknown> | null);
      return seg ? { observation: o, segment: seg } : null;
    })
    .filter((x): x is SegmentObs => x !== null)
    .sort((a, b) => a.segment.start_ms - b.segment.start_ms);

  if (segments.length === 0) return null;

  // Group by type (visual vs speech)
  const visual = segments.filter((s) => s.observation.subject !== "speech");
  const speech = segments.filter((s) => s.observation.subject === "speech");

  function isActive(seg: Segment): boolean {
    if (currentTimeMs === undefined) return false;
    return currentTimeMs >= seg.start_ms && currentTimeMs < seg.end_ms;
  }

  function renderSegment({ observation: o, segment: seg }: SegmentObs) {
    const active = isActive(seg);
    return (
      <button
        key={o.id}
        type="button"
        onClick={() => onSeek?.(seg.start_ms)}
        className={`group flex w-full items-start gap-3 rounded-lg border px-3 py-2.5 text-left transition-all ${
          active
            ? "border-accent/60 bg-accent-soft"
            : "border-transparent hover:border-border hover:bg-surface-muted"
        }`}
      >
        <div className="mt-0.5 flex items-center gap-1.5">
          {active ? (
            <Play className="size-3.5 shrink-0 fill-accent text-accent" />
          ) : (
            iconFor(o)
          )}
        </div>
        <div className="min-w-0 flex-1">
          <p className="text-sm leading-snug">{describeSegment(o)}</p>
          <div className="mt-1 flex flex-wrap items-center gap-1.5">
            <Badge tone={active ? "accent" : "outline"} className="font-mono text-[11px]">
              <Clock className="size-3" />
              {spanLabel(seg.start_ms, seg.end_ms)}
            </Badge>
            <Badge tone="outline" className="text-[11px]">
              {humanize(o.ontology_type)}
            </Badge>
            {o.source_provider && (
              <Badge tone="outline" className="text-[11px]">
                {humanize(o.source_provider)}
              </Badge>
            )}
          </div>
        </div>
      </button>
    );
  }

  return (
    <Card>
      <CardHeader
        title="Video timeline"
        description="Click a segment to jump to that moment in the video."
      />
      <div className="flex flex-col gap-1 px-3 pb-3">
        {visual.length > 0 && (
          <>
            <p className="mb-1 mt-1 px-2 text-xs font-medium uppercase tracking-wider text-text-subtle">
              Visual segments
            </p>
            {visual.map(renderSegment)}
          </>
        )}
        {speech.length > 0 && (
          <>
            <p className="mb-1 mt-3 px-2 text-xs font-medium uppercase tracking-wider text-text-subtle">
              Speech transcript
            </p>
            {speech.map(renderSegment)}
          </>
        )}
      </div>
    </Card>
  );
}
