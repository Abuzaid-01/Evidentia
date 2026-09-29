"""Measured load benchmark (PLAN Phase 9): 1k-asset corpus, concurrent search, registration speed.

    make loadtest                                   # 1,000 assets, 300 searches, concurrency 10
    uv run python infra/benchmarks/load_test.py --assets 5000 --requests 1000 --concurrency 20

Runs the real API app in-process against the DATABASE_URL in .env (AUTH_MODE=dev required), inside
a throwaway organisation that is deleted afterwards. By default it spends no quota: the LLM query
planner and the Cloudinary Search retriever are off (each would make a paid/rate-limited call per
query); turn them on with --with-llm / --with-cloudinary-search to include their latency.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--assets", type=int, default=1000)
    parser.add_argument("--sites", type=int, default=4)
    parser.add_argument("--requests", type=int, default=300)
    parser.add_argument("--concurrency", type=int, default=10)
    parser.add_argument("--with-llm", action="store_true", help="use the Gemini/Groq planner")
    parser.add_argument(
        "--with-cloudinary-search",
        action="store_true",
        help="include the Cloudinary Search retriever (Admin API rate limits apply)",
    )
    parser.add_argument("--output", type=Path, default=Path("infra/benchmarks/load_test_report.md"))
    args = parser.parse_args()

    # must be set before settings are first read
    os.environ["SEARCH_CLOUDINARY_ENABLED"] = "true" if args.with_cloudinary_search else "false"
    os.environ.setdefault("EMBEDDINGS_WARMUP", "true")

    import httpx
    from evidentia_api.benchmark import format_report, result_summary, run_benchmark
    from evidentia_api.main import create_app
    from evidentia_core.config import get_settings

    settings = get_settings()
    if settings.auth_mode != "dev":
        print("The benchmark signs in with dev identities: set AUTH_MODE=dev.", file=sys.stderr)
        return 2

    async def go() -> int:
        app = create_app(settings)
        async with app.router.lifespan_context(app):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(
                transport=transport, base_url="http://bench", timeout=120
            ) as client:
                print(f"Seeding {args.assets:,} assets and running {args.requests} searches...")
                result = await run_benchmark(
                    client,
                    settings,
                    app.state.embedder,
                    assets=args.assets,
                    sites=args.sites,
                    requests=args.requests,
                    concurrency=args.concurrency,
                    use_llm_planner=args.with_llm,
                )
        report = format_report(result, settings)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(report, encoding="utf-8")
        print(json.dumps(result_summary(result), indent=2))
        print(f"Report: {args.output}")
        return 0 if result.search_ok else 1

    return asyncio.run(go())


if __name__ == "__main__":
    raise SystemExit(main())
