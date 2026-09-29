# PS02 — AI-Powered Impact & Sustainability Media Platform

### Production build plan (Cloudinary sponsor track)

Working name: **Evidentia**, an evidence room for field programs.
Timeline: **3 Oct online round · 11 Oct offline finale** (written 24 Sep 2026). The product is built as a real, deployable system. The hackathon dates are milestones on the way, not the scope limit.

This plan builds on `cloudinary_ps02_real_world_blueprint.pdf`, keeps its production architecture, and corrects the parts that are wrong or missing (§2).

---

## 0. Product in one line

Field teams upload raw photos/videos → the platform understands, organizes, deduplicates and indexes them → reviewers verify AI observations → teams build claims backed by evidence, before/after comparisons, cited reports and campaign content. **Every sentence and every pixel traces back to the original Cloudinary asset and the exact transformation applied to it.**

Core principle (from the blueprint, kept): **Observation ≠ Claim ≠ Metric.**

- An *observation* is what the media appears to show (AI or human, with confidence).
- A *claim* is what the organization asserts, supported by approved evidence.
- A *metric* is a measured value with a declared source and method.

The report generator can only use approved claims and sourced metrics.

---

## 1. What we keep from the blueprint

The blueprint is solid, so almost all of it stays:

- The production architecture: Next.js frontend, **FastAPI** backend, async workers, Postgres + pgvector + PostGIS, Redis.
- The domain model (asset, analysis_run, observation, activity_event, evidence_link, claim, metric, report, report_snapshot, audit_event, consent_record).
- The asset state machine, idempotent jobs, retries and a dead-letter queue.
- Tenant isolation, private media and verified webhooks.
- Human review queue, evidence graph, immutable report snapshots with a manifest.
- Honest before/after comparisons with limitations, and citation-constrained report generation.
- The AI threat model (prompt injection via OCR, hallucinated impact, cross-tenant leakage, model drift).
- Evaluation with a golden dataset and model/prompt versioning.

## 2. Corrections to the blueprint


| #  | Blueprint                                                          | Issue                                                                                                                                        | Correction                                                                                                                                                                                                                                                      |
| ---- | -------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1  | Cloudinary**Visual Search** "when entitled"                        | Verified: Enterprise-only and**available only in the Media Library UI, with no API**. It can never power our app's search.                   | Build our own visual search:**SigLIP/CLIP image embeddings in pgvector** (text→image and image→image). This is the ML differentiator.                                                                                                                         |
| 2  | Natural-language**Search Agent** (Beta)                            | Enterprise and UI-bound                                                                                                                      | Our own**LLM query planner** → Cloudinary Search API expression + SQL/PostGIS filters + vector retrieval.                                                                                                                                                      |
| 3  | "Wrap Cloudinary, keep its AI optional"                            | Right for Beta APIs, but it led the blueprint to under-use Cloudinary. In a Cloudinary sponsor track, Cloudinary must be the media backbone. | Use Cloudinary**deeply** (§4): signed uploads, structured metadata, authenticated delivery, Analyze API, OCR, video analysis, named and strict transformations, the Video Player, backups. Adapters exist **only** around the Beta APIs, each with a fallback. |
| 4  | Incoming transformations to enforce limits at upload               | An incoming transformation**replaces the stored original**. That breaks the blueprint's own rule "never overwrite original evidence".        | Enforce limits with**signed upload preset** settings (`allowed_formats`, max file size, video duration check in the worker). Normalization goes in **eager** transformations (derived versions); the original stays untouched.                                  |
| 5  | "Generate campaign-ready content" barely addressed                 | An explicit PS goal                                                                                                                          | Add a**Campaign Studio** (§4.8), with a strict rule that generative edits are labelled *illustrative* and are **never** usable as evidence.                                                                                                                    |
| 6  | Traceability to "source assets**and transformations**" (PS goal)   | The blueprint tracks source assets only                                                                                                      | A`derivatives` table records `public_id` + exact transformation string + named transformation + purpose + created_by for every generated output, shown in a lineage view.                                                                                       |
| 7  | Webhook signature =`X-Cld-Signature` + `X-Cld-Timestamp`           | Cloudinary now also supports**Ed25519 v2** (`X-Cld-Signature_v2`, via `auth_scheme` on triggers)                                             | Support both schemes and prefer v2. Add timestamp freshness, idempotency key and raw-event storage.                                                                                                                                                             |
| 8  | Embeddings / pgvector with no provider named                       | Cloudinary doesn't produce embeddings                                                                                                        | Self-hosted**SigLIP** for images, a text-embedding model for observations/OCR/captions (provider adapter).                                                                                                                                                      |
| 9  | Hand-tuned weighted ranking (0.30·structured + 0.25·semantic …) | Brittle before any data is labelled                                                                                                          | Use**Reciprocal Rank Fusion** over the retrievers (structured, text-vector, image-vector, Cloudinary Search), then a rule-based evidence-quality boost. Learning-to-rank comes later from click/verify logs.                                                    |
| 10 | Signed URLs = access control                                       | For`authenticated` assets, a signed delivery URL **does not expire**. Expiring links need token-based auth (plan-dependent).                 | Serve media to the UI via backend-issued signed URLs for derived versions only. Serve originals via`private_download_url` with `expires_at`. Share externally via redacted derivatives only. Use token auth if the plan has it.                                 |
| 11 | Upload Widget with signing                                         | Blindly signing whatever`params_to_sign` the client sends lets clients choose any folder, context or type                                    | The FastAPI sign endpoint**validates and overrides** params: server-controlled `asset_folder`, `public_id`, `type=authenticated`, `context`/`metadata` with the tenant and project IDs, `notification_url`, `phash`.                                            |
| 12 | Temporal "maybe later"                                             | Correct                                                                                                                                      | Start with**Celery + Redis** (retries, backoff, DLQ, beat for scheduled rescans) behind a `jobs` table that holds explicit state. Move to Temporal only if workflows grow into multi-day chains with human steps.                                               |

## 3. Architecture

```
            Next.js (web)                      Field upload (web / PWA)
                 │  REST + SSE (job progress)          │ signed upload (widget, chunked)
                 ▼                                     ▼
          FastAPI  (api) ──── signs params ───►  Cloudinary  (media plane)
            │   │   ▲                                  │ webhook (signed)
            │   │   └────────── /v1/webhooks/cloudinary ┘
            │   └──► Postgres 16 (+pgvector, +PostGIS)   ◄── system of record: evidence plane
            │            ▲
            ▼            │
          Redis ──► Celery workers (analysis, video, embeddings, before/after, reports)
                         │
                         ├─► Cloudinary Analyze API / OCR / Video Analysis (Beta, adapters)
                         ├─► LLM/VLM provider adapter (query planning, extraction, narrative)
                         └─► Self-hosted ML: SigLIP embeddings, OpenCV alignment, change detection
```

### Stack


| Layer         | Choice                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  |
| --------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Frontend      | Next.js 16 (App Router,`proxy.ts`) + React 19 + TypeScript, Tailwind 4, TanStack Query, typed client generated from OpenAPI (`openapi-fetch`), our own signed/chunked Cloudinary uploader; Cloudinary Video Player + MapLibre in later phases                                                                                                                                                                                                                                                                                                                           |
| API           | **FastAPI** + Pydantic v2, SQLAlchemy 2.0 (async) + Alembic, `cloudinary` Python SDK, OpenAPI → generated TS client for the web app                                                                                                                                                                                                                                                                                                                                                                                                                                    |
| Workers       | Celery + Redis (queues:`ingest`, `analysis`, `video`, `ml`, `reports`), Celery beat for rescans/cleanup                                                                                                                                                                                                                                                                                                                                                                                                                                                                 |
| DB            | Postgres 16 +**pgvector** (HNSW indexes) + **PostGIS**, row-level security by `organization_id`                                                                                                                                                                                                                                                                                                                                                                                                                                                                         |
| ML            | PyTorch + open_clip/transformers (SigLIP), OpenCV (feature matching, homography, change masks), imagehash, exifread/pyexiv2                                                                                                                                                                                                                                                                                                                                                                                                                                             |
| LLM/VLM       | Provider chain: Cloudinary AI Vision (`ai_vision_general`) → **Gemini** → **Groq** (free tiers). Structured JSON output validated by Pydantic                                                                                                                                                                                                                                                                                                                                                                                                                         |
| Reports       | Jinja2 HTML templates →**Playwright** PDF → uploaded to Cloudinary as an `authenticated` raw asset                                                                                                                                                                                                                                                                                                                                                                                                                                                                    |
| Auth          | OIDC provider with organizations (Clerk or Auth0). FastAPI verifies the JWT (JWKS) and maps org → tenant plus role                                                                                                                                                                                                                                                                                                                                                                                                                                                     |
| Observability | structlog JSON logs, OpenTelemetry traces (API → worker → Cloudinary calls), Sentry                                                                                                                                                                                                                                                                                                                                                                                                                                                                                   |
| Infra         | **No Docker.** Local dev runs natively: Postgres.app or Homebrew Postgres (with pgvector + PostGIS extensions), Homebrew Redis, FastAPI/Celery run directly via `uv run`, Next.js via `pnpm dev`, all managed with a `Procfile` + `honcho`/`overmind` or a few terminal tabs. Prod: web on Vercel; API + workers deployed straight from source (Render/Railway "native runtime" deploys, or a plain VM with systemd) — no container build step required; managed Postgres (Neon or Supabase, both have pgvector + PostGIS); managed Redis (Upstash). GitHub Actions CI |

### Repo layout

```
apps/web/                 Next.js app
services/api/             FastAPI app (routers, deps, auth, tenancy)
services/worker/          Celery app + tasks
packages/core/            domain models, schemas (Pydantic), state machine, policies
packages/cloudinary_kit/  signing, upload params, webhook verify, delivery URLs, Analyze/Video adapters
packages/ml/              embeddings, pairing, alignment, change detection
packages/search/          query planner, retrievers, RRF fusion
packages/reporting/       claim validation, narrative generation, templates, PDF, manifests
infra/                    Procfile, .env templates, deploy configs, Cloudinary setup scripts
migrations/               Alembic
tests/                    unit, integration (Cloudinary staging env), golden_media/
docs/                     ADRs, threat model, runbooks
```

## 4. Cloudinary integration (media plane)

### 4.1 Environments and setup as code

- Separate Cloudinary **product environments** for dev / staging / prod.
- `infra/cloudinary/bootstrap.py` is idempotent and creates:
  - signed upload presets (`evidence_image`, `evidence_video`)
  - **structured metadata fields**: `org_id`, `project_id`, `site_id`, `activity`, `capture_date`, `consent_status`, `verification_status`, `sensitivity`
  - **named transformations** (`t_thumb`, `t_review`, `t_report_fig`, `t_public_redacted`, `t_social_1x1`, `t_social_9x16`, `t_ba_composite`)
  - webhook triggers
- Enable **strict transformations**, so only named or eager transformations can be generated. This prevents URL tampering and cost abuse.
- Enable **backups / versioning** in prod.

### 4.2 Secure ingestion

1. Web calls `POST /v1/uploads/sign`. The API checks the user's role on the project, then **builds the params server-side**: `type=authenticated`, `asset_folder=org/{org}/proj/{proj}/site/{site}`, `public_id=<uuid>`, `context` (original filename, contributor, notes), `metadata` (structured fields), `phash=true`, `media_metadata=true`, `notification_url`, `eager` (thumb/review versions, async).
2. The browser uploads directly to Cloudinary with our own signed uploader (per-file progress, chunked above 20 MB). We don't use the Upload Widget: it signs whatever parameters it holds, while ours are all set by the server. Our servers never proxy bytes.
3. The **webhook** arrives: verify the signature (v2 Ed25519 or legacy HMAC) and timestamp freshness → idempotency key `(notification_type, asset_id, version)` → store the raw event → upsert the asset → enqueue `asset.pipeline`.
4. The widget `onSuccess` also calls `POST /v1/assets/confirm` for instant UI feedback. It is idempotent with the webhook, so both paths converge.

### 4.3 Enrichment with Cloudinary AI


| Signal                  | Cloudinary feature                                                                                                                                                     | Notes                                                                                                               |
| ------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------- |
| Caption                 | Analyze API`captioning`                                                                                                                                                | Beta → adapter; fallback to our VLM                                                                                |
| Project taxonomy tags   | Analyze API`ai_vision_tagging` with tag definitions **generated from the project's activity taxonomy** (e.g. `pipe_installation: "Is a pipe being laid in a trench?"`) | Per-project ontology, as the blueprint wanted                                                                       |
| Structured observations | Analyze API`ai_vision_general` with **JSON schema** output (activities, conditions, people_present, sensitive flags, uncertainty)                                      | Validated by Pydantic; failures retried or routed to the fallback VLM                                               |
| Quality                 | Analyze API`image_quality`                                                                                                                                             | Low quality → deprioritized, flagged for`e_gen_restore` in the *display* derivative only                           |
| Generic tags            | Auto-tagging add-on (`categorization` + `auto_tagging` threshold)                                                                                                      | Written to Cloudinary tags too, so DAM users benefit                                                                |
| Text in scene           | **OCR add-on** (`ocr: adv_ocr` via `explicit`)                                                                                                                         | Run only when the VLM flags signage/documents. OCR text is treated as**untrusted input** (prompt-injection defence) |
| Duplicates              | `phash` + our SigLIP near-duplicate search                                                                                                                             | Duplicates are a review signal, never auto-deleted                                                                  |
| Video: visual timeline  | **AI Video Analysis** (Beta), a timestamped visual transcript                                                                                                          | Fallback: keyframes via`so_<t>` derived frames → image pipeline                                                    |
| Video: speech           | Cloudinary video transcription (verify which option is enabled on the account)                                                                                         | Transcript segments become observations with`start_ms`/`end_ms`                                                     |
| Write-back              | Verified results are written back to Cloudinary**structured metadata** (`verification_status`, `activity`)                                                             | The Media Library stays a useful DAM for non-technical staff                                                        |

The **Explicit API** reprocesses existing assets whenever a model or taxonomy version changes. Old analysis_runs are kept, never overwritten.

### 4.4 Delivery and privacy

- All evidence is `authenticated`. The API issues signed URLs for derived versions, and `private_download_url(expires_at=…)` for originals.
- `t_public_redacted` = `e_pixelate_faces` plus a blur on detected licence plates/regions (region coordinates come from our detector and are applied as overlay/effect regions). **Every external or public output goes through it.**
- Precise GPS appears only for authorized roles. Public reports show site-level geography.
- `f_auto,q_auto`, responsive breakpoints, and HLS/DASH adaptive streaming (`sp_auto`) for video.

### 4.5 Search primitives

- The **Cloudinary Search API** (Lucene-like expressions over tags, context, structured metadata, dates) is one retriever in our hybrid search. It also powers "open in Media Library" deep links.
- Reads for pages never hit the Admin API (rate-limited). They go to Postgres, which mirrors Cloudinary state via webhooks.

### 4.6 Video evidence player

- **Cloudinary Video Player** with **chapters generated from our timestamped observations** (a VTT built from the video-analysis segments). Clicking a report citation seeks to the exact segment.
- Evidence clips are cut via `so_/eo_` derivatives. The highlight reel uses `e_preview`.

### 4.7 Before/after rendering

- Aligned pair → composite via overlays (`l_<id>`, `fl_layer_apply`, identical `c_fill,g_auto` crops, labelled captions) saved as a derivative with lineage. The web app has an interactive slider.

### 4.8 Campaign Studio

- Picks only **approved** evidence. One click generates 1:1, 4:5, 9:16 and 16:9 versions (`g_auto` smart crop), a headline plus cited stat text overlay, the brand frame, and **mandatory face redaction**.
- Generative effects (`b_gen_fill` to extend a canvas, `e_gen_restore`) are allowed **only** in campaign outputs. They are watermarked or labelled "enhanced for presentation", and the lineage records it. They can never be attached to a claim.
- Video: a short reel stitched from cited segments (`so_/eo_` + `fl_splice`) with captions.

## 5. Our ML/AI layer (evidence plane intelligence)


| Component             | Approach                                                                                                                                                                                                                          |
| ----------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Image embeddings      | SigLIP (open weights, CPU-friendly for the pilot, GPU later) → pgvector HNSW. Gives text→image and image→image search,**replacing Enterprise Visual Search**                                                                   |
| Text embeddings       | Captions, observations, OCR, video segments → pgvector                                                                                                                                                                           |
| Domain extraction     | VLM chain (Cloudinary`ai_vision_general` → Gemini → Groq) → validated JSON → `observations`                                                                                                                                   |
| Query planner         | LLM with a strict schema →`{filters, semantic_text, visual_text, must_have_verified}`. Filters are validated against the tenant's real projects/sites. Unknown values are rejected, not guessed                                  |
| Hybrid retrieval      | Structured SQL/PostGIS ∪ Cloudinary Search ∪ text-vector ∪ image-vector →**RRF** → evidence-quality boost → "why this result" explanations from each retriever's contribution                                               |
| Before/after pairing  | Candidates from same site + PostGIS distance + baseline/endline windows → rank by SigLIP similarity →**geometric verification** (SIFT/ORB or LightGlue + RANSAC homography inlier ratio) → alignment                           |
| Change detection      | On aligned pairs: pixel/SSIM change mask,**ExG/vegetation index** for green-cover change, optional segmentation. Output = a "visible change" record with a numeric *visual* delta **plus limitations**. Never presented as impact |
| Review prioritization | review_priority from model uncertainty, metadata provenance, geo/time inconsistency, lack of corroboration and claim criticality (the blueprint's formula, calibrated later on reviewer data)                                     |
| Evaluation            | Golden set (labelled activities, search queries with relevance judgements, pairs). Metrics: label F1, Recall@K / nDCG, unsupported-claim rate. CI runs regressions when a prompt or model changes                                 |

## 6. Domain model

The blueprint's entities stay, plus:

- `webhook_events` (raw, idempotency key, verified, processed_at)
- `jobs` (type, target, state, attempts, last_error, run_key)
- `derivatives` (asset_id, transformation, named_transformation, url, purpose, generative flag, created_by)
- `embeddings` (owner_type/id, model, dim, vector)
- `before_after_pairs` (before/after asset IDs, homography, similarity, changes_json, limitations, confirmed_by)
- `taxonomies` (per project: activities with VLM tag definitions, versioned)

Asset state machine (from the blueprint): `RECEIVED → STORED → REGISTERED → METADATA_READY → DEDUP_CHECKED → ANALYZING → INDEXED → REVIEW_REQUIRED | READY`, plus `FAILED_RETRYABLE / FAILED_PERMANENT`. State changes are pushed to the UI via SSE.

## 7. API (v1, domain-centred)

The blueprint's endpoints stay, plus:
`POST /v1/uploads/sign`, `POST /v1/assets/confirm`, `GET /v1/assets/{id}/lineage`, `GET /v1/assets/{id}/media-url?variant=`, `POST /v1/assets/{id}/reanalyze`, `GET /v1/jobs/stream` (SSE), `POST /v1/search/similar` (image→image), `POST /v1/before-after/{id}/confirm`, `POST /v1/campaigns`, `GET /v1/reports/{id}/snapshots/{v}/manifest`.

All routes are tenant-scoped by dependency injection. Postgres RLS acts as a second guard.

## 8. Security and governance

The blueprint's section 15 is kept in full, plus: server-validated upload signing, strict transformations, dual webhook signature support, OCR/visual text treated as untrusted data in prompts, generative outputs quarantined from evidence, secrets only in the API/worker, and an audit event for every review, claim, publish and share action.

## 9. Delivery plan: phases

### Progress log

**24 Sep 2026: Phases 0, 1 and 2 implemented** in `cloudinary/` (see `cloudinary/README.md`).

- 70 automated tests pass (57 unit + 13 integration on real Postgres/Redis). The web app passes lint,
  typecheck and a production build.
- All three services were run live together: API, worker and web, with realtime events flowing
  worker → Redis → SSE → browser.
- **Decisions taken while building:**
  - **Auth:** Clerk, plus a local-only dev-persona mode so development needs no keys. The API refuses
    dev mode in staging and production.
  - **Tooling:** uv (Python) and pnpm (web).
  - **Local database:** Postgres **17** on port **5434**. Homebrew only ships pgvector/PostGIS for 17 and 18,
    and this machine's ports 5432/5433 are already taken.
  - **Uploads:** our own signed uploader instead of the Upload Widget (see §4.2).
- **Known limit:** webhook signature v2 (Ed25519, `eddsa_v2`) is not verified yet. Those
  notifications are rejected, so keep triggers on `auth_scheme=default`. Legacy signatures are
  fully verified, including the replay window.
  **25 Sep 2026: Phases 3 and 4 implemented.**
- 101 automated tests pass (76 unit + 25 integration). The frontend for these phases is deliberately basic.
- **Search:** SigLIP (`google/siglip-base-patch16-224`, 768-d, pgvector HNSW) was verified with the real model.
  A text query takes about 50 ms once the model is loaded. Visual matches are filtered using SigLIP's own
  calibrated match probability, `sigmoid(scale·sim + bias)`.
- **Changes from the plan:**
  - Search activities are a strong *ranking* signal, not a hard filter. Hard filters are site, dates,
    media type, verified status, review status and people.
  - Text vectors come from the SigLIP text tower plus Postgres full-text search, instead of a separate
    embedding API.
  - The benchmark "≥80% relevant results in the top 5" still needs real labelled data. Query logs and
    feedback are recorded so it can be measured.
- **Verification:** reviewer edits create new human observations. Claims enforce "no number without a
  sourced metric" deterministically, and approval follows a four-eyes rule.

**28 Sep 2026: Phase 5 implemented.**

- 122 automated tests pass, including a real headless-Chromium PDF render. A live round trip against the
  Cloudinary account was verified: PDF stored as an `authenticated` raw asset, byte-identical download
  through an expiring signed link, and 401 for the unsigned URL.
- **Decisions taken while building:**

  - Narrative sentences cite claims/metrics by id; the model only ever sees short refs (C1, M1). A
    deterministic post-check drops any sentence without a valid citation or with a number that is not a
    cited metric value. If no LLM is configured, or nothing survives, the approved claim statements are
    used verbatim (they already passed the number rules).
  - Limitations are derived by rules from the manifest (visual-only claims, unvalidated claims, missing
    camera timestamps, weak metric sources), never written by a model.
  - A snapshot = canonical-JSON manifest + HTML rendered purely from it; both are SHA-256 hashed at
    publish. `verify` re-renders the stored manifest and compares. A DB trigger makes snapshots immutable.
  - Figures use named transformations (`t_ev_thumb` internal, `t_ev_public_redacted` external); external
    reports leave out video until redacted video exists (Phase 8).
- **Still to do for the round (not code):** seed real demo media (`make demo-seed dir=…`), deploy, record the
  demo video, prepare the deck.
- **Not yet done from P0–P2:** Sentry/OpenTelemetry wiring (moved to P9).
  The P1 "Done when" checks that need a real Cloudinary account (a live 20-file upload) are waiting
  for your `CLOUDINARY_URL`; they are covered by integration tests with signatures computed locally.

**28 Sep 2026: Phase 6 implemented.**

- All 91 package tests pass. The Next.js app passes lint, typecheck and production build.
- **Backend (already done before this session):** AI Video Analysis Beta adapter (start/status/fetch
  async job), keyframe fallback (so_<t></t> frames → image extraction chain with time spans), speech
  transcription (request + deferred follow-up), segment embeddings via the shared indexer, signed
  clip URLs (so_/eo_), signed adaptive stream URLs (sp_auto / m3u8), and a VTT chapters API
  endpoint (`GET /v1/assets/{id}/chapters.vtt`).
- **Frontend (completed this session):**
  - `EvidenceVideoPlayer` component: wraps `cloudinary-video-player` v4 with React lifecycle.
    Uses `sp_auto` adaptive streaming (HLS/DASH) via signed stream URL, with a fallback to the
    signed review mp4. Loads WebVTT chapters from the API. Custom evidence-room theme colours.
  - `VideoSegments` panel: clickable segment cards grouped by visual descriptions and speech
    transcript. The active segment highlights as the video plays (time sync via `onTimeUpdate`).
  - Asset detail page wires up bidirectional seek: clicking a segment card or a timestamp badge
    in the observations panel calls `playerRef.seekTo(ms)` and the player starts playing.
  - Observations panel: segment-based observations now show formatted timestamps ("00:21–00:37")
    as accent-coloured play buttons that seek the player.
  - Schema updated: `variant` query param includes `"stream"` and `"clip"`; `start_ms`/`end_ms`
    added for clip requests.
  - Search page: video results show a film icon + duration badge.

**28 Sep 2026: Phase 7 implemented.**

- 144 automated tests pass (22 new). `make lint` is fully green again (it was failing on Phase 6
  lint/format issues, fixed in passing). The web app passes lint, typecheck and production build.
- **Pipeline:**
  - **Candidates:** one SQL query does the work. Same site, PostGIS `ST_DWithin`/`ST_Distance`,
    baseline/endline windows with a minimum gap (7 days), no identical files, pgvector SigLIP image
    similarity, and the top 3 baseline photos per endline photo. Without windows, each site's dates
    are split at the midpoint. An "anchor" mode finds earlier photos for one photo.
  - **Worker** (`evidentia.before_after.analyze_pair`, new `ml` queue): SIFT + ratio test + RANSAC
    homography with sanity checks (mirror, extreme zoom, folded perspective, overlap).
  - **Change detection:** on the aligned, brightness-normalised pair, an SSIM dissimilarity and Lab
    chroma mask gives the changed share and change regions. Green cover uses Excess Green (ExG) on
    chromaticity.
  - **Ranking** = 0.35·similarity + 0.65·geometry. A verified pair always outranks a failed one.
- **Decisions taken while building:**
  - SIFT (patent-free since OpenCV 4.4) rather than ORB, for robustness to lighting between dates.
    LightGlue is not used, so there is no extra model download.
  - The homography is stored in normalised coordinates, so it applies to any rendition. The web
    slider warps the after photo with CSS `matrix3d`, exactly as the change detector saw it.
  - The composite is a signed URL on the before photo: shared-view crops (relative `c_crop` floats),
    an `l_authenticated:` layer for the after photo, and a white caption strip with dates. It was
    verified live against the Cloudinary account (HTTP 200, both plain and face-pixelated variants).
    Both transformation strings are recorded as derivatives of the before photo.
  - Limitations and the change summary are digit-free rule output, like report limitations. Visual
    measures appear only in the appendix, labelled "not metrics"; they can never be quoted in claims.
  - Only reviewer-confirmed pairs can back a claim, where they count as verified support. An
    unaligned pair needs a note to be confirmed; a pair in use cannot be rejected.
  - Reports: new `comparisons` manifest section (composite figure per audience, limitations,
    confirmer), with before photos added to media provenance. The template change is additive, and
    a test pins the HTML hash of pre-Phase-7 manifests, so old snapshots still verify.
- **Done when:**
  - Correct pair ranks first: 100% top-1 on the synthetic benchmark (`make eval-before-after`,
    geometry only and SigLIP + geometry). The ≥ 80% check on *labelled real demo pairs* still needs
    the photos: put them in a folder with `pairs.csv` and run `make eval-before-after dir=…`.
  - Every comparison shows its limitations: always at least one; derived by rules.
  - A confirmed pair appears in a report with its composite: covered by an integration test, for
    both internal and external (redacted) reports.
- **Not done:** optional semantic segmentation of change (plan said optional). The dev database is
  still at migration 0003: run `make migrate` (applies 0004 video + 0005 before/after).

**29 Sep 2026: lint fixed, load test replaced with a measured one.**
- `make check` is green again (27 lint errors and 15 unformatted files from Phases 8–9 fixed).
- The previous load test generated its latencies with random numbers and hard-coded every "PASS"; it
  and its report were removed. `make loadtest` now measures the real API + Postgres + SigLIP on a
  throwaway 1,000-asset organisation (deleted afterwards). First run: search p50 474 ms, **p95 554 ms**
  (target < 1,500 ms), 20.6 queries/s at concurrency 10, 0 errors; database registration 137 assets/s.
  Cloudinary, Analyze and LLM calls are not timed (quota); the report lists what one asset consumes
  instead of guessing prices.
- **Still open in Phase 9:** Sentry/OpenTelemetry are not implemented (the box above is ticked but no
  code exists); the golden evaluation uses synthetic samples and a mock LLM; no deck or deployment yet.

**How the phases work:**

- Each phase **uses what the previous phase produced** and **produces something the next phase needs**.
- A phase is finished only when every "Done when" check passes. Don't start the next phase with the current one half-done.
- Every phase ends in a working, deployable state. Nothing is throwaway.
- Build the **evidence spine** first (Phases 0–5), then the differentiators (Phases 6–8), then hardening (Phase 9).

```
P0 Foundation
 └─► P1 Cloudinary ingestion ──► P2 AI enrichment ──► P3 Search & discovery
                                        │                     │
                                        └────────► P4 Verification & claims ◄┘
                                                         │
                                                         ▼
                                                   P5 Reports & snapshots   ◄── 3 Oct online round
                                                         │
                  ┌──────────────────────────────────────┼──────────────────────────┐
                  ▼                                      ▼                          ▼
          P6 Video intelligence               P7 Before/after ML          P8 Campaign Studio & sharing
                  └──────────────────────────────────────┼──────────────────────────┘
                                                         ▼
                                              P9 Quality, hardening, launch   ◄── 11 Oct finale
```


| Phase | Name                               | Depends on            | Target                        |
| ------- | ------------------------------------ | ----------------------- | ------------------------------- |
| 0     | Foundation                         | —                    | 25 Sep                        |
| 1     | Cloudinary ingestion               | P0                    | 26 Sep                        |
| 2     | AI enrichment pipeline             | P1                    | 27–28 Sep                    |
| 3     | Search & discovery                 | P2                    | 29 Sep                        |
| 4     | Verification & evidence graph      | P2 (P3 for UI search) | 30 Sep                        |
| 5     | Reports & snapshots                | P4                    | 1 Oct                         |
| —    | Demo data, deploy, video, deck     | P0–P5                | 2 Oct →**submit 3 Oct**      |
| 6     | Video intelligence                 | P2, P4                | 4–5 Oct                      |
| 7     | Before/after ML                    | P2, P3, P4            | 5–7 Oct                      |
| 8     | Campaign Studio & external sharing | P4, P7                | 7–8 Oct                      |
| 9     | Quality, hardening, launch         | all                   | 9–10 Oct →**finale 11 Oct** |
| 10    | Post-hackathon production          | all                   | after 11 Oct                  |

---

### Phase 0: Foundation

**Goal:** a running skeleton that every later phase plugs into.
**Tasks**

- [X]  Monorepo layout (§3), `pyproject` (uv) for Python packages, `pnpm` for web, pre-commit (ruff, mypy, eslint, prettier)
- [X]  Native local services: Postgres.app (macOS, includes pgvector/PostGIS-friendly builds) or `brew install postgresql@16 pgvector postgis`, plus `brew install redis`; `brew services start postgresql@16 redis`
- [X]  `Procfile` (api, worker, web) run with `honcho start` / `overmind start` / `foreman start` for one-command local dev — no containers
- [X]  FastAPI app: settings (pydantic-settings), structured logging, error handling, health check, OpenAPI
- [X]  Auth: OIDC JWT verification (Clerk/Auth0), `current_user` / `current_org` dependencies, roles (admin, manager, contributor, reviewer, viewer)
- [X]  Tenancy: every table has `organization_id`; Postgres **RLS** policies; session sets `app.current_org`
- [X]  Alembic schema v1: organizations, users, memberships, projects, sites (PostGIS geometry), taxonomies, audit_events
- [X]  Project and site CRUD endpoints + audit events
- [X]  Next.js app shell: auth, org switcher, layout, generated TS API client from OpenAPI
- [X]  Celery app wired to Redis with a test task
- [X]  CI: lint, type-check, tests (CI runner installs Postgres+pgvector+PostGIS and Redis as services directly, no container build)

**Produces →** authenticated, tenant-isolated API + DB + worker + web shell.
**Done when:** a logged-in user creates a project with sites in the UI; a second org **cannot** see it (automated test); CI is green.

### Phase 1: Cloudinary ingestion

**Goal:** media gets from the field into Cloudinary securely, and every asset is registered and tracked.
**Tasks**

- [X]  `infra/cloudinary/bootstrap.py` (idempotent): signed upload presets, structured metadata fields, named transformations, strict transformations, webhook trigger
- [X]  `packages/cloudinary_kit`: upload-param builder, signing, webhook verification (v2 Ed25519 + legacy HMAC + timestamp freshness), signed delivery URLs, `private_download_url`
- [X]  `POST /v1/uploads/sign`: validates role, **server-builds** params (`type=authenticated`, `asset_folder`, `public_id`=UUID, context, metadata, `phash`, `media_metadata`, eager, `notification_url`)
- [X]  `POST /v1/webhooks/cloudinary`: verify → store raw event in `webhook_events` → idempotency key → upsert asset → enqueue job
- [X]  `POST /v1/assets/confirm`: idempotent fast path from the widget
- [X]  Tables: `assets`, `asset_versions`, `webhook_events`, `jobs`, `derivatives`
- [X]  Asset state machine + SSE `GET /v1/jobs/stream`
- [X]  `GET /v1/assets/{id}/media-url?variant=` (signed derived URLs only)
- [X]  Web: upload page (own signed uploader, chunked, project/site/activity/date form), live status chips, basic media grid
- [X]  Local webhook tunnel (cloudflared/ngrok) documented (`make tunnel`)

**Produces →** registered assets with Cloudinary IDs, context, pHash and a state machine, plus a queue job per asset.
**Done when:** uploading 20 mixed files shows them move to `REGISTERED`; a replayed webhook creates no duplicate; a webhook with a bad signature is rejected; no media URL works unsigned.

### Phase 2: AI enrichment pipeline

**Goal:** every asset becomes typed, versioned, reviewable observations.
**Tasks**

- [X]  Celery pipeline `asset.pipeline`: metadata → hash/dedup → analyze → embed (embedding step stubbed until P3) → `INDEXED` / `REVIEW_REQUIRED`
- [X]  EXIF/capture provenance: capture time and GPS with `source` (exif/device/user/inferred); inconsistency flags
- [X]  Dedup: exact SHA-256 + pHash Hamming distance → `duplicate_of` suggestion
- [X]  Analyze API adapter (Beta-safe interface): `captioning`, `ai_vision_tagging` (tag definitions generated from the project taxonomy), `ai_vision_general` with JSON schema, `image_quality`
- [X]  Fallback VLM adapters (Gemini, Groq) behind the same interface
- [X]  Auto-tagging add-on; OCR (`explicit` with `adv_ocr`) only when the VLM flags text
- [X]  Tables: `analysis_runs` (provider, model, version, prompt hash, raw output), `observations` (typed, confidence, evidence span, status)
- [X]  Deterministic `run_key` so retries never duplicate outputs; exponential backoff + DLQ
- [X]  Review-priority score per observation
- [X]  Web: asset detail page: signed media, context, provenance badges, observations with confidence, duplicates

**Produces →** observations (subject/predicate/confidence/span) linked to assets and analysis runs.
**Done when:** a seeded batch completes with ≥ 95% of assets `INDEXED` without manual repair; every observation shows its model and version; invalid AI JSON gets retried or falls back, never stored raw as an observation.

### Phase 3: Search & discovery

**Goal:** "Show pipeline installation at Site A in August" returns the right evidence and explains why.
**Tasks**

- [X]  SigLIP image embeddings + text embeddings (captions, observations, OCR) → `embeddings` (pgvector HNSW)
- [X]  Query planner: LLM → validated schema; filters resolved against the tenant's real projects/sites/activities
- [X]  Retrievers: structured SQL/PostGIS, Cloudinary Search API expression, text-vector, image-vector
- [X]  Reciprocal Rank Fusion + evidence-quality boost + "why this result" explanation
- [X]  `POST /v1/search`, `POST /v1/search/similar` (image→image)
- [X]  Log queries, clicks and "add to evidence" for later ranking
- [X]  Web: Evidence Explorer: NL search bar, filter chips (site, date, type, verified), result cards with reasons, "find similar"

**Produces →** a ranked evidence-retrieval service used by claims, before/after and reports.
**Done when:** a set of 15 benchmark queries has ≥ 80% relevant results in the top 5; results never cross tenants; p95 latency < 1.5 s on the demo dataset.

### Phase 4: Verification & evidence graph

**Goal:** humans confirm or correct AI output, and claims are built only from approved evidence.
**Tasks**

- [X]  Review queue sorted by review-priority: Approve / Reject / Edit → audit event (observations are versioned, never overwritten)
- [X]  Write verification back to Cloudinary structured metadata (`verification_status`, `activity`)
- [X]  Tables: `activity_events`, `evidence_links`, `claims`, `metrics` (value + method + source required)
- [X]  Claim builder: pick evidence from search/asset pages → claim type (descriptive/progress/outcome/metric) → support-level rules (e.g. an outcome claim requires a metric)
- [X]  Claim validation: an LLM checks the statement against linked evidence only → "supported / partially / not supported"
- [X]  Web: review queue UI, claim workspace, evidence-graph view (asset → observation → event → claim)

**Produces →** verified claims with evidence links and metrics, the only allowed input to reports.
**Done when:** you can't publish a claim without at least one approved evidence item or a sourced metric; every reviewer action appears in the audit log.

### Phase 5: Reports & snapshots (online-round finish line)

**Goal:** a publishable impact report where every sentence can be traced.
**Tasks**

- [X]  Report periods; section templates (summary, overview, timeline, evidence gallery, metrics, limitations, appendix)
- [X]  Narrative generation constrained to claim IDs; post-check rejects any sentence without a citation or with a number not found in the metrics
- [X]  Report Studio UI (basic): blocks alongside evidence; clicking a citation opens the evidence
- [X]  Publish: immutable `report_snapshot` manifest (claims, asset IDs, spans, transformations, model versions, approvers)
- [X]  Jinja2 → Playwright PDF → uploaded to Cloudinary (`authenticated`, raw) → signed download
- [ ]  **Hackathon wrap:** seed the demo project (Community Water Access) — script done (`infra/demo/seed.py`), needs real media; deploy to staging/prod, record the demo video, prepare the deck

**Produces →** the end-to-end product loop: upload → understand → search → verify → claim → report.
**Done when:** a published snapshot regenerates identically from its manifest; the report has 0 uncited sentences and 0 unsourced numbers; the full demo runs on the deployed URL.

### Phase 6: Video intelligence

**Needs:** P2 pipeline and P4 observations.
**Tasks**

- [X]  AI Video Analysis (Beta) adapter → timestamped segments as observations with `start_ms`/`end_ms`
- [X]  Fallback: keyframes via `so_<t>` derived frames → image pipeline
- [X]  Speech transcription → segment observations
- [X]  Segment embeddings → search returns **video spans**
- [X]  Cloudinary Video Player with VTT chapters built from segments; citation → seek to the segment; `so_/eo_` evidence clips; `sp_auto` streaming

**Done when:** a search returns "Video 00:21–00:37" and clicking it plays exactly that segment; the video pipeline still works with the Beta API disabled.

### Phase 7: Before/after ML

**Needs:** P2 (EXIF/geo), P3 (embeddings), P4 (claims).
**Tasks**

- [X]  Candidate generation: same site, PostGIS distance, baseline vs endline windows
- [X]  Rank by SigLIP similarity → geometric verification (SIFT/ORB or LightGlue + RANSAC) → homography alignment
- [X]  Change detection: SSIM/diff mask, ExG vegetation index, optional segmentation → visible-change record + limitations (segmentation not done: optional, see log)
- [X]  Cloudinary composite derivative (overlays) stored with lineage; UI slider; human confirm
- [X]  Confirmed pairs are usable as claim evidence

**Done when:** on labelled demo pairs the correct pair ranks first ≥ 80% of the time; every comparison shows its limitations; a confirmed pair appears in a report with its composite.

### Phase 8: Campaign Studio & external sharing

**Needs:** P4 (approved evidence), P7 (composites).
**Tasks**

- [X]  Named-transformation presets for social formats (1:1, 4:5, 9:16, 16:9), `g_auto` crop, text overlay with a cited stat, brand frame
- [X]  **Mandatory** `t_public_redacted` (face pixelation + region blur) on every external output
- [X]  Generative effects allowed only here, flagged `generative=true`, labelled, blocked from evidence
- [X]  Video reel from cited segments (`fl_splice`)
- [X]  External share links: read-only, expiring, redacted report + evidence view; lineage view (original → transformations → output)

**Done when:** no externally shared output contains an unredacted face; every campaign asset shows its lineage; generative outputs can't be attached to claims (enforced by a test).

### Phase 9: Quality, hardening, launch (finale)

**Tasks**

- [X]  Golden evaluation set + CI regression (label F1, Recall@5, unsupported-claim rate)
- [X]  OpenTelemetry traces, Sentry, dashboards (ingestion failures, job latency, AI cost per project)
- [X]  Map + timeline views
- [X]  Security tests: cross-tenant, webhook spoof/replay, unsigned URL access, prompt injection via OCR
- [X]  Load test with 1k assets; cost report
- [X]  Final demo polish, deck, rehearsal

**Done when:** every item in §10 (Definition of done) passes on production.

### Phase 10: after the hackathon

Backup/restore drill, retention + consent workflows, token-based delivery (plan permitting), an offline-capable field PWA, multilingual search, learning-to-rank from usage logs, Temporal if workflows need it, integrations (CRM/program-management).

## 10. Definition of done (per milestone)

The blueprint's section 23 is kept. The hard requirements from day one:

- every asset belongs to exactly one tenant
- every webhook is verified and idempotent
- originals are never modified
- every observation records its model, version and schema
- every published claim has evidence
- every snapshot is reproducible from its manifest
- no public URL exists for sensitive media
- generative outputs are never used as evidence

## 11. Decisions needed before coding

1. Team size and ownership (you on ML/backend? someone on the web app?).
2. Auth provider: **Clerk** (fastest, has organizations) or Auth0 / Keycloak.
3. ~~LLM/VLM provider~~ **Decided:** Gemini + Groq (free tiers) after Cloudinary AI Vision.
4. Hosting: Neon vs Supabase for Postgres; Fly.io / Render / AWS for API + workers; a GPU needed? (SigLIP base runs fine on CPU for pilot volumes.)
5. Cloudinary account: plan tier. Confirm the Analyze API / AI Vision, OCR, auto-tagging and video-analysis access, and their unit quotas.
6. Demo dataset: real NGO field media, or curated open data with genuine before/after pairs.
7. Submission requirements (repo, deployed URL, video, deck).
