"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, ArrowLeft, Check, Cloud, FileCheck2, RefreshCw, X } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";

import { GradeBadge, PENDING, PairStatusBadge } from "@/components/before-after/badges";
import { ComparisonSlider } from "@/components/before-after/comparison-slider";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { ErrorState, Skeleton } from "@/components/ui/feedback";
import { Select, Textarea } from "@/components/ui/form";
import { api, unwrap } from "@/lib/api/client";
import { keys, useMe, usePair, usePairAction } from "@/lib/api/hooks";
import { hasRole, type PairAlignment, type PairChanges, type PairDetail } from "@/lib/api/types";
import { formatDate, humanize, percent } from "@/lib/utils";

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <>
      <dt className="text-text-muted">{label}</dt>
      <dd className="text-text">{children}</dd>
    </>
  );
}

function Decision({ pair, canReview }: { pair: PairDetail; canReview: boolean }) {
  const [note, setNote] = useState("");
  const action = usePairAction(pair.id);
  const run = async (name: "confirm" | "reject" | "analyze") => {
    try {
      await action.mutateAsync({ action: name, note });
      toast.success(name === "analyze" ? "Re-analysis queued" : `Comparison ${name === "confirm" ? "confirmed" : "rejected"}`);
      setNote("");
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Failed");
    }
  };
  const aligned = Boolean((pair.alignment as PairAlignment | null)?.ok);

  if (pair.status === "confirmed" || pair.status === "rejected") {
    return (
      <Card className="p-5 text-sm">
        <p className="font-semibold">{pair.status === "confirmed" ? "Confirmed as the same place" : "Rejected"}</p>
        <p className="mt-1 text-text-muted">
          {formatDate(pair.decided_at, true)}
          {pair.decision_note && <> · “{pair.decision_note}”</>}
        </p>
      </Card>
    );
  }
  if (!canReview) return null;
  return (
    <Card>
      <CardHeader
        title="Reviewer decision"
        description="Confirm only if both photos show the same place. Confirmed comparisons can support claims."
      />
      <CardBody className="space-y-3">
        <Textarea
          value={note}
          onChange={(e) => setNote(e.target.value)}
          placeholder={aligned ? "Note (required to reject)" : "Not aligned: a note is required to confirm or reject"}
        />
        <div className="flex flex-wrap gap-2">
          <Button onClick={() => run("confirm")} loading={action.isPending} disabled={pair.status !== "analyzed"}>
            <Check /> Confirm
          </Button>
          <Button variant="secondary" onClick={() => run("reject")} loading={action.isPending}>
            <X /> Reject
          </Button>
          <Button variant="ghost" onClick={() => run("analyze")} loading={action.isPending} disabled={PENDING.includes(pair.status)}>
            <RefreshCw /> Re-analyse
          </Button>
        </div>
      </CardBody>
    </Card>
  );
}

function UseAsEvidence({ pair }: { pair: PairDetail }) {
  const client = useQueryClient();
  const [claimId, setClaimId] = useState("");
  const [busy, setBusy] = useState(false);
  const claims = useQuery({
    queryKey: ["projects", pair.project_id, "claims"],
    queryFn: async () =>
      unwrap(await api.GET("/v1/projects/{project_id}/claims", { params: { path: { project_id: pair.project_id } } })),
  });
  const linkedClaims = pair.claims ?? [];
  const linked = new Set(linkedClaims.map((c) => c.id));
  const editable = (claims.data ?? []).filter((c) => ["draft", "rejected"].includes(c.status) && !linked.has(c.id));

  async function link() {
    setBusy(true);
    try {
      unwrap(
        await api.POST("/v1/claims/{claim_id}/evidence", {
          params: { path: { claim_id: claimId } },
          body: { pair_id: pair.id, relation: "supports" },
        }),
      );
      toast.success("Linked as supporting evidence");
      setClaimId("");
      await client.invalidateQueries({ queryKey: keys.pair(pair.id) });
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Could not link");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card>
      <CardHeader title="Evidence for claims" description="A confirmed comparison can support progress or descriptive claims. It is never an outcome metric." />
      <CardBody className="space-y-3 text-sm">
        {linkedClaims.length > 0 && (
          <ul className="space-y-1">
            {linkedClaims.map((c) => (
              <li key={c.id} className="flex items-center gap-2">
                <FileCheck2 className="size-4 text-accent" />
                <Link href={`/claims/${c.id}`} className="flex-1 truncate text-accent hover:underline">
                  {c.statement}
                </Link>
                <Badge tone="outline">{c.status}</Badge>
              </li>
            ))}
          </ul>
        )}
        {pair.status === "confirmed" ? (
          <div className="flex gap-2">
            <Select value={claimId} onChange={(e) => setClaimId(e.target.value)} className="flex-1">
              <option value="">Pick a draft claim…</option>
              {editable.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.statement}
                </option>
              ))}
            </Select>
            <Button onClick={link} disabled={!claimId} loading={busy}>
              Link
            </Button>
          </div>
        ) : (
          <p className="text-text-muted">Available once a reviewer confirms this comparison.</p>
        )}
      </CardBody>
    </Card>
  );
}

export default function PairPage() {
  const { pairId } = useParams<{ pairId: string }>();
  const pair = usePair(pairId);
  const { data: me } = useMe();
  const [showRegions, setShowRegions] = useState(true);

  if (pair.error) return <ErrorState error={pair.error} onRetry={() => pair.refetch()} />;
  if (!pair.data) return <Skeleton className="h-96" />;
  const p = pair.data;
  const alignment = p.alignment as PairAlignment | null;
  const changes = p.changes as PairChanges | null;
  const pending = PENDING.includes(p.status);

  return (
    <>
      <div className="mb-5">
        <Link href={`/projects/${p.project_id}/before-after`} className="mb-2 inline-flex items-center gap-1 text-sm text-text-muted hover:text-text">
          <ArrowLeft className="size-4" /> Before / after
        </Link>
        <div className="flex flex-wrap items-center gap-2">
          <h1 className="text-xl font-semibold tracking-tight">
            {formatDate(p.before.capture_time)} → {formatDate(p.after.capture_time)}
          </h1>
          <PairStatusBadge status={p.status} />
          <GradeBadge grade={p.alignment_grade} />
          <Badge tone="outline">{p.origin}</Badge>
        </div>
      </div>

      <div className="grid gap-6 lg:grid-cols-[1.4fr_1fr]">
        <div className="flex flex-col gap-6">
          {p.before_url && p.after_url ? (
            <Card className="p-4">
              <ComparisonSlider
                beforeUrl={p.before_url}
                afterUrl={p.after_url}
                alignment={alignment}
                regions={changes?.regions ?? []}
                showRegions={showRegions}
                beforeLabel={`Before · ${formatDate(p.before.capture_time)}`}
                afterLabel={`After · ${formatDate(p.after.capture_time)}`}
              />
              {changes && changes.regions.length > 0 && (
                <label className="mt-3 flex items-center gap-2 text-xs text-text-muted">
                  <input type="checkbox" checked={showRegions} onChange={(e) => setShowRegions(e.target.checked)} />
                  Show change regions
                  <span className="ml-2 inline-flex items-center gap-1"><span className="size-2.5 rounded-sm border-2 border-emerald-400" /> greener</span>
                  <span className="inline-flex items-center gap-1"><span className="size-2.5 rounded-sm border-2 border-amber-400" /> less green</span>
                  <span className="inline-flex items-center gap-1"><span className="size-2.5 rounded-sm border-2 border-sky-400" /> other change</span>
                </label>
              )}
            </Card>
          ) : (
            <Card className="p-5 text-sm text-text-muted">Media previews need Cloudinary to be configured.</Card>
          )}

          {p.composite_url && (
            <Card>
              <CardHeader
                title={<span className="flex items-center gap-2"><Cloud className="size-4 text-accent" /> Cloudinary composite</span>}
                description="Rendered by Cloudinary from both originals (the after photo is a signed authenticated layer); this exact transformation is recorded as a derivative. Reports use this image."
              />
              <CardBody className="space-y-3">
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img src={p.composite_url} alt="Before and after composite" className="w-full rounded-lg border border-border" />
                <p className="break-all font-mono text-[11px] text-text-muted">{p.composite_transformation}</p>
                {p.public_composite_url && (
                  <a href={p.public_composite_url} target="_blank" rel="noreferrer" className="text-xs text-accent hover:underline">
                    Open the face-pixelated version used in external reports
                  </a>
                )}
              </CardBody>
            </Card>
          )}
        </div>

        <div className="flex flex-col gap-6">
          <Card className="p-5">
            <p className="text-xs font-medium uppercase tracking-wider text-accent">Visible change</p>
            <p className="mt-2 text-base leading-relaxed">
              {pending ? "Aligning the photos and measuring change…" : p.change_summary ?? "Not measured."}
            </p>
            {p.analysis_error && <p className="mt-2 rounded-lg bg-danger-soft px-3 py-2 text-sm text-danger">{p.analysis_error}</p>}
            {changes && (
              <>
                <dl className="mt-4 grid grid-cols-[150px_1fr] gap-x-3 gap-y-1.5 text-sm">
                  <Row label="Changed area">{percent(changes.changed_share)} of the shared view</Row>
                  <Row label="Green cover">
                    {percent(changes.green_cover_before)} → {percent(changes.green_cover_after)} ({changes.green_delta_pp > 0 ? "+" : ""}
                    {changes.green_delta_pp} points)
                  </Row>
                  <Row label="Structural similarity">{changes.ssim_mean.toFixed(2)} (SSIM, 1 = identical)</Row>
                  <Row label="Method">{changes.method}</Row>
                </dl>
                <p className="mt-3 text-xs text-text-subtle">Visual measurements of pixels, not impact metrics. They cannot be quoted as numbers in claims.</p>
              </>
            )}
          </Card>

          {p.limitations.length > 0 && (
            <Card className="border-warning/40 p-5">
              <div className="flex items-center gap-2 text-sm font-semibold text-warning">
                <AlertTriangle className="size-4" /> Limitations
              </div>
              <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-text-muted">
                {p.limitations.map((l) => (
                  <li key={l}>{l}</li>
                ))}
              </ul>
            </Card>
          )}

          <Decision pair={p} canReview={hasRole(me?.role, "reviewer")} />
          {hasRole(me?.role, "contributor") && <UseAsEvidence pair={p} />}

          <Card>
            <CardHeader title="Geometry and provenance" />
            <dl className="grid grid-cols-[150px_1fr] gap-x-3 gap-y-1.5 px-5 py-4 text-sm">
              {alignment ? (
                <>
                  <Row label="Matching">{alignment.inliers} consistent matches ({percent(alignment.inlier_ratio)} of candidates)</Row>
                  <Row label="Overlap">{percent(alignment.overlap)} of the before frame</Row>
                  {alignment.rotation_deg !== null && <Row label="Camera change">rotated {alignment.rotation_deg}°, scale ×{alignment.scale}</Row>}
                  {alignment.reason && <Row label="Result">{alignment.reason}</Row>}
                  <Row label="Method">{alignment.method}</Row>
                </>
              ) : (
                <Row label="Matching">{pending ? "running…" : "not analysed"}</Row>
              )}
              <Row label="Look-alike score">{p.similarity !== null ? `${percent(p.similarity)} (SigLIP)` : "—"}</Row>
              <Row label="Time between">{p.days_apart !== null ? `${p.days_apart} days` : "unknown"}</Row>
              <Row label="GPS distance">{p.distance_m !== null ? `${Math.round(p.distance_m)} m` : "unknown"}</Row>
              <Row label="Before photo">
                <Link className="text-accent hover:underline" href={`/assets/${p.before.id}`}>{p.before.original_filename ?? p.before.id}</Link>
                <span className="text-text-subtle"> · time from {humanize(p.before.capture_time_source)}</span>
              </Row>
              <Row label="After photo">
                <Link className="text-accent hover:underline" href={`/assets/${p.after.id}`}>{p.after.original_filename ?? p.after.id}</Link>
                <span className="text-text-subtle"> · time from {humanize(p.after.capture_time_source)}</span>
              </Row>
              <Row label="Analysis version">{p.analysis_version ?? "—"}</Row>
            </dl>
          </Card>
        </div>
      </div>
    </>
  );
}
