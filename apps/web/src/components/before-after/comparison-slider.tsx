"use client";

import { useEffect, useRef, useState } from "react";

import type { ChangeRegion, PairAlignment } from "@/lib/api/types";
import { cn } from "@/lib/utils";

const REGION_TONE: Record<ChangeRegion["kind"], string> = {
  more_green: "border-emerald-400 bg-emerald-400/10",
  less_green: "border-amber-400 bg-amber-400/10",
  changed: "border-sky-400 bg-sky-400/10",
};

type Matrix = number[][];

function multiply(a: Matrix, b: Matrix): Matrix {
  return a.map((row) => [0, 1, 2].map((j) => row.reduce((sum, value, k) => sum + value * b[k][j], 0)));
}

/**
 * CSS transform that places the after photo onto the before frame.
 * The stored homography maps after-normalised -> before-normalised coordinates, so in pixels:
 * M = S_container · H · S_afterImage⁻¹, written as a column-major matrix3d.
 */
function warp(h: Matrix, container: { w: number; h: number }, image: { w: number; h: number }): string {
  const m = multiply(
    multiply(
      [
        [container.w, 0, 0],
        [0, container.h, 0],
        [0, 0, 1],
      ],
      h,
    ),
    [
      [1 / image.w, 0, 0],
      [0, 1 / image.h, 0],
      [0, 0, 1],
    ],
  );
  const v = [m[0][0], m[1][0], 0, m[2][0], m[0][1], m[1][1], 0, m[2][1], 0, 0, 1, 0, m[0][2], m[1][2], 0, m[2][2]];
  return `matrix3d(${v.map((x) => x.toFixed(10)).join(",")})`;
}

export function ComparisonSlider({
  beforeUrl,
  afterUrl,
  alignment,
  regions = [],
  showRegions = false,
  beforeLabel = "Before",
  afterLabel = "After",
}: {
  beforeUrl: string;
  afterUrl: string;
  alignment: PairAlignment | null;
  regions?: ChangeRegion[];
  showRegions?: boolean;
  beforeLabel?: string;
  afterLabel?: string;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState({ w: 0, h: 0 });
  const [position, setPosition] = useState(50);

  useEffect(() => {
    const element = ref.current;
    if (!element) return;
    const observer = new ResizeObserver(([entry]) =>
      setSize({ w: entry.contentRect.width, h: entry.contentRect.height }),
    );
    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  const aligned = Boolean(alignment?.ok && alignment.homography);
  const [bw, bh] = alignment?.before_size ?? [4, 3];
  const [aw, ah] = alignment?.after_size ?? [4, 3];
  const afterImage = { w: size.w || 1, h: (size.w || 1) * (ah / aw) };

  return (
    <div className="flex flex-col gap-2">
      <div
        ref={ref}
        className="relative w-full select-none overflow-hidden rounded-xl border border-border bg-surface-muted"
        style={{ aspectRatio: `${bw} / ${bh}` }}
      >
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img src={beforeUrl} alt="Before" className="absolute inset-0 size-full object-fill" draggable={false} />
        <div className="absolute inset-0" style={{ clipPath: `inset(0 0 0 ${position}%)` }}>
          {aligned && size.w > 0 ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img
              src={afterUrl}
              alt="After, aligned to the before photo"
              draggable={false}
              className="absolute left-0 top-0 max-w-none"
              style={{
                width: afterImage.w,
                height: afterImage.h,
                transformOrigin: "0 0",
                transform: warp(alignment!.homography as Matrix, size, afterImage),
              }}
            />
          ) : (
            // eslint-disable-next-line @next/next/no-img-element
            <img src={afterUrl} alt="After" className="absolute inset-0 size-full object-cover" draggable={false} />
          )}
        </div>

        {showRegions &&
          regions.map((r, i) => (
            <div
              key={i}
              className={cn("pointer-events-none absolute rounded-sm border-2", REGION_TONE[r.kind])}
              style={{ left: `${r.x * 100}%`, top: `${r.y * 100}%`, width: `${r.w * 100}%`, height: `${r.h * 100}%` }}
            />
          ))}

        <div className="pointer-events-none absolute inset-y-0 w-0.5 bg-white shadow-[0_0_0_1px_rgb(0_0_0/0.3)]" style={{ left: `${position}%` }}>
          <div className="absolute top-1/2 size-8 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-white bg-black/40 backdrop-blur" />
        </div>
        <span className="pointer-events-none absolute left-3 top-3 rounded-md bg-black/60 px-2 py-0.5 text-xs font-medium text-white">
          {beforeLabel}
        </span>
        <span className="pointer-events-none absolute right-3 top-3 rounded-md bg-black/60 px-2 py-0.5 text-xs font-medium text-white">
          {afterLabel}
        </span>
        <input
          type="range"
          min={0}
          max={100}
          step={0.5}
          value={position}
          onChange={(event) => setPosition(Number(event.target.value))}
          aria-label="Reveal before or after"
          className="absolute inset-0 size-full cursor-ew-resize opacity-0"
        />
      </div>
      {!aligned && (
        <p className="text-xs text-warning">
          These photos could not be aligned, so they are shown side by side without correction.
        </p>
      )}
    </div>
  );
}
