"use client";

import { useParams } from "next/navigation";
import {
  Activity,
  BarChart2,
  Clock,
  Coins,
  Cpu,
  Database,
  FileCheck2,
  ShieldCheck,
  Zap,
} from "lucide-react";

import { PageHeader } from "@/components/ui/page-header";
import { useProject, useProjectAnalytics } from "@/lib/api/hooks";
import { cn } from "@/lib/utils";

export default function AnalyticsPage() {
  const { projectId } = useParams<{ projectId: string }>();
  const { data: project } = useProject(projectId);
  const { data: analytics, isLoading, error } = useProjectAnalytics(projectId);

  if (isLoading) {
    return (
      <div className="space-y-6">
        <PageHeader
          eyebrow={project?.name}
          title="Analytics & Cost Accounting"
          description="Pipeline telemetry, ingestion latency, and per-project AI inference cost attribution."
        />
        <div className="flex h-96 items-center justify-center rounded-xl border border-border bg-surface/50 text-text-muted">
          Loading analytics metrics...
        </div>
      </div>
    );
  }

  if (error || !analytics) {
    return (
      <div className="space-y-6">
        <PageHeader
          eyebrow={project?.name}
          title="Analytics & Cost Accounting"
          description="Pipeline telemetry, ingestion latency, and per-project AI inference cost attribution."
        />
        <div className="rounded-xl border border-border bg-surface p-8 text-center text-text-muted">
          Failed to load project analytics.
        </div>
      </div>
    );
  }

  const { ingestion, costs, verification, activities } = analytics;

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow={project?.name}
        title="Analytics & Cost Accounting"
        description="Comprehensive observability, pipeline health, ingestion latencies, and granular Cloudinary & AI cost tracking."
      />

      {/* Top Level Metric Cards */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {/* Total Cost */}
        <div className="rounded-xl border border-border bg-surface p-5">
          <div className="flex items-center justify-between text-text-muted">
            <span className="text-xs font-medium uppercase tracking-wider">AI & Cloud Spend</span>
            <Coins className="size-4 text-accent" />
          </div>
          <p className="mt-2 text-3xl font-bold text-text">
            ${costs.total_estimated_usd.toFixed(4)}
          </p>
          <p className="mt-1 text-xs text-text-muted">
            Storage + Transformations + AI tokens
          </p>
        </div>

        {/* Total Assets */}
        <div className="rounded-xl border border-border bg-surface p-5">
          <div className="flex items-center justify-between text-text-muted">
            <span className="text-xs font-medium uppercase tracking-wider">Total Assets</span>
            <Database className="size-4 text-blue-500" />
          </div>
          <p className="mt-2 text-3xl font-bold text-text">{ingestion.total_assets}</p>
          <p className="mt-1 text-xs text-text-muted">
            {ingestion.successful_runs} analysis runs executed
          </p>
        </div>

        {/* Ingestion Latency */}
        <div className="rounded-xl border border-border bg-surface p-5">
          <div className="flex items-center justify-between text-text-muted">
            <span className="text-xs font-medium uppercase tracking-wider">Avg Latency</span>
            <Clock className="size-4 text-amber-500" />
          </div>
          <p className="mt-2 text-3xl font-bold text-text">{ingestion.avg_latency_ms} ms</p>
          <p className="mt-1 text-xs text-text-muted">
            p95: {ingestion.p95_latency_ms} ms
          </p>
        </div>

        {/* Claim Verification Rate */}
        <div className="rounded-xl border border-border bg-surface p-5">
          <div className="flex items-center justify-between text-text-muted">
            <span className="text-xs font-medium uppercase tracking-wider">Claim Approval Rate</span>
            <ShieldCheck className="size-4 text-emerald-500" />
          </div>
          <p className="mt-2 text-3xl font-bold text-text">
            {verification.approval_rate_pct.toFixed(1)}%
          </p>
          <p className="mt-1 text-xs text-text-muted">
            {verification.claims_approved} of {verification.claims_total} claims verified
          </p>
        </div>
      </div>

      {/* Row 2: Ingestion Health & Cost Breakdown */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        {/* Ingestion Health & Reliability */}
        <div className="rounded-xl border border-border bg-surface p-5 space-y-4">
          <div className="flex items-center gap-2 pb-3 border-b border-border">
            <Activity className="size-4 text-accent" />
            <h3 className="font-semibold text-text text-sm">Pipeline & Ingestion Health</h3>
          </div>

          <div className="grid grid-cols-2 gap-3 text-xs">
            <div className="rounded-lg border border-border bg-surface-muted/50 p-3">
              <span className="text-text-muted">Failure Rate</span>
              <p className={cn("mt-1 text-lg font-bold font-mono", ingestion.failure_rate_pct > 5 ? "text-red-500" : "text-emerald-500")}>
                {ingestion.failure_rate_pct.toFixed(2)}%
              </p>
            </div>
            <div className="rounded-lg border border-border bg-surface-muted/50 p-3">
              <span className="text-text-muted">Successful Analyses</span>
              <p className="mt-1 text-lg font-bold font-mono text-text">
                {ingestion.successful_runs} / {ingestion.total_analysis_runs}
              </p>
            </div>
          </div>

          <div>
            <h4 className="text-xs font-medium text-text-muted uppercase mb-2">Asset State Distribution</h4>
            <div className="space-y-1.5">
              {Object.entries(ingestion.state_counts).map(([state, count]) => {
                const pct = ingestion.total_assets > 0 ? (count / ingestion.total_assets) * 100 : 0;
                return (
                  <div key={state} className="space-y-1">
                    <div className="flex justify-between text-xs">
                      <span className="font-mono text-text">{state}</span>
                      <span className="text-text-muted">{count} ({pct.toFixed(0)}%)</span>
                    </div>
                    <div className="h-1.5 w-full rounded-full bg-surface-muted overflow-hidden">
                      <div
                        className="h-full rounded-full bg-accent"
                        style={{ width: `${pct}%` }}
                      />
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        </div>

        {/* Granular Cost Attribution */}
        <div className="rounded-xl border border-border bg-surface p-5 space-y-4">
          <div className="flex items-center gap-2 pb-3 border-b border-border">
            <Zap className="size-4 text-amber-500" />
            <h3 className="font-semibold text-text text-sm">Granular Cost Attribution</h3>
          </div>

          <div className="space-y-3">
            <div className="flex items-center justify-between rounded-lg border border-border p-3 text-xs">
              <div className="flex items-center gap-3">
                <Database className="size-4 text-blue-500" />
                <div>
                  <p className="font-medium text-text">Cloudinary Media Storage</p>
                  <p className="text-text-muted">{costs.storage_gb.toFixed(4)} GB managed</p>
                </div>
              </div>
              <span className="font-mono font-semibold text-text">
                ${costs.storage_cost_usd.toFixed(4)}
              </span>
            </div>

            <div className="flex items-center justify-between rounded-lg border border-border p-3 text-xs">
              <div className="flex items-center gap-3">
                <Cpu className="size-4 text-purple-500" />
                <div>
                  <p className="font-medium text-text">Dynamic Transformations & Derivatives</p>
                  <p className="text-text-muted">{costs.derivatives_count} derivatives created</p>
                </div>
              </div>
              <span className="font-mono font-semibold text-text">
                ${costs.transformations_cost_usd.toFixed(4)}
              </span>
            </div>

            <div className="flex items-center justify-between rounded-lg border border-border p-3 text-xs">
              <div className="flex items-center gap-3">
                <Coins className="size-4 text-emerald-500" />
                <div>
                  <p className="font-medium text-text">LLM Understanding & Embeddings</p>
                  <p className="text-text-muted">{costs.ai_analysis_runs} AI tool calls</p>
                </div>
              </div>
              <span className="font-mono font-semibold text-text">
                ${costs.ai_tokens_cost_usd.toFixed(4)}
              </span>
            </div>
          </div>

          <div className="mt-4 rounded-lg bg-surface-muted p-3 text-xs text-text-muted">
            <p className="font-medium text-text">Cost Accounting Model</p>
            <p className="mt-0.5">
              Reflects tiered Cloudinary pricing ($0.05/GB storage, $0.001/transformation) and Gemini/Groq token consumption ($0.0005/AI analysis).
            </p>
          </div>
        </div>
      </div>

      {/* Row 3: Claims Verification & Activity Matrix */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        {/* Verification Progress */}
        <div className="rounded-xl border border-border bg-surface p-5 space-y-4">
          <div className="flex items-center gap-2 pb-3 border-b border-border">
            <FileCheck2 className="size-4 text-emerald-500" />
            <h3 className="font-semibold text-text text-sm">Evidence Verification Progress</h3>
          </div>

          <div className="grid grid-cols-4 gap-2 text-center text-xs">
            <div className="rounded-lg border border-border bg-emerald-500/10 p-2 text-emerald-600 dark:text-emerald-400">
              <p className="font-bold text-base">{verification.claims_approved}</p>
              <p className="text-[10px] uppercase font-medium">Approved</p>
            </div>
            <div className="rounded-lg border border-border bg-amber-500/10 p-2 text-amber-600 dark:text-amber-400">
              <p className="font-bold text-base">{verification.claims_pending}</p>
              <p className="text-[10px] uppercase font-medium">Pending</p>
            </div>
            <div className="rounded-lg border border-border bg-purple-500/10 p-2 text-purple-600 dark:text-purple-400">
              <p className="font-bold text-base">{verification.claims_disputed}</p>
              <p className="text-[10px] uppercase font-medium">Disputed</p>
            </div>
            <div className="rounded-lg border border-border bg-red-500/10 p-2 text-red-600 dark:text-red-400">
              <p className="font-bold text-base">{verification.claims_rejected}</p>
              <p className="text-[10px] uppercase font-medium">Rejected</p>
            </div>
          </div>
        </div>

        {/* Top Field Activities */}
        <div className="rounded-xl border border-border bg-surface p-5 space-y-4">
          <div className="flex items-center gap-2 pb-3 border-b border-border">
            <BarChart2 className="size-4 text-accent" />
            <h3 className="font-semibold text-text text-sm">Top Identified Field Activities</h3>
          </div>

          {activities.length === 0 ? (
            <p className="py-6 text-center text-xs text-text-muted">
              No activity observations classified yet.
            </p>
          ) : (
            <div className="space-y-2">
              {activities.slice(0, 5).map((act) => {
                const maxCount = Math.max(...activities.map((a) => a.count), 1);
                const pct = (act.count / maxCount) * 100;
                return (
                  <div key={act.activity} className="space-y-1">
                    <div className="flex justify-between text-xs">
                      <span className="font-medium text-text capitalize">
                        {act.activity.replace(/_/g, " ")}
                      </span>
                      <span className="font-mono text-text-muted">{act.count}</span>
                    </div>
                    <div className="h-1.5 w-full rounded-full bg-surface-muted overflow-hidden">
                      <div
                        className="h-full rounded-full bg-accent"
                        style={{ width: `${pct}%` }}
                      />
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
