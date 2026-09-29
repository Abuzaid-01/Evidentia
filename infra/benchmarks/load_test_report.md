# Evidentia load benchmark (measured locally)

Run 2026-09-29T13:23:19+00:00 · 1,000 assets across 4 sites · embedder `google/siglip-base-patch16-224` · LLM planner off · Cloudinary Search retriever off.

Every number below was timed on this machine against the real API app and the real Postgres database. Produced by `make loadtest`.

## 1. Search over the corpus

| Measure | Value |
| :--- | ---: |
| Requests (concurrency) | 300 (10) |
| Errors | 0 |
| Throughput | 20.6 queries/s |
| Latency p50 / p95 / p99 (end to end) | 474 / 554 / 687 ms |
| Server-reported search time p50 / p95 | 470 / 550 ms |
| Mean results per query | 19.2 |
| PLAN Phase 3 target: p95 < 1500 ms, no errors | **PASS** |

## 2. Registration (database side of ingestion)

| Measure | Value |
| :--- | ---: |
| Embedding 1,000 texts + 1,000 image vectors | 32.7 s |
| Writing assets + observations + embeddings | 7.3 s (137 assets/s) |

## 3. Not measured here

Cloudinary upload and transformations, Cloudinary Analyze, LLM/VLM calls and network time are excluded: they spend account quota and depend on the plan and region. End-to-end ingestion time per job is in the worker logs; latency of real AI calls is on the project analytics page.

## 4. What one photo consumes

| Service | Per asset |
| :--- | :--- |
| Cloudinary upload | 1 authenticated upload (bytes go browser → Cloudinary directly) |
| Cloudinary transformations | 3 renditions: 2 eager (t_ev_thumb, t_ev_review) + 1 model input (t_ev_ai) |
| Cloudinary Analyze (Beta) | 3 calls: captioning, image_quality, ai_vision_tagging (skipped if no taxonomy) |
| Structured extraction | 1 successful call through the provider chain (cloudinary, gemini, groq); later providers are only called when earlier ones fail |
| OCR / auto-tagging add-ons | OCR off; auto-tagging off |
| Embeddings | 2 local google/siglip-base-patch16-224 passes (image + text); no API cost |

To turn this into money, use your Cloudinary plan's credit rules (Console → Usage) and your Gemini/Groq tier; prices are deliberately not guessed here.
