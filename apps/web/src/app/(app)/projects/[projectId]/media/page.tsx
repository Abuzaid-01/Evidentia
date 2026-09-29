"use client";

import { Images, UploadCloud } from "lucide-react";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { Suspense } from "react";

import { AssetCard } from "@/components/assets/asset-card";
import { Button, LinkButton } from "@/components/ui/button";
import { EmptyState, ErrorState, Skeleton } from "@/components/ui/feedback";
import { Select } from "@/components/ui/form";
import { PageHeader } from "@/components/ui/page-header";
import { useAssets, useProject, useSites, type AssetFilters } from "@/lib/api/hooks";
import type { AssetState } from "@/lib/api/types";
import { cn } from "@/lib/utils";

const STATE_TABS: { label: string; value?: AssetState }[] = [
  { label: "All" },
  { label: "Needs review", value: "review_required" },
  { label: "Ready", value: "ready" },
  { label: "Analysing", value: "analyzing" },
  { label: "Failed", value: "failed_permanent" },
];

function MediaLibrary() {
  const { projectId } = useParams<{ projectId: string }>();
  const search = useSearchParams();
  const router = useRouter();
  const { data: project } = useProject(projectId);
  const sites = useSites(projectId);

  const filters: AssetFilters = {
    state: (search.get("state") as AssetState | null) ?? undefined,
    site_id: search.get("site") ?? undefined,
    resource_type: (search.get("type") as "image" | "video" | null) ?? undefined,
  };
  const assets = useAssets(projectId, filters);
  const items = assets.data?.pages.flatMap((page) => page.items) ?? [];

  function setFilter(key: string, value?: string) {
    const params = new URLSearchParams(search.toString());
    if (value) params.set(key, value);
    else params.delete(key);
    router.replace(`?${params.toString()}`, { scroll: false });
  }

  return (
    <>
      <PageHeader
        eyebrow={project?.name}
        title="Media library"
        description="Every item is a private Cloudinary asset with its provenance, AI observations and review status."
        actions={
          <LinkButton href={`/projects/${projectId}/upload`}>
            <UploadCloud /> Upload
          </LinkButton>
        }
      />

      <div className="mb-5 flex flex-wrap items-center justify-between gap-3">
        <div className="flex rounded-lg border border-border bg-surface p-1 shadow-card">
          {STATE_TABS.map((tab) => (
            <button
              key={tab.label}
              type="button"
              onClick={() => setFilter("state", tab.value)}
              className={cn(
                "rounded-md px-3 py-1.5 text-sm transition",
                filters.state === tab.value ? "bg-accent-soft font-medium text-accent" : "text-text-muted hover:text-text",
              )}
            >
              {tab.label}
            </button>
          ))}
        </div>
        <div className="flex gap-2">
          <Select className="w-44" value={filters.site_id ?? ""} onChange={(e) => setFilter("site", e.target.value)}>
            <option value="">All sites</option>
            {sites.data?.map((s) => (
              <option key={s.id} value={s.id}>
                {s.code} · {s.name}
              </option>
            ))}
          </Select>
          <Select className="w-32" value={filters.resource_type ?? ""} onChange={(e) => setFilter("type", e.target.value)}>
            <option value="">All media</option>
            <option value="image">Photos</option>
            <option value="video">Videos</option>
          </Select>
        </div>
      </div>

      {assets.error && <ErrorState error={assets.error} onRetry={() => assets.refetch()} />}
      {assets.isLoading && (
        <div className="grid grid-cols-2 gap-4 md:grid-cols-3 xl:grid-cols-4">
          {Array.from({ length: 8 }).map((_, i) => (
            <Skeleton key={i} className="aspect-[4/5]" />
          ))}
        </div>
      )}
      {!assets.isLoading && items.length === 0 && !assets.error && (
        <EmptyState
          icon={Images}
          title="Nothing here yet"
          description="Upload field photos and videos; they appear here as they are processed."
          action={<LinkButton href={`/projects/${projectId}/upload`}>Upload evidence</LinkButton>}
        />
      )}
      {items.length > 0 && (
        <div className="grid grid-cols-2 gap-4 md:grid-cols-3 xl:grid-cols-4">
          {items.map((asset) => (
            <AssetCard key={asset.id} asset={asset} />
          ))}
        </div>
      )}
      {assets.hasNextPage && (
        <div className="mt-6 flex justify-center">
          <Button variant="secondary" loading={assets.isFetchingNextPage} onClick={() => assets.fetchNextPage()}>
            Load more
          </Button>
        </div>
      )}
    </>
  );
}

export default function MediaPage() {
  return (
    <Suspense fallback={<Skeleton className="h-96" />}>
      <MediaLibrary />
    </Suspense>
  );
}
