"use client";

import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { useAuthState } from "@/lib/auth/auth-bridge";

import { api, unwrap } from "./client";
import type {
  AssetLineage,
  AssetPage,
  AssetState,
  Campaign,
  CampaignCreate,
  PairStatus,
  ProjectAnalyticsOut,
  ProjectCreate,
  ShareLink,
  SharedContent,
  SiteCreate,
  SpatialTemporalOut,
  SuggestRequest,
} from "./types";

export const keys = {
  me: ["me"] as const,
  presets: ["taxonomy-presets"] as const,
  projects: ["projects"] as const,
  project: (id: string) => ["projects", id] as const,
  sites: (projectId: string) => ["projects", projectId, "sites"] as const,
  taxonomy: (projectId: string) => ["projects", projectId, "taxonomy"] as const,
  assets: (projectId: string) => ["projects", projectId, "assets"] as const,
  asset: (id: string) => ["assets", id] as const,
  pairs: (projectId: string) => ["projects", projectId, "before-after"] as const,
  pair: (id: string) => ["before-after", id] as const,
  campaigns: (projectId: string) => ["projects", projectId, "campaigns"] as const,
  campaign: (id: string) => ["campaigns", id] as const,
  lineage: (assetId: string) => ["assets", assetId, "lineage"] as const,
  shareLinks: (projectId: string) => ["projects", projectId, "share-links"] as const,
  sharedContent: (token: string) => ["share", token] as const,
  spatialTemporal: (projectId: string) => ["projects", projectId, "spatial-temporal"] as const,
  analytics: (projectId: string) => ["projects", projectId, "analytics"] as const,
};

function useEnabled() {
  const auth = useAuthState();
  return auth.ready && auth.signedIn && auth.hasOrganization;
}

export function useMe() {
  const enabled = useEnabled();
  return useQuery({
    queryKey: keys.me,
    enabled,
    staleTime: 60_000,
    queryFn: async () => unwrap(await api.GET("/v1/me")),
  });
}

export function useProjects() {
  return useQuery({
    queryKey: keys.projects,
    enabled: useEnabled(),
    queryFn: async () => unwrap(await api.GET("/v1/projects")),
  });
}

export function useProject(projectId: string) {
  return useQuery({
    queryKey: keys.project(projectId),
    enabled: useEnabled(),
    queryFn: async () =>
      unwrap(await api.GET("/v1/projects/{project_id}", { params: { path: { project_id: projectId } } })),
  });
}

export function useTaxonomyPresets() {
  return useQuery({
    queryKey: keys.presets,
    enabled: useEnabled(),
    staleTime: Infinity,
    queryFn: async () => unwrap(await api.GET("/v1/taxonomy-presets")),
  });
}

export function useCreateProject() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async (body: ProjectCreate) => unwrap(await api.POST("/v1/projects", { body })),
    onSuccess: () => client.invalidateQueries({ queryKey: keys.projects }),
  });
}

export function useSites(projectId: string) {
  return useQuery({
    queryKey: keys.sites(projectId),
    enabled: useEnabled(),
    queryFn: async () =>
      unwrap(await api.GET("/v1/projects/{project_id}/sites", { params: { path: { project_id: projectId } } })),
  });
}

export function useCreateSite(projectId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async (body: SiteCreate) =>
      unwrap(
        await api.POST("/v1/projects/{project_id}/sites", { params: { path: { project_id: projectId } }, body }),
      ),
    onSuccess: () => {
      client.invalidateQueries({ queryKey: keys.sites(projectId) });
      client.invalidateQueries({ queryKey: keys.project(projectId) });
    },
  });
}

export function useTaxonomy(projectId: string) {
  return useQuery({
    queryKey: keys.taxonomy(projectId),
    enabled: useEnabled(),
    queryFn: async () =>
      unwrap(await api.GET("/v1/projects/{project_id}/taxonomy", { params: { path: { project_id: projectId } } })),
  });
}

export type AssetFilters = {
  state?: AssetState;
  site_id?: string;
  resource_type?: "image" | "video";
};

export function useAssets(projectId: string, filters: AssetFilters = {}) {
  return useInfiniteQuery({
    queryKey: [...keys.assets(projectId), filters],
    enabled: useEnabled(),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (last: AssetPage) => last.next_cursor ?? undefined,
    queryFn: async ({ pageParam }): Promise<AssetPage> =>
      unwrap(
        await api.GET("/v1/projects/{project_id}/assets", {
          params: { path: { project_id: projectId }, query: { ...filters, cursor: pageParam, limit: 48 } },
        }),
      ),
  });
}

export function useAsset(assetId: string) {
  return useQuery({
    queryKey: keys.asset(assetId),
    enabled: useEnabled(),
    queryFn: async () =>
      unwrap(await api.GET("/v1/assets/{asset_id}", { params: { path: { asset_id: assetId } } })),
  });
}

export function useMediaUrl(assetId: string, variant: "thumb" | "review", enabled = true) {
  return useQuery({
    queryKey: [...keys.asset(assetId), "media", variant],
    enabled: useEnabled() && enabled,
    staleTime: 10 * 60_000,
    queryFn: async () =>
      unwrap(
        await api.GET("/v1/assets/{asset_id}/media", {
          params: { path: { asset_id: assetId }, query: { variant } },
        }),
      ),
  });
}

export async function fetchOriginalUrl(assetId: string) {
  return unwrap(
    await api.GET("/v1/assets/{asset_id}/media", {
      params: { path: { asset_id: assetId }, query: { variant: "original" } },
    }),
  );
}

export function useStreamUrl(assetId: string, enabled = true) {
  return useQuery({
    queryKey: [...keys.asset(assetId), "media", "stream"],
    enabled: useEnabled() && enabled,
    staleTime: 10 * 60_000,
    queryFn: async () =>
      unwrap(
        await api.GET("/v1/assets/{asset_id}/media", {
          params: { path: { asset_id: assetId }, query: { variant: "stream" } },
        }),
      ),
  });
}

export async function fetchClipUrl(assetId: string, startMs: number, endMs: number) {
  return unwrap(
    await api.GET("/v1/assets/{asset_id}/media", {
      params: { path: { asset_id: assetId }, query: { variant: "clip", start_ms: startMs, end_ms: endMs } },
    }),
  );
}

export function useReanalyze(assetId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async () =>
      unwrap(await api.POST("/v1/assets/{asset_id}/reanalyze", { params: { path: { asset_id: assetId } } })),
    onSuccess: () => client.invalidateQueries({ queryKey: keys.asset(assetId) }),
  });
}

// --- before/after (Phase 7) ----------------------------------------------------------------------

export type PairFilters = { status_filter?: PairStatus; site_id?: string; asset_id?: string };

export function usePairs(projectId: string, filters: PairFilters = {}) {
  return useQuery({
    queryKey: [...keys.pairs(projectId), filters],
    enabled: useEnabled() && !!projectId,
    // candidates are analysed in the background; SSE also refreshes, polling is the fallback
    refetchInterval: (query) =>
      query.state.data?.some((p) => p.status === "candidate" || p.status === "analyzing") ? 5000 : false,
    queryFn: async () =>
      unwrap(
        await api.GET("/v1/projects/{project_id}/before-after", {
          params: { path: { project_id: projectId }, query: filters },
        }),
      ),
  });
}

export function useSuggestPairs(projectId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async (body: SuggestRequest) =>
      unwrap(
        await api.POST("/v1/projects/{project_id}/before-after/suggest", {
          params: { path: { project_id: projectId } },
          body,
        }),
      ),
    onSuccess: () => client.invalidateQueries({ queryKey: keys.pairs(projectId) }),
  });
}

export function usePair(pairId: string) {
  return useQuery({
    queryKey: keys.pair(pairId),
    enabled: useEnabled(),
    refetchInterval: (query) =>
      query.state.data && ["candidate", "analyzing"].includes(query.state.data.status) ? 4000 : false,
    queryFn: async () =>
      unwrap(await api.GET("/v1/before-after/{pair_id}", { params: { path: { pair_id: pairId } } })),
  });
}

export function usePairAction(pairId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async ({ action, note }: { action: "confirm" | "reject" | "analyze"; note?: string }) => {
      const path = { params: { path: { pair_id: pairId } } };
      if (action === "analyze") return unwrap(await api.POST("/v1/before-after/{pair_id}/analyze", path));
      const body = { note: note?.trim() || null };
      if (action === "confirm") return unwrap(await api.POST("/v1/before-after/{pair_id}/confirm", { ...path, body }));
      return unwrap(await api.POST("/v1/before-after/{pair_id}/reject", { ...path, body }));
    },
    onSuccess: (pair) => {
      client.setQueryData(keys.pair(pairId), pair);
      client.invalidateQueries({ queryKey: keys.pairs(pair.project_id) });
    },
  });
}

export function useCampaigns(projectId: string) {
  return useQuery({
    queryKey: keys.campaigns(projectId),
    enabled: useEnabled(),
    queryFn: async () =>
      unwrap(
        await api.GET("/v1/projects/{project_id}/campaigns", {
          params: { path: { project_id: projectId } },
        }),
      ) as unknown as Campaign[],
  });
}

export function useCampaign(campaignId: string) {
  return useQuery({
    queryKey: keys.campaign(campaignId),
    enabled: useEnabled(),
    queryFn: async () =>
      unwrap(
        await api.GET("/v1/campaigns/{campaign_id}", {
          params: { path: { campaign_id: campaignId } },
        }),
      ) as unknown as Campaign,
  });
}

export function useCreateCampaign(projectId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async (body: CampaignCreate) =>
      unwrap(
        await api.POST("/v1/projects/{project_id}/campaigns", {
          params: { path: { project_id: projectId } },
          body: {
            ...body,
            formats: body.formats ?? ["1:1", "4:5", "9:16", "16:9"],
            brand_tag: body.brand_tag ?? null,
            generative_fill: body.generative_fill ?? false,
            generative_restore: body.generative_restore ?? false,
            redact: body.redact ?? true,
          },
        }),
      ) as unknown as Campaign,
    onSuccess: () => {
      client.invalidateQueries({ queryKey: keys.campaigns(projectId) });
    },
  });
}

export function useAssetLineage(assetId: string) {
  return useQuery({
    queryKey: keys.lineage(assetId),
    enabled: useEnabled() && !!assetId,
    queryFn: async () =>
      unwrap(
        await api.GET("/v1/assets/{asset_id}/lineage", {
          params: { path: { asset_id: assetId } },
        }),
      ) as unknown as AssetLineage,
  });
}

export function useShareLinks(projectId: string) {
  return useQuery({
    queryKey: keys.shareLinks(projectId),
    enabled: useEnabled(),
    queryFn: async () =>
      unwrap(
        await api.GET("/v1/projects/{project_id}/share-links", {
          params: { path: { project_id: projectId } },
        }),
      ) as unknown as ShareLink[],
  });
}

export function useCreateShareLink(projectId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async (body: {
      title: string;
      target_type: "report" | "evidence" | "campaign";
      target_id: string;
      expires_in_days?: number;
    }) =>
      unwrap(
        await api.POST("/v1/projects/{project_id}/share-links", {
          params: { path: { project_id: projectId } },
          body: {
            ...body,
            expires_in_days: body.expires_in_days ?? 14,
          },
        }),
      ) as unknown as ShareLink,
    onSuccess: () => {
      client.invalidateQueries({ queryKey: keys.shareLinks(projectId) });
    },
  });
}

export function useRevokeShareLink(projectId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async (linkId: string) =>
      unwrap(
        await api.DELETE("/v1/share-links/{link_id}", {
          params: { path: { link_id: linkId } },
        }),
      ),
    onSuccess: () => {
      client.invalidateQueries({ queryKey: keys.shareLinks(projectId) });
    },
  });
}

export function useSharedContent(token: string) {
  return useQuery({
    queryKey: keys.sharedContent(token),
    enabled: !!token,
    queryFn: async () =>
      unwrap(
        await api.GET("/v1/share/{token}", {
          params: { path: { token } },
        }),
      ) as unknown as SharedContent,
  });
}

export function useSpatialTemporal(projectId: string) {
  return useQuery({
    queryKey: keys.spatialTemporal(projectId),
    enabled: useEnabled() && !!projectId,
    queryFn: async () =>
      unwrap(
        await api.GET("/v1/projects/{project_id}/spatial-temporal", {
          params: { path: { project_id: projectId } },
        }),
      ) as unknown as SpatialTemporalOut,
  });
}

export function useProjectAnalytics(projectId: string) {
  return useQuery({
    queryKey: keys.analytics(projectId),
    enabled: useEnabled() && !!projectId,
    queryFn: async () =>
      unwrap(
        await api.GET("/v1/projects/{project_id}/analytics", {
          params: { path: { project_id: projectId } },
        }),
      ) as unknown as ProjectAnalyticsOut,
  });
}

