"use client";

import { FileImage, FileVideo, RotateCcw, ShieldCheck, UploadCloud, X } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useRef, useState, type DragEvent } from "react";

import { StateBadge } from "@/components/assets/state-badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Progress } from "@/components/ui/feedback";
import { Field, Input, Select } from "@/components/ui/form";
import { api, unwrap } from "@/lib/api/client";
import { useSites, useTaxonomy } from "@/lib/api/hooks";
import type { AssetState } from "@/lib/api/types";
import { useAssetEvents } from "@/lib/events/use-org-events";
import { UploadAborted, uploadToCloudinary } from "@/lib/upload/cloudinary-upload";
import { cn, formatBytes } from "@/lib/utils";

const ACCEPT = "image/jpeg,image/png,image/heic,image/heif,image/webp,video/mp4,video/quicktime,video/webm";
const CONCURRENCY = 3;

type Phase = "queued" | "signing" | "uploading" | "confirming" | "processing" | "error" | "cancelled";

type Item = {
  key: string;
  file: File;
  phase: Phase;
  progress: number;
  assetId?: string;
  state?: AssetState;
  error?: string;
  controller?: AbortController;
};

type Context = { siteId: string; activity: string; note: string };

export function Uploader({ projectId }: { projectId: string }) {
  const sites = useSites(projectId);
  const taxonomy = useTaxonomy(projectId);
  const [items, setItems] = useState<Item[]>([]);
  const [context, setContext] = useState<Context>({ siteId: "", activity: "", note: "" });
  const [dragging, setDragging] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const active = useRef(0);
  const queue = useRef<Item[]>([]);

  const patch = useCallback((key: string, update: Partial<Item>) => {
    setItems((current) => current.map((item) => (item.key === key ? { ...item, ...update } : item)));
  }, []);

  // Live pipeline progress for files uploaded in this session.
  useAssetEvents((event) => {
    setItems((current) =>
      current.map((item) =>
        item.assetId === event.asset_id ? { ...item, state: event.state as AssetState } : item,
      ),
    );
  });

  const process = useCallback(
    async (item: Item, ctx: Context) => {
      const controller = new AbortController();
      patch(item.key, { phase: "signing", controller, error: undefined });
      try {
        const signed = unwrap(
          await api.POST("/v1/uploads/sign", {
            body: {
              project_id: projectId,
              site_id: ctx.siteId || null,
              filename: item.file.name,
              content_type: item.file.type || "application/octet-stream",
              size_bytes: item.file.size,
              declared_activity: ctx.activity || null,
              note: ctx.note || null,
            },
          }),
        );
        patch(item.key, { phase: "uploading", assetId: signed.asset_id });
        const result = await uploadToCloudinary(item.file, signed, {
          signal: controller.signal,
          onProgress: (progress) => patch(item.key, { progress }),
        });
        patch(item.key, { phase: "confirming", progress: 1 });
        const asset = unwrap(
          await api.POST("/v1/assets/{asset_id}/confirm", {
            params: { path: { asset_id: signed.asset_id } },
            body: { public_id: result.public_id, version: result.version, signature: result.signature },
          }),
        );
        patch(item.key, { phase: "processing", state: asset.state });
      } catch (error) {
        if (error instanceof UploadAborted) patch(item.key, { phase: "cancelled" });
        else patch(item.key, { phase: "error", error: error instanceof Error ? error.message : String(error) });
      }
    },
    [patch, projectId],
  );

  // Keep the latest `process` in a ref so the queue pump can be a stable callback.
  const processRef = useRef(process);
  useEffect(() => {
    processRef.current = process;
  }, [process]);

  const pump = useCallback((ctx: Context) => {
    const startNext = () => {
      while (active.current < CONCURRENCY && queue.current.length) {
        const next = queue.current.shift()!;
        active.current += 1;
        void processRef.current(next, ctx).finally(() => {
          active.current -= 1;
          startNext();
        });
      }
    };
    startNext();
  }, []);

  const addFiles = useCallback(
    (files: FileList | File[]) => {
      const added = Array.from(files).map<Item>((file) => ({
        key: `${file.name}-${file.size}-${file.lastModified}-${crypto.randomUUID()}`,
        file,
        phase: "queued",
        progress: 0,
      }));
      if (!added.length) return;
      setItems((current) => [...added, ...current]);
      queue.current.push(...added);
      pump(context);
    },
    [context, pump],
  );

  const retry = (item: Item) => {
    patch(item.key, { phase: "queued", progress: 0, error: undefined });
    queue.current.push(item);
    pump(context);
  };

  const onDrop = (event: DragEvent) => {
    event.preventDefault();
    setDragging(false);
    addFiles(event.dataTransfer.files);
  };

  const done = items.filter((i) => i.state === "ready" || i.state === "review_required").length;

  return (
    <div className="grid gap-6 lg:grid-cols-[320px_1fr]">
      <Card className="h-fit p-5">
        <h2 className="text-sm font-semibold">Field context</h2>
        <p className="mt-1 text-xs text-text-muted">Applied to the next files you add. AI checks it; it never overrides what is visible.</p>
        <div className="mt-4 flex flex-col gap-4">
          <Field label="Site">
            <Select value={context.siteId} onChange={(e) => setContext({ ...context, siteId: e.target.value })}>
              <option value="">Not specified</option>
              {sites.data?.map((site) => (
                <option key={site.id} value={site.id}>
                  {site.code} · {site.name}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="Activity (what you photographed)">
            <Select value={context.activity} onChange={(e) => setContext({ ...context, activity: e.target.value })}>
              <option value="">Let AI decide</option>
              {taxonomy.data?.activities.map((a) => (
                <option key={a.key} value={a.key}>
                  {a.label}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="Note">
            <Input value={context.note} maxLength={1000} placeholder="e.g. north trench, day 3" onChange={(e) => setContext({ ...context, note: e.target.value })} />
          </Field>
        </div>
        <div className="mt-5 flex items-start gap-2 rounded-lg bg-accent-soft p-3 text-xs text-accent">
          <ShieldCheck className="mt-0.5 size-4 shrink-0" />
          <span>
            Files go straight to Cloudinary as <strong>private, signed</strong> uploads. Originals are never modified.
          </span>
        </div>
      </Card>

      <div className="flex flex-col gap-4">
        <div
          onDragOver={(e) => {
            e.preventDefault();
            setDragging(true);
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={onDrop}
          onClick={() => inputRef.current?.click()}
          className={cn(
            "flex cursor-pointer flex-col items-center justify-center rounded-2xl border-2 border-dashed px-6 py-12 text-center transition",
            dragging ? "border-accent bg-accent-soft" : "border-border bg-surface hover:border-accent/60",
          )}
        >
          <div className="mb-3 rounded-full bg-accent-soft p-3 text-accent">
            <UploadCloud className="size-7" />
          </div>
          <p className="font-medium">Drop photos and videos here</p>
          <p className="mt-1 text-sm text-text-muted">JPEG, PNG, HEIC, WebP · MP4, MOV, WebM · large videos upload in chunks</p>
          <input
            ref={inputRef}
            type="file"
            accept={ACCEPT}
            multiple
            hidden
            onChange={(e) => {
              if (e.target.files) addFiles(e.target.files);
              e.target.value = "";
            }}
          />
        </div>

        {items.length > 0 && (
          <Card>
            <div className="flex items-center justify-between border-b border-border px-5 py-3 text-sm">
              <span className="font-medium">
                {items.length} file{items.length === 1 ? "" : "s"} · {done} processed
              </span>
              <Link href={`/projects/${projectId}/media`} className="text-accent hover:underline">
                Open media library →
              </Link>
            </div>
            <ul className="divide-y divide-border">
              {items.map((item) => (
                <UploadRow key={item.key} item={item} onRetry={() => retry(item)} />
              ))}
            </ul>
          </Card>
        )}
      </div>
    </div>
  );
}

const PHASE_LABEL: Record<Phase, string> = {
  queued: "Queued",
  signing: "Preparing secure upload…",
  uploading: "Uploading to Cloudinary",
  confirming: "Verifying upload…",
  processing: "Processing",
  error: "Failed",
  cancelled: "Cancelled",
};

function UploadRow({ item, onRetry }: { item: Item; onRetry: () => void }) {
  const Icon = item.file.type.startsWith("video") ? FileVideo : FileImage;
  return (
    <li className="flex items-center gap-4 px-5 py-3">
      <Icon className="size-5 shrink-0 text-text-subtle" />
      <div className="min-w-0 flex-1">
        <div className="flex items-center justify-between gap-3">
          <p className="truncate text-sm font-medium">{item.file.name}</p>
          <span className="shrink-0 text-xs text-text-subtle">{formatBytes(item.file.size)}</span>
        </div>
        {item.phase === "uploading" ? (
          <Progress value={item.progress} className="mt-2" />
        ) : (
          <p className={cn("mt-1 text-xs", item.phase === "error" ? "text-danger" : "text-text-muted")}>
            {item.error ?? PHASE_LABEL[item.phase]}
          </p>
        )}
      </div>
      <div className="flex shrink-0 items-center gap-2">
        {item.state && item.phase === "processing" && <StateBadge state={item.state} />}
        {item.assetId && (item.state === "ready" || item.state === "review_required") && (
          <Link href={`/assets/${item.assetId}`} className="text-xs text-accent hover:underline">
            View
          </Link>
        )}
        {item.phase === "uploading" && (
          <Button size="icon" variant="ghost" title="Cancel" onClick={() => item.controller?.abort()}>
            <X />
          </Button>
        )}
        {(item.phase === "error" || item.phase === "cancelled") && (
          <Button size="sm" variant="secondary" onClick={onRetry}>
            <RotateCcw /> Retry
          </Button>
        )}
      </div>
    </li>
  );
}
