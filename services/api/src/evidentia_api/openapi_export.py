"""Write the OpenAPI document to disk (the web app generates its typed client from it)."""

from __future__ import annotations

import json
import sys
from pathlib import Path


def main() -> None:
    from evidentia_api.main import create_app

    target = Path(sys.argv[1] if len(sys.argv) > 1 else "apps/web/src/lib/api/openapi.json")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(create_app().openapi(), indent=2) + "\n")
    print(f"wrote {target}")


if __name__ == "__main__":
    main()
