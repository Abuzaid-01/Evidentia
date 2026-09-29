"""Load demo field media through the real pipeline (signed upload -> Cloudinary -> confirm -> AI).

Put photos/videos in a folder; each sub-folder is a site (its name becomes the site code):

    demo-media/
      village-a/  IMG_001.jpg ...
      rampura/    VID_004.mp4 ...

    uv run python infra/demo/seed.py demo-media              # API on http://localhost:8000
    uv run python infra/demo/seed.py demo-media --org jalseva --user asha

Idempotent for the project and sites (matched by name / code). Needs the API and worker running,
AUTH_MODE=dev and CLOUDINARY_URL set. Files larger than one upload chunk are skipped: use the web
uploader for those.
"""

from __future__ import annotations

import argparse
import mimetypes
import sys
from pathlib import Path
from typing import Any

import httpx

MEDIA = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".mp4", ".mov", ".m4v", ".webm"}


def _ok(response: httpx.Response) -> Any:
    if response.is_error:
        raise SystemExit(f"{response.request.method} {response.request.url} -> {response.text}")
    return response.json()


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("folder", type=Path)
    parser.add_argument("--api", default="http://localhost:8000")
    parser.add_argument("--project", default="Community Water Access")
    parser.add_argument("--org", default="jalseva", help="dev organisation slug")
    parser.add_argument("--user", default="asha", help="dev user (uploads as a manager)")
    args = parser.parse_args()
    if not args.folder.is_dir():
        print(f"{args.folder} is not a folder", file=sys.stderr)
        return 2

    api = httpx.Client(
        base_url=args.api,
        headers={"Authorization": f"Bearer dev.{args.user}.{args.org}.manager"},
        timeout=60,
    )
    projects = _ok(api.get("/v1/projects"))
    project = next((p for p in projects if p["name"] == args.project), None) or _ok(
        api.post("/v1/projects", json={"name": args.project})
    )
    pid = project["id"]
    sites = {s["code"]: s for s in _ok(api.get(f"/v1/projects/{pid}/sites"))}

    uploaded = skipped = 0
    for path in sorted(args.folder.rglob("*")):
        if path.suffix.lower() not in MEDIA or not path.is_file():
            continue
        rel = path.relative_to(args.folder)
        site_id = None
        if len(rel.parts) > 1:
            code = rel.parts[0][:40]
            if code not in sites:
                name = rel.parts[0].replace("-", " ").replace("_", " ").title()
                sites[code] = _ok(
                    api.post(f"/v1/projects/{pid}/sites", json={"name": name, "code": code})
                )
            site_id = sites[code]["id"]
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        signed = _ok(
            api.post(
                "/v1/uploads/sign",
                json={
                    "project_id": pid,
                    "site_id": site_id,
                    "filename": path.name,
                    "content_type": content_type,
                    "size_bytes": path.stat().st_size,
                },
            )
        )
        if path.stat().st_size > signed["chunk_size"]:
            print(f"skip   {rel} (larger than one chunk; use the web uploader)")
            skipped += 1
            continue
        with path.open("rb") as fh:
            result = httpx.post(
                signed["upload_url"],
                data=signed["fields"],
                files={"file": (path.name, fh, content_type)},
                timeout=300,
            )
        if result.is_error:
            print(f"fail   {rel}: Cloudinary said {result.text[:200]}")
            skipped += 1
            continue
        body = result.json()
        _ok(
            api.post(
                f"/v1/assets/{signed['asset_id']}/confirm",
                json={
                    "public_id": body["public_id"],
                    "version": body["version"],
                    "signature": body["signature"],
                },
            )
        )
        uploaded += 1
        print(f"upload {rel} -> {signed['asset_id']}")

    print(
        f"\n{uploaded} uploaded, {skipped} skipped. The worker is analysing them now.\n"
        f"Next: review at /projects/{pid}/review, build claims at /projects/{pid}/claims,\n"
        f"then a report at /projects/{pid}/reports (sign in as '{args.user}' in org '{args.org}')."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
