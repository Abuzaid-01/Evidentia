"""Before/after pairing benchmark (PLAN Phase 7: "the correct pair ranks first >= 80% of the time").

Labelled data: a folder with the photos and a `pairs.csv` with two columns, `before,after`
(file names relative to the folder). Every after photo is ranked against every before photo in the
file (plus any photos in --distractors) with the production score: SigLIP image similarity
(unless --no-siglip) combined with geometric verification, exactly as the worker ranks pairs.

    uv run python infra/eval/before_after_eval.py demo-pairs/            # real labelled pairs
    uv run python infra/eval/before_after_eval.py --synthetic 12         # offline self-check

Prints top-1 accuracy and mean reciprocal rank; exits 1 when top-1 is below --min-top1.
"""

from __future__ import annotations

import argparse
import csv
import sys
import time
from pathlib import Path

import numpy as np
from evidentia_core.domain.before_after import rank_score
from evidentia_ml.before_after import Prepared, align, prepare, prepare_array


def _similarities(befores: list[bytes], afters: list[bytes], model: str) -> np.ndarray:
    from evidentia_ml.embeddings import get_embedder

    embedder = get_embedder(model, "cpu", 768)
    b = np.array(embedder.embed_images(befores))
    a = np.array(embedder.embed_images(afters))
    return a @ b.T  # vectors are L2-normalised: cosine similarity


def evaluate(
    before_ids: list[str],
    befores: list[Prepared],
    after_ids: list[str],
    afters: list[Prepared],
    truth: dict[str, str],
    sims: np.ndarray | None,
) -> tuple[float, float, list[str]]:
    lines, hits, rr = [], 0, 0.0
    for i, (after_id, after) in enumerate(zip(after_ids, afters, strict=True)):
        scores = []
        for j, before in enumerate(befores):
            similarity = float(sims[i, j]) if sims is not None else None
            scores.append(rank_score(similarity, align(before, after).as_dict()))
        order = list(np.argsort(scores)[::-1])
        rank = [before_ids[k] for k in order].index(truth[after_id]) + 1
        hits += rank == 1
        rr += 1 / rank
        best = before_ids[order[0]]
        lines.append(
            f"{'ok ' if rank == 1 else 'MISS'} {after_id}: truth rank {rank}, best {best} ({scores[order[0]]:.3f})"
        )
    n = len(after_ids)
    return hits / n, rr / n, lines


def _load_folder(
    folder: Path, distractors: Path | None
) -> tuple[list[str], list[bytes], list[str], list[bytes], dict[str, str]]:
    with (folder / "pairs.csv").open(newline="") as fh:
        rows = [r for r in csv.DictReader(fh) if r.get("before") and r.get("after")]
    if not rows:
        raise SystemExit("pairs.csv needs rows with 'before' and 'after' columns")
    truth = {r["after"].strip(): r["before"].strip() for r in rows}
    before_ids = sorted(set(truth.values()))
    if distractors:
        before_ids += sorted(
            str(p.relative_to(folder)) if p.is_relative_to(folder) else str(p)
            for p in distractors.iterdir()
            if p.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}
        )

    def read(name: str) -> bytes:
        path = Path(name) if Path(name).is_absolute() else folder / name
        return path.read_bytes()

    after_ids = sorted(truth)
    return before_ids, [read(b) for b in before_ids], after_ids, [read(a) for a in after_ids], truth


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("folder", nargs="?", type=Path)
    parser.add_argument(
        "--distractors", type=Path, help="extra before-candidates that match nothing"
    )
    parser.add_argument("--synthetic", type=int, metavar="N", help="use N synthetic scenes instead")
    parser.add_argument(
        "--no-siglip", action="store_true", help="geometry only (no model download)"
    )
    parser.add_argument("--model", default="google/siglip-base-patch16-224")
    parser.add_argument("--min-top1", type=float, default=0.8)
    args = parser.parse_args()

    started = time.perf_counter()
    if args.synthetic:
        from evidentia_ml.synthetic import jpeg, repeat_photo, scene

        before_ids = [f"scene{s}" for s in range(args.synthetic)]
        after_ids = [f"scene{s}-after" for s in range(args.synthetic)]
        truth = dict(zip(after_ids, before_ids, strict=True))
        before_imgs = [scene(s) for s in range(args.synthetic)]
        after_imgs = [
            repeat_photo(img, s, green=s % 2 == 0)[0] for s, img in enumerate(before_imgs)
        ]
        before_bytes, after_bytes = [jpeg(i) for i in before_imgs], [jpeg(i) for i in after_imgs]
        befores, afters = (
            [prepare_array(i) for i in before_imgs],
            [prepare_array(i) for i in after_imgs],
        )
    elif args.folder:
        before_ids, before_bytes, after_ids, after_bytes, truth = _load_folder(
            args.folder, args.distractors
        )
        befores, afters = [prepare(b) for b in before_bytes], [prepare(a) for a in after_bytes]
    else:
        parser.error("give a folder with pairs.csv, or --synthetic N")

    sims = None if args.no_siglip else _similarities(before_bytes, after_bytes, args.model)
    top1, mrr, lines = evaluate(before_ids, befores, after_ids, afters, truth, sims)
    print("\n".join(lines))
    print(
        f"\n{len(after_ids)} after photos x {len(before_ids)} candidates · "
        f"top-1 {top1:.0%} · MRR {mrr:.3f} · scoring {'geometry' if sims is None else 'SigLIP + geometry'} · "
        f"{time.perf_counter() - started:.1f}s"
    )
    if top1 < args.min_top1:
        print(f"FAIL: top-1 below {args.min_top1:.0%}")
        return 1
    print(f"PASS: top-1 >= {args.min_top1:.0%}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
