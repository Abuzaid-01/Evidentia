"""Configure the Cloudinary product environment for Evidentia (idempotent).

uv run python infra/cloudinary/bootstrap.py            # apply
uv run python infra/cloudinary/bootstrap.py --dry-run  # show what would change
"""

from __future__ import annotations

import argparse
import sys

from evidentia_cloudinary import CloudinaryCredentials, bootstrap, configure
from evidentia_core.config import get_settings


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--dry-run", action="store_true", help="only check what exists")
    parser.add_argument(
        "--structured-metadata",
        action="store_true",
        help="also create structured metadata fields (then set CLOUDINARY_USE_STRUCTURED_METADATA=true)",
    )
    args = parser.parse_args()

    settings = get_settings()
    if not settings.cloudinary_configured:
        print("CLOUDINARY_URL is not set in .env (Console > Settings > API Keys).", file=sys.stderr)
        return 2
    cloud, key, secret = settings.cloudinary_parts()
    configure(CloudinaryCredentials(cloud, key, secret, settings.cloudinary_signature_algorithm))
    print(f"Cloudinary product environment: {cloud}")

    report = bootstrap.run(structured_metadata=args.structured_metadata, dry_run=args.dry_run)
    return 1 if report.errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
