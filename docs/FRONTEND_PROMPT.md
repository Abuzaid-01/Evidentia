# Frontend prompt for Lovable (or any AI UI builder)

How to use this file:
- **Paste Prompt 1** (everything between the `=== PROMPT 1 ===` markers) as your first message.
- Then paste **Prompt 2** and **Prompt 3** one at a time, after each result works.
- Keep `VITE_USE_MOCKS=true` while designing. The app must look complete on mock data alone.
- When you are happy, give the code back and it gets connected to the real backend. That only works
  cleanly if the rules in "Integration contract" are followed exactly, so don't let the builder skip them.

---

=== PROMPT 1 ===

# Build the frontend for "Evidentia": the evidence room for field programmes

## 1. What the product is (read this first; it drives every design decision)

Evidentia turns raw field photos and videos into **evidence you can defend**. NGOs and sustainability
teams upload media from project sites (water pipes, sewer and manhole maintenance, tanks, community taps).
AI (Cloudinary AI, with Gemini and Groq as fallbacks) describes what each photo shows. Humans verify it.
Verified evidence backs **claims** ("4 manholes were cleaned by the crew"). Claims become **reports**
where **every sentence cites its proof**, and a published report is frozen and can be re-verified by
anyone.

Core idea to express visually: **Observation ≠ Claim ≠ Metric**.
- **Observation**: what one photo appears to show (AI or human, with a confidence score).
- **Claim**: what the organisation asserts, backed by verified observations.
- **Metric**: a measured number with a declared source ("142 households, door-to-door survey, Form HH-7").

Tagline: **"Every sentence and every pixel traces back to its source."**
Audience: programme managers, field staff, reviewers, donors, and hackathon judges who have about
3 minutes. The first impression must say *trustworthy, precise, modern, alive*.

## 2. Tech stack (mandatory)

- React 18 + TypeScript (strict) + Vite
- Tailwind CSS + shadcn/ui (Radix) + lucide-react icons
- TanStack Query v5 for all server data
- framer-motion for animation; Lenis for smooth scrolling on the **landing page only**
- react-router v6, with **all routes defined in one file**: `src/routes.tsx`
- MapLibre GL (map page), Recharts (analytics)
- **No Supabase, no Lovable Cloud, no backend, no database, no auth provider.** This is a pure
  frontend talking to an existing REST API (described below). Do not generate server code.

## 3. Visual design direction

**Mood:** an "evidence room": editorial and forensic. Think a precise, calm investigation tool crossed
with a premium magazine, not a generic SaaS dashboard.

**Theme:** dark by default, with a polished light mode (toggle in the header, persisted). All colours
are CSS variables defined in one place (`src/styles/tokens.css`) and mapped in the Tailwind config.
- Background: near-black green-grey (`#0E1311`); surfaces a step lighter; hairline borders.
- Accent: **evidence green** `#5FD39A` (primary actions, verified states, citations).
- Warning: amber (needs review, partial match). Danger: coral red (rejected, failed).
- Info: cool blue (AI-generated, not yet verified).

**Typography:**
- Display: a refined serif (Instrument Serif or Fraunces) for big headings and report-like text.
- UI: Inter or Geist.
- Mono: JetBrains Mono for IDs, hashes, timestamps and Cloudinary transformation strings. These are
  *features*: show them proudly in small mono chips, because traceability is the product.

**Signature motifs (use them consistently):**
1. **The provenance chain:** a thin animated line connecting *Photo → Observation → Claim → Report
   sentence*. It appears on the landing page, the claim page and the report page.
2. **Citation chips:** `[C1]` `[M1]` small pill links; hovering one highlights its source with a glow.
3. **Status chips** with a coloured dot and a tiny pulse while a state is changing.
4. **"Verified" seal:** a subtle stamp or check animation when something becomes verified or approved.
5. **Hash reveal:** SHA-256 values shown truncated (`5d541e58…`); clicking expands with a typewriter
   effect and a copy button.

## 4. Motion and interaction (make it feel premium, but never slow)

**Landing page (bold):**
- Lenis smooth scroll plus a scroll-progress bar at the top.
- **Hero parallax:** 3–4 layered field photos (mock images) moving at different scroll speeds; the
  headline stays sticky while photos slide under it. Photos get "scanned": an AI bounding box and a
  label draw themselves on (`manhole · 95%`).
- **Scroll-driven story (pinned section)** in 5 steps: Upload → AI understands → Human verifies →
  Claim → Cited report. Each step animates as you scroll, and the provenance-chain line draws itself
  between them.
- Count-up stats on scroll-in (e.g. "0 uncited sentences", "p95 search 554 ms", "100% of numbers
  sourced").
- Magnetic primary buttons; a cursor-following soft glow on the hero; a marquee of Cloudinary feature
  names (Signed uploads · AI Vision · Face pixelation · Named transformations · Video · Overlays).
- Staggered fade-up reveals for sections (`whileInView`, once).

**In the app (subtle and fast):**
- Page transitions: 150–200 ms fade and slide. Skeleton shimmer while loading, never blank screens.
- Upload: files fly into the grid; the progress ring morphs into a status chip; the chip updates live
  (awaiting_upload → uploaded → analyzing → ready).
- Search: results stagger in; "why this result" reasons expand; missing words shown struck through.
- Approve or verify: seal animation plus a toast. Publish: a "freeze" animation (a frost or lock sweep),
  then the version badge appears.
- Before/after: a draggable comparison slider with a spring.
- Everything respects `prefers-reduced-motion` (parallax and pinning off, fades only).

**Quality bar:** responsive from 360 px to wide desktop; keyboard accessible; visible focus rings;
WCAG AA contrast in both themes; Lighthouse performance above 90 on the landing page (lazy-load
images, no layout shift).

## 5. Integration contract (the most important section; follow it exactly)

The real backend already exists. Your code must be connectable by swapping mocks for real calls
**without touching any page or component**. Rules:

1. **All network access lives in `src/api/`.** Components never call `fetch`. Pages use hooks from
   `src/api/hooks.ts` only.
2. `src/api/types.ts` holds the types in section 7, **with these exact names and field names**
   (snake_case, as the API returns them). Do not rename, camelCase or reshape them.
3. `src/api/endpoints.ts` has one async function per endpoint in section 6, with the exact method and
   path, e.g. `getAsset(assetId)` → `GET /v1/assets/{asset_id}`.
4. `src/api/client.ts` is a tiny fetch wrapper:
   - base URL from `import.meta.env.VITE_API_BASE_URL` (default `http://localhost:8000`)
   - adds `Authorization: Bearer <token>` from `getToken()` in `src/auth/session.ts`
   - JSON in and out; on non-2xx it throws `ApiError(message, status, code, details)` parsed from the
     API's error body: `{ "error": { "code": string, "message": string, "details": any }, "request_id": string }`
5. `src/api/mock/` implements **the same functions** with realistic in-memory data and latency
   (200–600 ms). `src/api/index.ts` exports mock or real based on `VITE_USE_MOCKS` (default `true`).
   Mocks must respect the business rules in section 8, so the demo feels real.
6. **Never build Cloudinary URLs in the browser.** Every image or video URL comes from the API
   (`thumb_url`, `before_url`, `composite_url`, or `getMedia(asset, variant)`). They are signed. In mocks,
   use royalty-free placeholder images of pipes, manholes, trenches, water tanks and field workers.
7. **Uploads** go through `src/lib/upload.ts` → `uploadFile(file, ctx, onProgress)`:
   `POST /v1/uploads/sign` → multipart POST **directly** to the returned `upload_url` with every entry
   of `fields` plus `file` → `POST /v1/assets/{asset_id}/confirm` with `{public_id, version, signature}`
   taken from Cloudinary's response. Files larger than `chunk_size` use Cloudinary chunked upload:
   the same fields on every chunk, headers `X-Unique-Upload-Id` and
   `Content-Range: bytes start-end/total`. In mock mode, simulate progress.
8. **Live updates:** `src/lib/events.ts` opens `GET /v1/events/stream` using **fetch streaming** (not
   `EventSource`, because it must send the Authorization header), parses SSE blocks, reconnects with
   backoff, and invalidates TanStack queries. Events:
   - `asset.state_changed` → `{asset_id, project_id, state, reason}`
   - `before_after.updated` → `{pair_id, project_id}`
   Mocks emit fake state transitions after an upload.
9. **Report HTML** from the API is shown inside a sandboxed `<iframe srcDoc>`. Never restyle or
   parse it: it must stay byte-exact, because it is cryptographically verified.
10. **Auth abstraction** in `src/auth/`: `getToken()`, `useSession()`, `signOut()`. Dev mode stores a
    persona `{user, org, role}` in localStorage, and the token is the string `dev.<user>.<org>.<role>`.
    Personas:
    - Asha · Programme manager: `asha/jalseva/manager`
    - Ravi · Field contributor: `ravi/jalseva/contributor`
    - Meera · Evidence reviewer: `meera/jalseva/reviewer`
    - Donor · Viewer: `donor/jalseva/viewer`
    - Kiran · Another organisation: `kiran/greenroots/admin`

    Keep the provider swappable (a real OIDC provider, Clerk, will replace it later).
11. Query keys live in one object in `hooks.ts`, e.g. `keys.assets(projectId)`, `keys.asset(id)`,
    `keys.claims(projectId)`, `keys.report(id)`.
12. Role rules come from `me.role` (rank viewer < contributor < reviewer < manager < admin), via a
    helper `hasRole(role, needed)`. Hide or disable actions the user can't do, with a tooltip saying
    why.

## 6. API endpoints (implement all in endpoints.ts plus mocks; build UI for the ones marked ★)

Identity and projects
- ★ `GET /v1/me` → MeOut (`features` flags include `demo_mode`, `cloudinary`, `webhooks`, `gemini`, `groq`)
- `GET /v1/taxonomy-presets`
- ★ `GET /v1/projects` → ProjectOut[] · ★ `POST /v1/projects` `{name, taxonomy_preset:"water_infrastructure"}`
- ★ `GET /v1/projects/{id}` · `PATCH /v1/projects/{id}`
- ★ `GET/POST /v1/projects/{id}/sites` → SiteOut · `PATCH /v1/sites/{id}`
- `GET/PUT /v1/projects/{id}/taxonomy`

Media
- ★ `POST /v1/uploads/sign` · ★ `POST /v1/assets/{id}/confirm`
- ★ `GET /v1/projects/{id}/assets?state&site_id&resource_type&cursor&limit` → `{items: AssetSummary[], next_cursor}`
- ★ `GET /v1/assets/{id}` → AssetDetail · ★ `GET /v1/assets/{id}/lineage` → LineageOut
- ★ `GET /v1/assets/{id}/media?variant=thumb|review|original|stream|clip&start_ms&end_ms` → MediaUrlOut
- `GET /v1/assets/{id}/chapters.vtt` (video chapters, text) · `POST /v1/assets/{id}/reanalyze`

Search
- ★ `POST /v1/search` `{project_id, query, filters?, limit?, use_llm_planner?}` → SearchResponse
- ★ `POST /v1/search/similar` `{asset_id, limit}` · `POST /v1/search/{query_id}/feedback` `{asset_id, action: click|add_to_evidence|dismiss, rank}`

Review
- ★ `GET /v1/projects/{id}/review-queue` → QueueItem[]
- ★ `POST /v1/assets/{id}/review` `{decisions:[{observation_id, decision: approve|reject|edit, edit?}], complete, note}`
- `POST /v1/assets/{id}/observations` (add a human observation) · `GET /v1/assets/{id}/reviews`

Claims and metrics
- ★ `GET/POST /v1/projects/{id}/metrics` · ★ `GET/POST /v1/projects/{id}/claims`
- ★ `GET /v1/claims/{id}` → ClaimDetail · `PATCH /v1/claims/{id}`
- ★ `POST /v1/claims/{id}/evidence` `{asset_id, observation_id?, relation: supports|contradicts|context, note?}` · `DELETE /v1/claims/{id}/evidence/{link_id}`
- ★ `PUT|DELETE /v1/claims/{id}/metrics/{metric_id}`
- ★ `POST /v1/claims/{id}/validate` | `submit` | `approve` | `reject` | `retract` (body `{note?, override?}`)
- ★ `GET /v1/claims/{id}/graph` → EvidenceGraph (draw it as a node graph)
- `GET/POST /v1/projects/{id}/events` · `GET /v1/projects/{id}/events/suggestions`

Reports
- ★ `GET/POST /v1/projects/{id}/reports` `{title, period_start?, period_end?, audience: internal|external, claim_ids?}`
- ★ `GET /v1/reports/{id}` → ReportDetail · `PATCH /v1/reports/{id}`
- ★ `POST /v1/reports/{id}/generate` · `PUT /v1/reports/{id}/narrative` · ★ `GET /v1/reports/{id}/preview` → `{html, manifest_sha256, problems}`
- ★ `POST /v1/reports/{id}/publish` → SnapshotOut · ★ `GET /v1/reports/{id}/snapshots`
- ★ `GET /v1/reports/{id}/snapshots/{v}/html` · ★ `.../verify` → SnapshotVerification · ★ `GET .../pdf` → `{url, expires_at}` · `POST .../pdf` (retry) · `GET .../manifest`

Before / after
- ★ `POST /v1/projects/{id}/before-after/suggest` · ★ `GET /v1/projects/{id}/before-after` → PairSummary[] · `POST /v1/projects/{id}/before-after`
- ★ `GET /v1/before-after/{id}` → PairDetail · `POST .../analyze` · ★ `POST .../confirm` · `POST .../reject` (body `{note?}`)

Campaigns, sharing, analytics, map
- ★ `GET/POST /v1/projects/{id}/campaigns` → CampaignOut · `GET /v1/campaigns/{id}` · `POST /v1/projects/{id}/campaigns/video-reel`
- ★ `GET/POST /v1/projects/{id}/share-links` · `DELETE /v1/share-links/{id}` · ★ `GET /v1/share/{token}` (public, no auth)
- ★ `GET /v1/projects/{id}/analytics` → ProjectAnalyticsOut · ★ `GET /v1/projects/{id}/spatial-temporal` → SpatialTemporalOut
- `GET /v1/audit?target_type&target_id&limit`

Demo mode (one-click versions; all real on the backend)
- ★ `POST /v1/demo/assets/{asset_id}/claim` `{claim_type:"descriptive", statement?}` → DemoClaimOut
- ★ `POST /v1/demo/claims/{claim_id}/approve` → DemoClaimOut
- ★ `POST /v1/demo/projects/{project_id}/report` `{audience:"internal", title?}` → DemoReportOut

## 7. Types (put these in `src/api/types.ts` exactly; `?` = optional; dates are ISO strings)

```ts
export type Role = "viewer" | "contributor" | "reviewer" | "manager" | "admin";
export type AssetState = "awaiting_upload" | "uploaded" | "registered" | "metadata_ready" | "dedup_checked"
  | "analyzing" | "indexed" | "review_required" | "ready" | "expired" | "failed_retryable" | "failed_permanent";
export type ResourceType = "image" | "video";
export type ProvenanceSource = "exif" | "device" | "user" | "upload" | "site" | "none";
export type OntologyType = "scene" | "activity" | "object" | "condition" | "people" | "document_text" | "quality" | "sensitive";
export type ObservationStatus = "proposed" | "verified" | "rejected" | "superseded";
export type ClaimType = "descriptive" | "progress" | "outcome" | "metric";
export type ClaimStatus = "draft" | "in_review" | "approved" | "rejected" | "retracted";
export type SupportLevel = "unsupported" | "proposed" | "reviewed" | "verified";
export type ValidationVerdict = "supported" | "partially_supported" | "not_supported" | "not_checked";
export type MetricSource = "field_survey" | "sensor" | "operational_record" | "third_party" | "visual_count";
export type ReportAudience = "internal" | "external";
export type PdfStatus = "pending" | "ready" | "failed" | "skipped";

export interface MeOut { user: { id: string; email: string | null; display_name: string | null };
  organization: { id: string; name: string; slug: string | null }; role: Role; auth_mode: string;
  cloudinary_cloud_name: string | null; features: Record<string, boolean> }
export interface ProjectOut { id: string; name: string; description: string | null; status: string;
  starts_on: string | null; ends_on: string | null; taxonomy_preset: string; active_taxonomy_version: number;
  created_at: string; stats?: { assets_total: number; by_state: Record<string, number>; sites: number } | null }
export interface SiteOut { id: string; project_id: string; name: string; code: string; description: string | null;
  latitude: number | null; longitude: number | null; radius_m: number; created_at: string }
export interface UploadSignResponse { asset_id: string; resource_type: ResourceType; upload_url: string;
  fields: Record<string, string>; chunk_size: number; expires_at: number }
export interface AssetSummary { id: string; project_id: string; site_id: string | null; resource_type: ResourceType;
  state: AssetState; state_reason: string | null; original_filename: string | null; format: string | null;
  bytes: number | null; width: number | null; height: number | null; duration_seconds: number | null;
  capture_time: string | null; capture_time_source: ProvenanceSource; location_source: ProvenanceSource;
  declared_activity: string | null; caption: string | null; top_activity: string | null;
  top_activity_confidence: number | null; review_priority: number | null; flags: Record<string, unknown> | null;
  exact_duplicate_of_id: string | null; created_at: string; thumb_url?: string | null }
export interface ObservationOut { id: string; ontology_type: OntologyType; subject: string; predicate: string;
  value: Record<string, unknown> | null; confidence: number | null; evidence_span: Record<string, unknown> | null;
  source_kind: "ai" | "human" | "system"; source_provider: string | null; status: ObservationStatus;
  review_priority: number | null; analysis_run_id: string | null; generation: number; created_at: string }
export interface AnalysisRunOut { id: string; task: string; provider: string; model: string; prompt_version: string | null;
  status: "running" | "succeeded" | "failed"; error: string | null; latency_ms: number | null; created_at: string }
export interface DerivativeOut { id: string; purpose: string; named_transformation: string | null;
  transformation: string; format: string | null; source: string; generative: boolean; created_at: string }
export interface AssetDetail extends AssetSummary { latitude: number | null; longitude: number | null;
  sha256: string | null; quality_score: number | null; review_reasons: string[] | null;
  near_duplicates: { asset_id: string; distance: number }[]; cloudinary: Record<string, unknown>;
  observations: ObservationOut[]; analysis_runs: AnalysisRunOut[]; derivatives: DerivativeOut[];
  contributor_note: string | null; uploaded_at: string | null }
export interface MediaUrlOut { url: string; variant: string; transformation: string;
  named_transformation: string | null; format: string | null; expires_at: number | null }
export interface SearchResult { asset: AssetSummary; score: number; reasons: string[];
  matched_observations: { id: string; ontology_type: string; subject: string; predicate: string; confidence: number | null; status: string }[];
  video_span?: { start_ms: number; end_ms: number; label: string } | null; missing_terms?: string[] }
export interface SearchResponse { query_id: string; results: SearchResult[]; took_ms: number;
  plan: { semantic_text?: string; planner?: string; warnings?: string[]; filters?: Record<string, unknown> };
  retrievers: Record<string, { hits?: number; ms?: number; error?: string }>;
  query_terms?: string[]; complete_matches?: number }
export interface QueueItem { asset: AssetSummary; pending_observations: number; review_reasons: string[] }
export interface MetricOut { id: string; project_id: string; site_id: string | null; name: string; value: string;
  unit: string | null; method: string; source_type: MetricSource; source_reference: string;
  period_start: string | null; period_end: string | null; created_at: string }
export interface EvidenceLinkOut { id: string; asset_id: string; observation_id: string | null; pair_id?: string | null;
  relation: "supports" | "contradicts" | "context"; note: string | null; created_at: string; verified?: boolean;
  observation_summary?: string | null; asset_caption?: string | null; thumb_url?: string | null }
export interface ClaimOut { id: string; project_id: string; site_id: string | null; statement: string;
  claim_type: ClaimType; status: ClaimStatus; support_level: SupportLevel; period_start: string | null;
  period_end: string | null; rule_check: { passed: boolean; problems: string[]; unsourced_numbers: string[] } | null;
  validation: { verdict?: string; reasoning?: string; reason?: string; model?: string; provider?: string } | null;
  validation_verdict: ValidationVerdict | null; created_by_id: string | null; decided_by_id: string | null;
  decided_at: string | null; decision_note: string | null; created_at: string; updated_at: string }
export interface ClaimDetail extends ClaimOut { evidence: EvidenceLinkOut[]; metrics: MetricOut[] }
export interface EvidenceGraph { nodes: { id: string; type: string; label: string; data: Record<string, unknown> }[];
  edges: { source: string; target: string; relation: string }[] }
export interface SnapshotOut { id: string; report_id: string; version: number; manifest_sha256: string;
  html_sha256: string; renderer_version: string; published_by_id: string | null; published_at: string;
  pdf_status: PdfStatus; pdf_bytes: number | null; pdf_error: string | null; retracted_claim_ids?: string[] }
export interface ReportOut { id: string; project_id: string; site_id: string | null; title: string;
  audience: ReportAudience; period_start: string | null; period_end: string | null; status: "draft" | "published";
  latest_version: number; claim_ids: string[]; published_at: string | null; created_at: string }
export interface ReportClaim { id: string; statement: string; claim_type: ClaimType; status: ClaimStatus; support_level: SupportLevel }
export type Narrative = Record<"summary" | "overview", { text: string; cites: { type: "claim" | "metric"; id: string }[] }[]>;
export interface ReportDetail extends ReportOut { narrative: Narrative | null;
  narrative_meta: { mode?: string; provider?: string; model?: string; edited_by?: string | null;
    rejected?: { section: string; text: string; problems: string[] }[] } | null;
  narrative_problems: { section: string; index: number; text: string; problems: string[] }[];
  claims: ReportClaim[]; candidate_claims: ReportClaim[]; snapshots: SnapshotOut[]; warnings: string[] }
export interface SnapshotVerification { version: number; manifest_sha256: string; recomputed_manifest_sha256: string;
  html_sha256: string; recomputed_html_sha256: string; identical: boolean }
export interface PairPhoto { id: string; original_filename: string | null; caption: string | null;
  capture_time: string | null; capture_time_source: ProvenanceSource; site_id: string | null;
  width: number | null; height: number | null; thumb_url: string | null }
export interface PairSummary { id: string; project_id: string; site_id: string | null; status: string;
  before: PairPhoto; after: PairPhoto;
  similarity: number | null; distance_m: number | null; days_apart: number | null; rank_score: number;
  alignment_grade: "strong" | "partial" | "none" | null; change_summary: string | null;
  changed_share: number | null; green_delta_pp: number | null; limitation_count: number; created_at: string }
export interface PairDetail extends PairSummary { alignment: Record<string, unknown> | null;
  changes: Record<string, unknown> | null; limitations: string[]; before_url: string | null;
  after_url: string | null; composite_url: string | null; composite_transformation: string | null;
  public_composite_url: string | null; decision_note: string | null }
export interface CampaignOut { id: string; project_id: string; title: string; headline: string;
  stat_text: string | null; brand_tag: string | null; asset_id: string; pair_id: string | null;
  claim_id: string | null; formats: string[]; generative: boolean;
  renditions: Record<string, { format: string; url: string; transformation: string;
    named_transformation: string | null; generative: boolean; purpose: string }>; created_at: string }
export interface ShareLinkOut { id: string; project_id: string; token: string; title: string;
  target_type: "report" | "evidence" | "campaign"; target_id: string; share_url: string;
  expires_at: string; view_count: number; is_revoked: boolean; created_at: string }
export interface DemoClaimOut { claim: ClaimDetail; approved: boolean; reviewed_observations: number;
  linked_evidence: number; validation_verdict: ValidationVerdict | null; reviewer: string; steps: string[]; message?: string | null }
export interface DemoReportOut { report_id: string; snapshot: SnapshotOut; claims: number;
  narrative_mode: string | null; sentences: number; rejected_sentences: number; steps: string[] }
// Analytics, spatial and lineage: model them as documented objects and render defensively.
export type ProjectAnalyticsOut = { project_id: string; ingestion: Record<string, unknown>;
  costs: Record<string, unknown>; verification: Record<string, unknown>; activities: Record<string, unknown>[] };
export type SpatialTemporalOut = { project_id: string; total_geotagged: number; points: Record<string, unknown>[];
  sites: Record<string, unknown>[]; timeline: Record<string, unknown>[]; bounds: Record<string, unknown> };
```

## 8. Business rules the UI (and the mocks) must show

- Only **approved claims** can go into reports. Claims need a verified observation, or a reviewed photo,
  as evidence. **Any number in a claim must match a linked metric**, otherwise it is blocked with
  "Numbers without a linked sourced metric: 9".
- **Four-eyes rule:** the author of a claim cannot approve it. Disable **Approve** when
  `claim.created_by_id === me.user.id`, with a tooltip explaining why.
- Claim workflow: draft → (validate, submit) → in_review → approve/reject → approved (frozen) →
  retract (manager, needs a note). Reject and retract need a note.
- AI observations start as `proposed`; a reviewer makes them `verified` or `rejected`. Show AI output in
  info-blue and human-verified in green, so the difference is always visible.
- Published report versions are **immutable**. Show a lock icon, the manifest hash, a "Verify" button
  and a PDF status that polls every 2 s while `pending`.
- External audience = faces pixelated; never show precise GPS to viewers.
- Search can return partial matches: show `missing_terms` as struck-through words, plus a banner
  when `complete_matches === 0`.

## 9. File structure (keep these paths)

```
src/
  main.tsx, App.tsx, routes.tsx          # all routes here
  styles/tokens.css, styles/globals.css  # design tokens (light + dark)
  api/ client.ts endpoints.ts hooks.ts types.ts index.ts mock/{data.ts, handlers.ts}
  auth/ session.ts personas.ts AuthProvider.tsx RequireAuth.tsx
  lib/ upload.ts events.ts format.ts (dates, bytes, hashes) roles.ts utils.ts
  components/
    ui/            # shadcn primitives
    brand/         # Logo, ProvenanceChain, CitationChip, HashChip, VerifiedSeal, StatusChip
    layout/        # AppShell, Sidebar, Topbar, ThemeToggle, PersonaSwitcher, PageHeader
    landing/       # Hero(parallax), StoryScroller(pinned), Stats, FeatureGrid, CloudinaryMarquee, CTA
    media/         # AssetCard, AssetGrid, AssetViewer, VideoPlayer, ObservationList, LineagePanel
    upload/        # Dropzone, UploadQueue
    search/        # SearchBar, ResultCard, WhyThisResult
    review/        # ReviewQueueItem, ObservationDecision
    claims/        # ClaimCard, ClaimWorkflowBar, EvidencePicker, MetricForm, EvidenceGraphView
    reports/       # ReportStudio, NarrativeEditor, SnapshotTable, ReportFrame, VerifyDialog
    beforeafter/   # PairCard, ComparisonSlider
    campaigns/     # CampaignStudio, FormatPreview
    share/         # ShareDialog
    demo/          # DemoStepper and its 4 steps
  pages/           # one file per route below; thin, composition only
```

## 10. Pages (same URLs as below; they map 1:1 onto the real app)

Public:
- `/`: **Landing page.** Hero with parallax, the pinned 5-step scroll story, "why trust it" (four-eyes,
  cited sentences, frozen reports), Cloudinary features, stats, and a CTA "Start the demo".
- `/sign-in`: a big **Start demo** card (signs in as Asha and goes to `/demo`), then the persona list
  "Or sign in as a team member (full workflow)".
- `/share/:token`: public read-only shared report, evidence or campaign (no auth), with a lineage view.

App (inside AppShell; sidebar lists the projects and, inside a project: **Demo mode**, Overview, Upload,
Media, Map & Timeline, Search, Review queue, Before/after, Claims, Reports, Campaign Studio, Analytics):
- `/projects`: project cards with stats; create a project.
- `/demo`: choose a project for the demo → `/projects/:projectId/demo`.
- `/projects/:projectId/demo`: **the most important screen.** A 4-step guided stepper with progress rail:
  1. Upload (live status). 2. Search in plain English. 3. Photo grid; each card has **Make claim** →
  shows `steps[]` as an animated checklist and the approved claim. 4. **Generate & publish report** →
  steps checklist, PDF status, **View report** (iframe), **Verify** (seal animation), **Download PDF**.
  Explain in one line that approvals are made by a separate "Demo reviewer" (four-eyes still holds).
- `/projects/:projectId`: overview: stats, sites (create), state distribution, recent activity.
- `/projects/:projectId/upload`: dropzone plus live upload queue (site, activity and note fields).
- `/projects/:projectId/media`: masonry grid, state filters, infinite scroll (cursor).
- `/assets/:assetId`: large viewer (video player with chapters for videos), AI caption, observations
  grouped by type with confidence bars, provenance (capture time and source, GPS source), duplicates,
  **Lineage** drawer (original → named transformations → derivatives, all in mono), review controls for
  reviewers, "Find similar".
- `/projects/:projectId/map`: MapLibre map of geotagged points and sites plus a timeline scrubber.
- `/projects/:projectId/search`: search bar, result cards with thumbnails, "why", missing words, video spans.
- `/projects/:projectId/review`: queue sorted by priority; approve or reject each observation; complete review.
- `/projects/:projectId/claims`: claims table (status and support chips) plus metrics list and form.
- `/claims/:claimId`: workflow bar (validate · submit · approve · reject · retract, role-aware, note
  field), rule-check panel, AI validation verdict, linked evidence with thumbnails, evidence picker
  (search a photo → choose a verified observation → Link), metric checkboxes, **evidence graph**.
- `/projects/:projectId/reports` and `/reports/:reportId`: **Report Studio**: included and candidate
  claims, Generate, narrative with citation chips (hover highlights the claim), rejected sentences,
  warnings, Preview (iframe), Publish, versions table (hash, PDF status, verify, download, retry).
- `/projects/:projectId/before-after` and `/before-after/:pairId`: find pairs (site, date windows),
  pair cards, comparison slider, change stats, limitations list, confirm or reject.
- `/projects/:projectId/campaigns`: pick approved evidence → formats (1:1, 4:5, 9:16, 16:9) → preview
  grid; mark AI-enhanced outputs as "illustrative".
- `/projects/:projectId/analytics`: KPI tiles with count-up, state distribution, verification
  progress, AI latency and cost charts.

Every page has: a skeleton loading state, an empty state with a friendly illustration and one clear
action, and an error state that shows `ApiError.message` plus a retry button.

## 11. Mock data (make the demo feel real)

One organisation "Jalseva"; projects "Community Water Access" and "Sewer maintenance"; sites "Village
A" and "Rampura"; about 12 assets with captions like "A man is manually cleaning sludge from an open
manhole on a street", with observations (manhole 95%, shovel 95%, pipe_installation 80%), a mix of
proposed and verified; 3 claims (draft, in_review, approved); 1 metric (Manholes cleaned = 4,
operational_record); 1 published report with 2 versions; 2 before/after pairs; 1 campaign. Mock uploads
walk through the states over about 6 s. Mock demo endpoints return realistic `steps[]`.

=== END PROMPT 1 ===

---

=== PROMPT 2 (after Prompt 1 works) ===

Polish pass. Keep the integration contract intact (don't touch `src/api/types.ts` names or
`endpoints.ts` paths).
1. Landing: refine the parallax depth, and add the "scan" animation on hero photos (bounding box plus
   label drawing on). Make the pinned story section draw the provenance-chain line on scroll. Add
   subtle grain or noise texture and a radial accent glow behind the hero.
2. Add a command palette (Cmd+K) for pages, projects and recent assets.
3. Report Studio: when hovering a citation chip, draw a connector line to the claim card and pulse its
   evidence thumbnails. Publish triggers the "freeze" animation, then the new version row slides in.
4. Asset page: the observation list animates confidence bars on mount; the lineage drawer shows the
   transformation chain as connected mono chips.
5. Check every page at 360 px, 768 px and 1440 px, in both themes, with reduced motion on. Fix contrast
   and layout issues.

=== END PROMPT 2 ===

---

=== PROMPT 3 (final check before handing the code back) ===

Audit the code against the integration contract and fix any violations:
- No `fetch` outside `src/api/` and `src/lib/{upload,events}.ts`.
- Every endpoint in section 6 exists in `endpoints.ts` with the exact method and path, and a mock twin.
- Types match section 7 exactly (snake_case field names, same type names).
- No hard-coded Cloudinary URLs; every media URL comes from the API response.
- `VITE_USE_MOCKS=false` makes the app call `VITE_API_BASE_URL` with `Authorization: Bearer dev.<user>.<org>.<role>`.
- The report HTML is only ever shown in `<iframe srcDoc>`, unchanged.
- Add a README listing the environment variables, the folder structure and how to run it.

=== END PROMPT 3 ===
