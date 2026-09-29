import type { components } from "./schema";

type Schemas = components["schemas"];

export type Me = Schemas["MeOut"];
export type Role = Schemas["Role"];
export type Project = Schemas["ProjectOut"];
export type ProjectCreate = Schemas["ProjectCreate"];
export type Site = Schemas["SiteOut"];
export type SiteCreate = Schemas["SiteCreate"];
export type Taxonomy = Schemas["TaxonomyOut"];
export type TaxonomyPreset = Schemas["TaxonomyPresetOut"];
export type Activity = Schemas["Activity"];
export type AssetSummary = Schemas["AssetSummary"];
export type AssetPage = Schemas["Page_AssetSummary_"];
export type AssetDetail = Schemas["AssetDetail"];
export type AssetState = Schemas["AssetState"];
export type Observation = Schemas["ObservationOut"];
export type AnalysisRun = Schemas["AnalysisRunOut"];
export type Derivative = Schemas["DerivativeOut"];
export type UploadSignResponse = Schemas["UploadSignResponse"];
export type MediaUrl = Schemas["MediaUrlOut"];
export type SearchResponse = Schemas["SearchResponse"];
export type SearchResult = Schemas["SearchResult"];
export type SimilarResult = Schemas["SimilarResult"];
export type QueueItem = Schemas["QueueItem"];
export type Claim = Schemas["ClaimOut"];
export type ClaimDetail = Schemas["ClaimDetail"];
export type Metric = Schemas["MetricOut"];
export type Report = Schemas["ReportOut"];
export type ReportDetail = Schemas["ReportDetail"];
export type ReportSnapshot = Schemas["SnapshotOut"];
export type PairSummary = Schemas["PairSummary"];
export type PairDetail = Schemas["PairDetail"];
export type PairStatus = Schemas["PairStatus"];
export type SuggestRequest = Schemas["SuggestRequest"];
export type SuggestOut = Schemas["SuggestOut"];

/** Alignment as stored by the worker (evidentia_ml.before_after.Alignment + image sizes). */
export type PairAlignment = {
  ok: boolean;
  method: string;
  inliers: number;
  inlier_ratio: number;
  overlap: number;
  homography: number[][] | null;
  rotation_deg: number | null;
  scale: number | null;
  before_box: number[];
  after_box: number[];
  reason: string | null;
  before_size?: number[];
  after_size?: number[];
};

export type ChangeRegion = { x: number; y: number; w: number; h: number; area_share: number; kind: "changed" | "more_green" | "less_green" };

export type PairChanges = {
  method: string;
  shared_share: number;
  ssim_mean: number;
  changed_share: number;
  luminance_shift: number;
  green_cover_before: number;
  green_cover_after: number;
  green_delta_pp: number;
  regions: ChangeRegion[];
};

const ROLE_RANK: Record<Role, number> = { viewer: 0, contributor: 1, reviewer: 2, manager: 3, admin: 4 };

export function hasRole(role: Role | undefined, needed: Role): boolean {
  return role !== undefined && ROLE_RANK[role] >= ROLE_RANK[needed];
}

export type SocialRendition = {
  format: string;
  url: string;
  transformation: string;
  named_transformation?: string | null;
  generative: boolean;
  purpose: string;
};

export type Campaign = {
  id: string;
  project_id: string;
  title: string;
  headline: string;
  stat_text: string | null;
  brand_tag: string | null;
  asset_id: string;
  pair_id: string | null;
  claim_id: string | null;
  metric_id: string | null;
  formats: string[];
  generative: boolean;
  renditions: Record<string, SocialRendition>;
  created_at: string;
};

export type CampaignCreate = {
  title: string;
  headline: string;
  stat_text?: string | null;
  brand_tag?: string | null;
  asset_id: string;
  pair_id?: string | null;
  claim_id?: string | null;
  metric_id?: string | null;
  formats?: string[];
  generative_fill?: boolean;
  generative_restore?: boolean;
  redact?: boolean;
};

export type LineageDerivative = {
  id: string;
  purpose: string;
  named_transformation?: string | null;
  transformation: string;
  format?: string | null;
  source: string;
  generative: boolean;
  url: string;
  created_at: string;
};

export type AssetLineage = {
  asset_id: string;
  original_filename: string | null;
  public_id: string;
  format: string | null;
  bytes: number | null;
  sha256: string | null;
  phash: string | null;
  capture_time: string | null;
  capture_time_source: string;
  uploaded_at: string | null;
  derivatives: LineageDerivative[];
  pairs: Array<{ id: string; role: string; status: string; rank_score: number; change_summary: string | null }>;
  claims: Array<{ claim_id: string; statement: string; status: string; relation: string }>;
  campaigns: Array<{ campaign_id: string; title: string; headline: string; formats: string[]; generative: boolean }>;
};

export type ShareLink = {
  id: string;
  project_id: string;
  token: string;
  title: string;
  target_type: string;
  target_id: string;
  share_url: string;
  expires_at: string;
  view_count: number;
  is_revoked: boolean;
  created_at: string;
};

export type SharedContent = {
  token: string;
  title: string;
  target_type: string;
  project_name: string;
  expires_at: string;
  data: Record<string, unknown>;
  lineage: LineageDerivative[];
};

export type SpatialPoint = {
  id: string;
  public_id: string;
  thumbnail_url: string | null;
  latitude: number;
  longitude: number;
  location_source: string;
  capture_time: string | null;
  activity: string | null;
  site_id: string | null;
  site_name: string | null;
};

export type SpatialSite = {
  id: string;
  name: string;
  code: string | null;
  latitude: number | null;
  longitude: number | null;
  asset_count: number;
};

export type TimelineBucket = {
  date: string;
  count: number;
  activities: Record<string, number>;
};

export type SpatialBounds = {
  min_lat: number | null;
  max_lat: number | null;
  min_lng: number | null;
  max_lng: number | null;
};

export type SpatialTemporalOut = {
  project_id: string;
  total_geotagged: number;
  bounds: SpatialBounds;
  sites: SpatialSite[];
  points: SpatialPoint[];
  timeline: TimelineBucket[];
};

export type CostBreakdown = {
  storage_gb: number;
  storage_cost_usd: number;
  derivatives_count: number;
  transformations_cost_usd: number;
  ai_analysis_runs: number;
  ai_tokens_cost_usd: number;
  total_estimated_usd: number;
};

export type IngestionHealth = {
  total_assets: number;
  state_counts: Record<string, number>;
  failure_rate_pct: number;
  avg_latency_ms: number;
  p95_latency_ms: number;
  total_analysis_runs: number;
  successful_runs: number;
  failed_runs: number;
};

export type VerificationHealth = {
  claims_total: number;
  claims_approved: number;
  claims_rejected: number;
  claims_disputed: number;
  claims_pending: number;
  approval_rate_pct: number;
};

export type ActivityMetric = {
  activity: string;
  count: number;
};

export type ProjectAnalyticsOut = {
  project_id: string;
  ingestion: IngestionHealth;
  costs: CostBreakdown;
  verification: VerificationHealth;
  activities: ActivityMetric[];
};

