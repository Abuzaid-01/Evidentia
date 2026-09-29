/* eslint-disable @next/next/no-img-element */
"use client";

import { useMemo, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import {
  Calendar,
  Compass,
  ExternalLink,
  Layers,
  MapPin,
} from "lucide-react";

import { PageHeader } from "@/components/ui/page-header";
import { useProject, useSpatialTemporal } from "@/lib/api/hooks";
import type { SpatialPoint } from "@/lib/api/types";
import { cn } from "@/lib/utils";

export default function MapTimelinePage() {
  const { projectId } = useParams<{ projectId: string }>();
  const { data: project } = useProject(projectId);
  const { data: spatialData, isLoading, error } = useSpatialTemporal(projectId);

  const [selectedSiteId, setSelectedSiteId] = useState<string | "all">("all");
  const [selectedDate, setSelectedDate] = useState<string | "all">("all");
  const [selectedPoint, setSelectedPoint] = useState<SpatialPoint | null>(null);

  const points = spatialData?.points;

  const filteredPoints = useMemo(() => {
    if (!points) return [];
    return points.filter((pt) => {
      const matchSite = selectedSiteId === "all" || pt.site_id === selectedSiteId;
      const matchDate =
        selectedDate === "all" ||
        (pt.capture_time && pt.capture_time.slice(0, 10) === selectedDate);
      return matchSite && matchDate;
    });
  }, [points, selectedSiteId, selectedDate]);

  if (isLoading) {
    return (
      <div className="space-y-6">
        <PageHeader
          eyebrow={project?.name}
          title="Map & Timeline"
          description="Geographic and chronological distribution of verified field assets."
        />
        <div className="flex h-96 items-center justify-center rounded-xl border border-border bg-surface/50 text-text-muted">
          Loading spatial-temporal data...
        </div>
      </div>
    );
  }

  if (error || !spatialData) {
    return (
      <div className="space-y-6">
        <PageHeader
          eyebrow={project?.name}
          title="Map & Timeline"
          description="Geographic and chronological distribution of verified field assets."
        />
        <div className="rounded-xl border border-border bg-surface p-8 text-center text-text-muted">
          Failed to load spatial-temporal data.
        </div>
      </div>
    );
  }

  const { total_geotagged, bounds, sites, timeline } = spatialData;

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow={project?.name}
        title="Map & Timeline"
        description="Explore field evidence across space and time. Cross-correlate capture coordinates with telemetry and audit activity milestones."
      />

      {/* Top metrics bar */}
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
        <div className="rounded-xl border border-border bg-surface p-4">
          <p className="text-xs font-medium text-text-muted">Geotagged Assets</p>
          <p className="mt-1 text-2xl font-bold text-text">{total_geotagged}</p>
        </div>
        <div className="rounded-xl border border-border bg-surface p-4">
          <p className="text-xs font-medium text-text-muted">Field Sites</p>
          <p className="mt-1 text-2xl font-bold text-text">{sites.length}</p>
        </div>
        <div className="rounded-xl border border-border bg-surface p-4">
          <p className="text-xs font-medium text-text-muted">Active Days</p>
          <p className="mt-1 text-2xl font-bold text-text">{timeline.length}</p>
        </div>
        <div className="rounded-xl border border-border bg-surface p-4">
          <p className="text-xs font-medium text-text-muted">Bounding Box</p>
          <p className="mt-1 text-xs text-text-muted truncate">
            {bounds.min_lat !== null
              ? `${bounds.min_lat?.toFixed(2)}°, ${bounds.min_lng?.toFixed(2)}° to ${bounds.max_lat?.toFixed(2)}°, ${bounds.max_lng?.toFixed(2)}°`
              : "No coordinates recorded"}
          </p>
        </div>
      </div>

      {/* Timeline Scrubber */}
      <div className="rounded-xl border border-border bg-surface p-5 shadow-xs">
        <div className="flex items-center justify-between pb-3 border-b border-border">
          <div className="flex items-center gap-2">
            <Calendar className="size-4 text-accent" />
            <h3 className="font-semibold text-text text-sm">Chronological Activity Scrubber</h3>
          </div>
          {selectedDate !== "all" && (
            <button
              onClick={() => setSelectedDate("all")}
              className="text-xs text-accent hover:underline cursor-pointer"
            >
              Reset to all dates
            </button>
          )}
        </div>

        {timeline.length === 0 ? (
          <p className="py-4 text-center text-xs text-text-muted">
            No capture timestamps available for this project yet.
          </p>
        ) : (
          <div className="mt-4 flex gap-2 overflow-x-auto pb-2">
            <button
              onClick={() => setSelectedDate("all")}
              className={cn(
                "flex shrink-0 flex-col items-center justify-center rounded-lg border px-3 py-2 text-xs transition cursor-pointer",
                selectedDate === "all"
                  ? "border-accent bg-accent-soft text-accent font-semibold"
                  : "border-border bg-surface-muted text-text-muted hover:border-text-subtle",
              )}
            >
              <span>All Dates</span>
              <span className="text-[10px] opacity-75">{total_geotagged} assets</span>
            </button>
            {timeline.map((bucket) => {
              const isSelected = selectedDate === bucket.date;
              return (
                <button
                  key={bucket.date}
                  onClick={() => setSelectedDate(bucket.date)}
                  className={cn(
                    "flex shrink-0 flex-col items-center justify-center rounded-lg border px-3 py-2 text-xs transition cursor-pointer",
                    isSelected
                      ? "border-accent bg-accent-soft text-accent font-semibold"
                      : "border-border bg-surface-muted text-text-muted hover:border-text-subtle",
                  )}
                >
                  <span>{bucket.date}</span>
                  <span className="text-[10px] opacity-75">
                    {bucket.count} {bucket.count === 1 ? "asset" : "assets"}
                  </span>
                </button>
              );
            })}
          </div>
        )}
      </div>

      {/* Main Grid: Sites & Points Interactive Map Representation */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        {/* Left column: Sites Filter & Point Selection */}
        <div className="space-y-4">
          <div className="rounded-xl border border-border bg-surface p-4">
            <div className="flex items-center gap-2 pb-3 border-b border-border">
              <Layers className="size-4 text-text-muted" />
              <h4 className="text-sm font-medium text-text">Sites & Telemetry</h4>
            </div>
            <div className="mt-3 space-y-1">
              <button
                onClick={() => setSelectedSiteId("all")}
                className={cn(
                  "flex w-full items-center justify-between rounded-md px-2.5 py-1.5 text-xs transition cursor-pointer",
                  selectedSiteId === "all"
                    ? "bg-accent-soft text-accent font-medium"
                    : "text-text-muted hover:bg-surface-muted",
                )}
              >
                <span>All Locations</span>
                <span className="font-mono">{total_geotagged}</span>
              </button>
              {sites.map((site) => (
                <button
                  key={site.id}
                  onClick={() => setSelectedSiteId(site.id)}
                  className={cn(
                    "flex w-full items-center justify-between rounded-md px-2.5 py-1.5 text-xs transition cursor-pointer",
                    selectedSiteId === site.id
                      ? "bg-accent-soft text-accent font-medium"
                      : "text-text-muted hover:bg-surface-muted",
                  )}
                >
                  <div className="flex items-center gap-1.5 truncate">
                    <MapPin className="size-3 shrink-0 text-accent" />
                    <span className="truncate">{site.name}</span>
                  </div>
                  <span className="font-mono">{site.asset_count}</span>
                </button>
              ))}
            </div>
          </div>

          {/* Selected point inspector */}
          {selectedPoint && (
            <div className="rounded-xl border border-accent/40 bg-surface p-4 shadow-sm">
              <div className="flex items-center justify-between pb-2 border-b border-border">
                <span className="text-xs font-semibold text-accent">Selected Evidence Point</span>
                <button
                  onClick={() => setSelectedPoint(null)}
                  className="text-xs text-text-muted hover:text-text cursor-pointer"
                >
                  ✕
                </button>
              </div>
              <div className="mt-3 space-y-2 text-xs">
                {selectedPoint.thumbnail_url && (
                  <div className="relative aspect-video w-full overflow-hidden rounded-md border border-border bg-black/5">
                    <img
                      src={selectedPoint.thumbnail_url}
                      alt={selectedPoint.public_id}
                      className="h-full w-full object-cover"
                    />
                  </div>
                )}
                <div>
                  <p className="text-[10px] text-text-muted uppercase">Activity</p>
                  <p className="font-medium text-text">
                    {selectedPoint.activity ? selectedPoint.activity.replace(/_/g, " ") : "Unspecified"}
                  </p>
                </div>
                <div className="grid grid-cols-2 gap-2">
                  <div>
                    <p className="text-[10px] text-text-muted uppercase">Latitude</p>
                    <p className="font-mono text-text">{selectedPoint.latitude.toFixed(5)}°</p>
                  </div>
                  <div>
                    <p className="text-[10px] text-text-muted uppercase">Longitude</p>
                    <p className="font-mono text-text">{selectedPoint.longitude.toFixed(5)}°</p>
                  </div>
                </div>
                <div className="grid grid-cols-2 gap-2">
                  <div>
                    <p className="text-[10px] text-text-muted uppercase">Source</p>
                    <p className="font-medium text-text uppercase">{selectedPoint.location_source}</p>
                  </div>
                  <div>
                    <p className="text-[10px] text-text-muted uppercase">Capture Time</p>
                    <p className="text-text truncate">
                      {selectedPoint.capture_time ? new Date(selectedPoint.capture_time).toLocaleString() : "N/A"}
                    </p>
                  </div>
                </div>
                <div className="pt-2">
                  <Link
                    href={`/projects/${projectId}/media?assetId=${selectedPoint.id}`}
                    className="flex items-center justify-center gap-1.5 w-full rounded-md bg-accent px-3 py-1.5 text-xs font-medium text-white transition hover:bg-accent/90"
                  >
                    <span>View Full Evidence</span>
                    <ExternalLink className="size-3" />
                  </Link>
                </div>
              </div>
            </div>
          )}
        </div>

        {/* Right 2 columns: Spatial Cluster Matrix */}
        <div className="lg:col-span-2 space-y-4">
          <div className="rounded-xl border border-border bg-surface p-5">
            <div className="flex items-center justify-between pb-3 border-b border-border">
              <div className="flex items-center gap-2">
                <Compass className="size-4 text-accent" />
                <h3 className="font-semibold text-text text-sm">Georeferenced Points ({filteredPoints.length})</h3>
              </div>
              <span className="text-xs text-text-muted">
                {selectedDate !== "all" ? `Date: ${selectedDate}` : "All dates"}
                {selectedSiteId !== "all" && ` • Site filter active`}
              </span>
            </div>

            {filteredPoints.length === 0 ? (
              <div className="flex flex-col items-center justify-center py-16 text-center text-text-muted">
                <MapPin className="size-8 stroke-1 text-text-subtle mb-2" />
                <p className="text-sm">No geotagged assets match the current filter criteria.</p>
                <button
                  onClick={() => {
                    setSelectedSiteId("all");
                    setSelectedDate("all");
                  }}
                  className="mt-3 text-xs text-accent hover:underline cursor-pointer"
                >
                  Clear all filters
                </button>
              </div>
            ) : (
              <div className="mt-4 grid grid-cols-1 sm:grid-cols-2 gap-3">
                {filteredPoints.map((pt) => {
                  const isSelected = selectedPoint?.id === pt.id;
                  return (
                    <div
                      key={pt.id}
                      onClick={() => setSelectedPoint(pt)}
                      className={cn(
                        "flex gap-3 rounded-lg border p-3 transition cursor-pointer",
                        isSelected
                          ? "border-accent bg-accent-soft/40 shadow-xs ring-1 ring-accent"
                          : "border-border bg-surface hover:border-text-subtle hover:bg-surface-muted/50",
                      )}
                    >
                      <div className="relative size-16 shrink-0 overflow-hidden rounded-md border border-border bg-surface-muted">
                        {pt.thumbnail_url ? (
                          <img
                            src={pt.thumbnail_url}
                            alt=""
                            className="h-full w-full object-cover"
                          />
                        ) : (
                          <div className="flex h-full w-full items-center justify-center text-[10px] text-text-subtle">
                            No preview
                          </div>
                        )}
                      </div>
                      <div className="min-w-0 flex-1 space-y-1 text-xs">
                        <div className="flex items-center justify-between">
                          <span className="font-medium text-text truncate">
                            {pt.activity ? pt.activity.replace(/_/g, " ") : "Observation"}
                          </span>
                          <span className="rounded bg-surface-muted px-1.5 py-0.5 text-[10px] font-mono text-text-muted">
                            {pt.location_source}
                          </span>
                        </div>
                        <p className="text-[11px] font-mono text-text-muted truncate">
                          {pt.latitude.toFixed(4)}°, {pt.longitude.toFixed(4)}°
                        </p>
                        <p className="text-[11px] text-text-muted truncate">
                          {pt.site_name ?? "Unassigned site"}
                        </p>
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
