# Evidentia · developer guide

**AI-powered impact & sustainability evidence platform, built on Cloudinary.**
Field teams upload raw photos and videos. Evidentia stores them privately in Cloudinary, extracts
provenance, detects duplicates and uses AI to produce typed, versioned *observations* that humans verify.
Later phases turn verified evidence into claims, before/after comparisons, reports and campaign content,
all traceable back to the original pixel and the exact transformation applied to it.

> Problem statement: PS02 "AI-Powered Impact & Sustainability Media Platform" (Cloudinary track).
> Product and build plan: [`../PLAN.md`](../PLAN.md).

---

## Status

| Phase | What | State |
|---|---|---|
| 0 | Foundation: monorepo, FastAPI, Postgres (RLS) + pgvector + PostGIS, Redis/Celery, auth, tenancy, audit, Next.js shell, CI | ✅ done |
| 1 | Cloudinary ingestion: server-signed direct uploads (chunked), upload-signature + webhook verification, idempotent claim, asset registry, state machine, live progress (SSE), signed delivery | ✅ done |
| 2 | AI enrichment: EXIF provenance, SHA-256 + pHash dedup, Cloudinary Analyze API (captioning, quality, AI Vision tagging), structured extraction chain (Cloudinary AI Vision → Gemini → Groq), OCR/auto-tagging add-ons, review priority, Cloudinary write-back | ✅ done |
| 3 | Search: natural-language query planner (rules + optional Gemini/Groq, validated), 6 retrievers (filters, activity, Postgres full-text, SigLIP text-vector, SigLIP text→image visual, Cloudinary Search API), Reciprocal Rank Fusion + evidence-quality boost, "why this result", image→image similar search, query/feedback logging | ✅ done |
| 4 | Verification & evidence graph: review queue, approve/reject/edit (versioned, audited), human observations, claims with deterministic evidence rules + LLM validation, metrics with declared sources, four-eyes approval, activity events + suggestions, evidence graph API, Cloudinary write-back of verified status | ✅ done |
| 5 | Reports & snapshots: report drafts from approved claims, narrative (Gemini/Groq or deterministic fallback) where every sentence must cite a claim/metric and every number must match a cited metric, derived limitations, immutable hashed snapshots (manifest + HTML, DB-enforced), verify-by-re-render, Playwright PDF stored privately in Cloudinary with expiring links, demo seed script | ✅ done |
| 6 | Video intelligence: AI Video Analysis (Beta) with keyframe fallback, speech transcription, segment embeddings (search returns video spans), Cloudinary Video Player with VTT chapters, `so_/eo_` clips, `sp_auto` streaming | ✅ done |
| 7 | Before/after: candidates by site + PostGIS distance + baseline/endline windows + pgvector SigLIP similarity, SIFT/RANSAC geometric verification and homography alignment, SSIM/chroma change mask + Excess-Green vegetation index, rule-derived limitations, signed Cloudinary composite (authenticated layer) with lineage, aligned web slider, human confirm, pairs as claim evidence and report figures | ✅ done |
| 8+ | Campaign studio & external sharing, hardening | next |

Tests: **144 passing** (unit + integration against real Postgres/Redis, plus a real headless-Chromium PDF render). Web: lint, typecheck and production build pass.
The frontend for Phases 3–5 is intentionally basic (functional screens); styling comes later.

---

## Architecture

```
 Browser (Next.js 16)                                        Cloudinary (media plane)
   │  1. POST /v1/uploads/sign  ──►  FastAPI  ── builds + signs every upload param
   │  2. upload bytes directly  ─────────────────────────────►  authenticated asset, eager renditions
   │  3. POST /v1/assets/{id}/confirm (Cloudinary's response signature verified)
   │                                   ▲                              │ upload webhook (signed)
   │                                   └──── /v1/webhooks/cloudinary ◄┘
   │                                   │  whichever arrives first "claims" the asset (atomic UPDATE)
   │  SSE /v1/events/stream  ◄── Redis pub/sub ◄── Celery worker: register → provenance → dedup
   │                                                               → AI enrichment → finalize
   ▼                                   Postgres 17: RLS per organisation, pgvector, PostGIS
```

**Principles in the code**
- **Observation ≠ claim.** AI output is stored as typed observations with confidence, provider, model,
  prompt version, schema version and taxonomy version. It is never a report sentence.
- **Private by default.** Every asset is `type=authenticated`. The UI only gets signed renditions of
  named transformations, and originals only through expiring download links (and each access is audited).
- **Server decides upload parameters.** The browser uploads directly, but the folder, public_id,
  delivery type, context and tags are chosen and signed by the API.
- **Idempotent everywhere.** Webhooks are deduplicated by key, analysis runs by deterministic `run_key`,
  and the pipeline resumes from the asset's state after a crash or retry.
- **Tenant isolation in the database.** Postgres row-level security (`FORCE`d) plus a non-superuser app
  role; the test suite proves one organisation cannot read another's rows.
- **Beta APIs never block the pipeline.** Cloudinary Analyze / AI Vision are used first. If they're
  unavailable, Gemini or Groq take over, and the result is validated against the same Pydantic schema.

---

## Folder structure

```
cloudinary/
├── apps/web/                      Next.js 16 + React 19 + Tailwind 4 (App Router)
│   └── src/
│       ├── app/                   routes: sign-in, projects, project overview/upload/media, asset detail
│       ├── components/            ui/ (design system) · layout/ · projects/ · uploads/ · assets/
│       ├── lib/api/               typed client generated from FastAPI's OpenAPI + React Query hooks
│       ├── lib/auth/              Clerk or local dev identities behind one interface
│       ├── lib/upload/            direct signed + chunked upload to Cloudinary
│       ├── lib/events/            SSE live pipeline updates
│       └── proxy.ts               Next 16 proxy (Clerk route protection)
├── services/
│   ├── api/                       FastAPI: auth/ · routers/ · schemas/ · services/ (business logic)
│   └── worker/                    Celery: pipeline/ (one module per step) · tasks/
├── packages/
│   ├── core/                      settings, domain rules (state machine, taxonomy, review priority,
│   │                              media policy), SQLAlchemy models, RLS-aware sessions, events
│   ├── cloudinary_kit/            everything Cloudinary: signing, webhooks, delivery, Admin + Analyze
│   │                              API clients, named transformations, EXIF parsing, account bootstrap
│   ├── ai/                        extraction schema, versioned prompts, provider adapters
│   │                              (Cloudinary AI Vision, Gemini, Groq, mock), parsing, normalisation,
│   │                              query planner, claim validator, report narrative writer
│   ├── ml/                        SigLIP embeddings; before/after alignment + change detection (OpenCV)
│   └── reporting/                 manifest -> HTML (Jinja2, pure/deterministic) -> PDF (Playwright)
├── migrations/                    Alembic (schema + row-level security policies)
├── infra/
│   ├── local/setup.sh             native macOS setup (no Docker)
│   ├── cloudinary/bootstrap.py    configure the Cloudinary account as code
│   ├── demo/seed.py               upload a folder of demo media through the real pipeline
│   └── eval/before_after_eval.py  pairing benchmark on labelled before/after photos
├── .github/workflows/ci.yml       lint, tests (native Postgres/Redis), web build
├── Makefile · Procfile · .env.example
```

---

## Getting started (macOS, no Docker)

**Prerequisites:** Homebrew, Python 3.12+, [uv](https://docs.astral.sh/uv/), Node 20+, pnpm.

```bash
make setup     # Postgres 17 on :5434 (+pgvector, PostGIS), Redis, deps, Chromium, migrations, .env files
make dev       # API :8000, worker, beat, web :3000
```
Open http://localhost:3000 and pick a persona (local dev auth). Everything except uploading works without
any keys. For uploads and AI, add the keys below to `.env`.

> Port 5434 is used because this machine already runs other Postgres servers on 5432/5433.
> Override with `EVIDENTIA_PG_PORT` when running `infra/local/setup.sh`, and update `DATABASE_URL`.

### Demo mode (for presentations)
On the sign-in page click **Start demo** (or **Demo mode** at the top of a project's sidebar). One page,
one click per step: upload → search → **Make claim** from a photo → **Generate & publish report** → view,
verify, download the PDF. Every call is real (Cloudinary, AI, database, PDF worker). The only shortcut is
who approves: a separate **Demo reviewer** account in your organisation, so the four-eyes rule and the
audit trail still hold, and a claim the AI validator rejects is left in review. The full multi-person
workflow is unchanged on the other pages. Turn it off with `DEMO_MODE_ENABLED=false`.
API: `POST /v1/demo/assets/{id}/claim`, `POST /v1/demo/claims/{id}/approve`, `POST /v1/demo/projects/{id}/report`.

### Keys you need

| Key | Where to get it | Needed for |
|---|---|---|
| `CLOUDINARY_URL` | Cloudinary Console → Settings → API Keys (`cloudinary://key:secret@cloud`) | uploads, delivery, AI |
| Cloudinary add-ons | Console → Settings → Add-ons: register free tiers of **AI Vision / Analyze API**, **OCR Text Detection** (optional), an **auto-tagging** add-on (optional) | Cloudinary-native AI |
| `GEMINI_API_KEY` | https://aistudio.google.com → Get API key | AI fallback #1 (free tier) |
| `GROQ_API_KEY` | https://console.groq.com → API Keys | AI fallback #2 (free tier) |
| (same Gemini/Groq keys) | – | search query planning + claim validation (text LLM) |
| `PUBLIC_API_BASE_URL` | `make tunnel` (cloudflared) → paste the `https://…trycloudflare.com` URL | Cloudinary webhooks locally |
| Clerk keys (optional) | https://clerk.com → app → enable Organizations → API Keys | real sign-in (`AUTH_MODE=clerk`) |

After setting `CLOUDINARY_URL`, configure the account once:
```bash
make cloudinary-bootstrap                               # named transformations + signed presets
make cloudinary-bootstrap args=--structured-metadata    # optional: metadata fields
```
Then, in the Cloudinary Console, enable **Settings → Security → Strict transformations** (the named ones
are pre-approved).

### Common commands
```bash
make test          # all Python tests
make lint          # ruff + eslint + tsc
make api-types     # regenerate the web's typed client after API changes
make migration m="describe change"
make playwright    # headless Chromium for report PDFs (already done by make setup)
make demo-seed dir=demo-media   # upload demo photos/videos; sub-folders become sites
make eval-before-after dir=demo-pairs   # pairing benchmark (folder with pairs.csv: before,after)
```

---

## API overview (v1)

| Method | Path | Role | Purpose |
|---|---|---|---|
| GET | `/v1/me` | viewer | identity, organisation, role, feature flags |
| GET/POST | `/v1/projects` | viewer / manager | list (with stats) / create (with taxonomy v1) |
| GET/PATCH | `/v1/projects/{id}` | viewer / manager | |
| GET/POST | `/v1/projects/{id}/sites` | viewer / manager | sites with coordinates + radius (PostGIS) |
| GET/PUT | `/v1/projects/{id}/taxonomy` | viewer / manager | versioned activity taxonomy |
| POST | `/v1/uploads/sign` | contributor | register upload intent, return signed Cloudinary params |
| POST | `/v1/assets/{id}/confirm` | contributor | verify Cloudinary's upload signature, start pipeline |
| GET | `/v1/projects/{id}/assets` | viewer | cursor-paginated media with signed thumbnails |
| GET | `/v1/assets/{id}` | viewer | observations, runs, provenance, duplicates, lineage |
| GET | `/v1/assets/{id}/media?variant=` | viewer | signed rendition / expiring original (audited) |
| POST | `/v1/assets/{id}/reanalyze` | reviewer | new analysis generation, history kept |
| POST | `/v1/search` | viewer | hybrid natural-language evidence search (plan + reasons) |
| POST | `/v1/search/similar` | viewer | image → image similar evidence |
| POST | `/v1/search/{query_id}/feedback` | viewer | click / add-to-evidence / dismiss logging |
| GET | `/v1/projects/{id}/review-queue` | reviewer | assets needing a human, by priority |
| POST | `/v1/assets/{id}/review` | reviewer | approve / reject / edit observations, complete review |
| POST | `/v1/assets/{id}/observations` | reviewer | add a human (verified) observation |
| GET | `/v1/assets/{id}/reviews` | viewer | review history |
| GET/POST | `/v1/projects/{id}/metrics` | viewer / manager | measured values with declared sources |
| GET/POST | `/v1/projects/{id}/claims` | viewer / contributor | claims |
| GET/PATCH | `/v1/claims/{id}` | viewer / contributor | claim detail (evidence, metrics, rule check) |
| POST/DELETE | `/v1/claims/{id}/evidence` | contributor | link/unlink assets, observations or confirmed before/after pairs |
| PUT/DELETE | `/v1/claims/{id}/metrics/{metric_id}` | contributor | link/unlink metrics |
| POST | `/v1/claims/{id}/validate` | contributor | evidence rules + LLM check |
| POST | `/v1/claims/{id}/submit` · `approve` · `reject` · `retract` | contributor / reviewer / manager | workflow (four-eyes approval) |
| GET | `/v1/claims/{id}/graph` | viewer | evidence graph: claim ← observation ← asset, claim ← metric |
| GET/POST | `/v1/projects/{id}/events` (+ `/suggestions`) | viewer / reviewer | activity events from verified observations |
| GET/POST | `/v1/projects/{id}/reports` | viewer / contributor | list / create (defaults to every approved claim in the period) |
| GET/PATCH | `/v1/reports/{id}` | viewer / contributor | studio view (claims, narrative, problems, snapshots) / edit title, period, audience, claims |
| POST | `/v1/reports/{id}/generate` | contributor | narrative from approved claims; failing sentences dropped and listed |
| PUT | `/v1/reports/{id}/narrative` | contributor | human edit, rejected if any sentence breaks the citation rules |
| GET | `/v1/reports/{id}/preview` | viewer | draft HTML + problems |
| POST | `/v1/reports/{id}/publish` | manager | freeze an immutable, hashed snapshot and queue its PDF |
| GET | `/v1/reports/{id}/snapshots` (`/{v}/manifest`, `/{v}/html`, `/{v}/verify`) | viewer | versions, frozen manifest, rendered HTML, re-render + hash check |
| GET/POST | `/v1/reports/{id}/snapshots/{v}/pdf` | viewer / manager | expiring signed PDF link (audited) / re-queue the PDF |
| POST | `/v1/projects/{id}/before-after/suggest` | contributor | before/after candidates (site, PostGIS distance, windows, SigLIP), queued for alignment |
| GET/POST | `/v1/projects/{id}/before-after` | viewer / contributor | list comparisons (by status, site, photo) / compare two chosen photos |
| GET | `/v1/before-after/{id}` | viewer | geometry, homography, visible change, limitations, signed photos + composite |
| POST | `/v1/before-after/{id}/analyze` · `confirm` · `reject` | reviewer | re-run analysis / human decision (audited) |
| GET | `/v1/events/stream` | viewer | SSE: live asset state and before/after updates for the organisation |
| GET | `/v1/audit` | manager | audit trail |
| POST | `/v1/webhooks/cloudinary` | signature | Cloudinary notifications |

Interactive docs: http://localhost:8000/docs

---

## Notes and known limits

- **Webhook signatures:** legacy `X-Cld-Signature` (SHA-1/SHA-256) is fully verified. Triggers configured
  with `auth_scheme: eddsa_v2` only send the Ed25519 header, and those are rejected until the v2
  public-key flow is wired in. Keep triggers on `default`, and per-upload `notification_url` works as is.
- **Video (Phase 2):** a representative frame (`so_50p`) is analysed. Full timestamped video analysis
  arrives in Phase 6.
- **SigLIP model:** downloaded on first use (~800 MB) into the Hugging Face cache. The first search in a
  fresh API process takes ~10 s (model load), then ~50 ms. Set `EMBEDDINGS_WARMUP=true` for demos.
- **Existing assets** processed before Phase 3 have no embeddings: run `make reindex project=<id>`.
- **Reports:** a snapshot's manifest and hashes are immutable (a Postgres trigger refuses updates); only
  its PDF columns are filled in later. Retracting a claim never changes old snapshots: they are flagged
  in the studio, and the next publish refuses until the claim is removed. External reports use only the
  face-pixelated rendition and leave videos out until redacted video exists (Phase 8).
- **Report PDFs** need Chromium on the worker machine (`make playwright`) and Cloudinary; without
  them the snapshot is still published and its HTML stays available.
- **Before/after** runs on the worker's `ml` queue (OpenCV SIFT + RANSAC, ~50 ms per pair at
  1024 px). SigLIP proposes candidates, geometry decides: a pair that fails verification always ranks
  below every verified one. Visual measures (changed share, green cover) describe pixels, never
  impact; they are shown with rule-derived limitations and cannot be quoted as claim numbers. The
  composite is a signed Cloudinary URL (before photo + `l_authenticated:` after layer, cropped to the
  shared view); external reports use the face-pixelated variant. Only reviewer-confirmed pairs can
  support claims, and a pair in use cannot be rejected.
- **Report renderer compatibility:** snapshots are verified by re-rendering, so template changes must
  be additive (new sections render nothing for older manifests). `test_render.py` pins the HTML hash
  of a pre-Phase-7 manifest. `RENDERER_VERSION` is printed in the footer, so bumping it would break
  verification of every existing snapshot (render the stored version instead if it ever must change).
- The Cloudinary **Analyze API** and **AI Video Analysis** are Beta. The code treats them as optional
  accelerators behind adapters.
