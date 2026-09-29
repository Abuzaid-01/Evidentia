"use client";

import { ArrowRight, GitCompareArrows, Loader2, Search } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useMemo, useState, type FormEvent } from "react";
import { toast } from "sonner";

import { GradeBadge, PENDING, PairStatusBadge } from "@/components/before-after/badges";
import { Button } from "@/components/ui/button";
import { Card, CardHeader } from "@/components/ui/card";
import { EmptyState, ErrorState, Skeleton } from "@/components/ui/feedback";
import { Field, Input, Select } from "@/components/ui/form";
import { PageHeader } from "@/components/ui/page-header";
import { useMe, usePairs, useSites, useSuggestPairs } from "@/lib/api/hooks";
import { hasRole, type PairStatus, type PairSummary } from "@/lib/api/types";
import { cn, formatDate, percent } from "@/lib/utils";

function Thumb({ url, label }: { url: string | null | undefined; label: string }) {
  return (
    <div className="relative aspect-[4/3] w-full overflow-hidden rounded-lg bg-surface-muted">
      {url && (
        // eslint-disable-next-line @next/next/no-img-element
        <img src={url} alt={label} className="size-full object-cover" />
      )}
      <span className="absolute left-1.5 top-1.5 rounded bg-black/60 px-1.5 py-0.5 text-[10px] font-medium text-white">{label}</span>
    </div>
  );
}

function CandidateRow({ pair, best }: { pair: PairSummary; best: boolean }) {
  return (
    <Link
      href={`/before-after/${pair.id}`}
      className={cn(
        "grid grid-cols-[96px_1fr] items-center gap-3 rounded-lg border p-2 transition hover:border-accent/50",
        best ? "border-accent/40 bg-accent-soft/40" : "border-border",
      )}
    >
      <Thumb url={pair.before.thumb_url} label={formatDate(pair.before.capture_time)} />
      <div className="min-w-0 space-y-1 text-xs">
        <div className="flex flex-wrap items-center gap-1.5">
          <PairStatusBadge status={pair.status} />
          <GradeBadge grade={pair.alignment_grade} />
          {best && pair.alignment_grade && pair.alignment_grade !== "none" && <span className="font-medium text-accent">Best match</span>}
        </div>
        <p className="truncate text-text-muted">{pair.before.original_filename}</p>
        <p className="text-text-subtle">
          score {pair.rank_score.toFixed(2)}
          {pair.similarity !== null && ` · look-alike ${percent(pair.similarity)}`}
          {pair.days_apart !== null && ` · ${pair.days_apart} days earlier`}
          {pair.distance_m !== null && ` · ${Math.round(pair.distance_m)} m apart`}
        </p>
        {pair.change_summary && <p className="line-clamp-2 text-text">{pair.change_summary}</p>}
        {pair.analysis_error && <p className="text-danger">{pair.analysis_error}</p>}
      </div>
    </Link>
  );
}

export default function BeforeAfterPage() {
  const { projectId } = useParams<{ projectId: string }>();
  const { data: me } = useMe();
  const sites = useSites(projectId);
  const [status, setStatus] = useState<PairStatus | "">("");
  const pairs = usePairs(projectId, status ? { status_filter: status } : {});
  const suggest = useSuggestPairs(projectId);
  const canSuggest = hasRole(me?.role, "contributor");

  const groups = useMemo(() => {
    const byAfter = new Map<string, PairSummary[]>();
    for (const pair of pairs.data ?? []) {
      byAfter.set(pair.after.id, [...(byAfter.get(pair.after.id) ?? []), pair]);
    }
    const list = [...byAfter.values()].map((items) => items.sort((a, b) => b.rank_score - a.rank_score));
    return list.sort((a, b) => (b[0].after.capture_time ?? "").localeCompare(a[0].after.capture_time ?? ""));
  }, [pairs.data]);
  const stillPending = (pairs.data ?? []).some((p) => PENDING.includes(p.status));

  async function onSuggest(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const value = (name: string) => String(form.get(name) || "") || null;
    try {
      const out = await suggest.mutateAsync({
        site_id: value("site_id"),
        baseline_from: value("baseline_from"),
        baseline_to: value("baseline_to"),
        endline_from: value("endline_from"),
        endline_to: value("endline_to"),
        max_distance_m: Number(form.get("max_distance_m") || 250),
        min_gap_days: 7,
        per_anchor: 3,
        limit: 60,
      });
      if (!out.windows) toast.info("Not enough dated photos to split into baseline and endline yet.");
      else if (!out.pairs.length) toast.info("No candidate pairs: try wider windows or a larger distance.");
      else toast.success(`${out.pairs.length} candidate pairs for ${out.anchors} after photos · ${out.queued} queued for alignment`);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Could not search for pairs");
    }
  }

  return (
    <>
      <PageHeader
        eyebrow="Evidence"
        title="Before / after"
        description="Photos of the same place on two dates. Candidates come from the same site, nearby GPS and look-alike search; feature geometry then verifies and aligns them, and a reviewer confirms before a pair can back a claim."
      />

      {canSuggest && (
        <Card className="mb-6">
          <CardHeader title="Find pairs" description="Leave the dates empty to split each site's photos at the middle of their date range." />
          <form onSubmit={onSuggest} className="grid gap-3 px-5 py-4 md:grid-cols-4">
            <Field label="Site">
              <Select name="site_id" defaultValue="">
                <option value="">All sites</option>
                {sites.data?.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.name}
                  </option>
                ))}
              </Select>
            </Field>
            <Field label="Baseline from"><Input name="baseline_from" type="date" /></Field>
            <Field label="Baseline to"><Input name="baseline_to" type="date" /></Field>
            <Field label="Max GPS distance (m)"><Input name="max_distance_m" type="number" min={1} max={5000} defaultValue={250} /></Field>
            <div className="hidden md:block" />
            <Field label="Endline from"><Input name="endline_from" type="date" /></Field>
            <Field label="Endline to"><Input name="endline_to" type="date" /></Field>
            <div className="flex items-end">
              <Button type="submit" loading={suggest.isPending} className="w-full">
                <Search /> Find pairs
              </Button>
            </div>
          </form>
        </Card>
      )}

      <div className="mb-4 flex items-center justify-between gap-3">
        <h2 className="flex items-center gap-2 text-sm font-semibold">
          Comparisons {stillPending && <Loader2 className="size-4 animate-spin text-info" />}
        </h2>
        <Select value={status} onChange={(e) => setStatus(e.target.value as PairStatus | "")} className="w-48">
          <option value="">Every status</option>
          <option value="analyzed">Needs review</option>
          <option value="confirmed">Confirmed</option>
          <option value="candidate">Queued</option>
          <option value="failed">Failed</option>
          <option value="rejected">Rejected</option>
        </Select>
      </div>

      {pairs.error && <ErrorState error={pairs.error} onRetry={() => pairs.refetch()} />}
      {!pairs.data && !pairs.error && <Skeleton className="h-64" />}
      {pairs.data && groups.length === 0 && (
        <EmptyState icon={GitCompareArrows} title="No comparisons yet" description="Use “Find pairs” once photos of the same place exist from two periods." />
      )}
      <div className="grid gap-4 xl:grid-cols-2">
        {groups.map((items) => {
          const after = items[0].after;
          return (
            <Card key={after.id} className="p-4">
              <div className="grid grid-cols-[180px_1fr] gap-4">
                <div className="space-y-1.5">
                  <Thumb url={after.thumb_url} label={`After · ${formatDate(after.capture_time)}`} />
                  <Link href={`/assets/${after.id}`} className="block truncate text-xs text-accent hover:underline">
                    {after.original_filename ?? after.id}
                  </Link>
                </div>
                <div className="space-y-2">
                  <p className="flex items-center gap-1 text-xs font-medium uppercase tracking-wider text-text-muted">
                    Candidate before photos <ArrowRight className="size-3" />
                  </p>
                  {items.map((pair, i) => (
                    <CandidateRow key={pair.id} pair={pair} best={i === 0} />
                  ))}
                </div>
              </div>
            </Card>
          );
        })}
      </div>
    </>
  );
}
