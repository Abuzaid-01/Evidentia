"use client";

import { AlertTriangle, CheckCircle2, Images, Loader2, UploadCloud, XCircle } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import type { ReactNode } from "react";

import { PROCESSING_STATES } from "@/components/assets/state-badge";
import { DeleteProject } from "@/components/projects/delete-project";
import { SitesPanel } from "@/components/projects/sites-panel";
import { TaxonomyPanel } from "@/components/projects/taxonomy-panel";
import { LinkButton } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { ErrorState, Skeleton } from "@/components/ui/feedback";
import { PageHeader } from "@/components/ui/page-header";
import { useMe, useProject } from "@/lib/api/hooks";
import { hasRole } from "@/lib/api/types";
import { cn, formatDate } from "@/lib/utils";

function Stat({ label, value, icon, tone, href }: { label: string; value: number; icon: ReactNode; tone: string; href?: string }) {
  const body = (
    <Card className={cn("p-4 transition", href && "hover:border-accent/50")}>
      <div className="flex items-center justify-between">
        <span className="text-xs font-medium uppercase tracking-wider text-text-muted">{label}</span>
        <span className={cn("rounded-lg p-1.5 [&_svg]:size-4", tone)}>{icon}</span>
      </div>
      <p className="mt-2 text-3xl font-semibold tabular-nums">{value}</p>
    </Card>
  );
  return href ? <Link href={href}>{body}</Link> : body;
}

export default function ProjectOverviewPage() {
  const { projectId } = useParams<{ projectId: string }>();
  const project = useProject(projectId);
  const { data: me } = useMe();

  if (project.error) return <ErrorState error={project.error} onRetry={() => project.refetch()} />;
  if (!project.data) return <Skeleton className="h-64" />;

  const p = project.data;
  const byState = p.stats?.by_state ?? {};
  const processing = PROCESSING_STATES.reduce((sum, s) => sum + (byState[s] ?? 0), 0);
  const media = `/projects/${projectId}/media`;

  return (
    <>
      <PageHeader
        eyebrow="Project"
        title={p.name}
        description={
          <>
            {p.description && <span className="block">{p.description}</span>}
            {(p.starts_on || p.ends_on) && (
              <span className="text-text-subtle">
                {formatDate(p.starts_on)} – {formatDate(p.ends_on)}
              </span>
            )}
          </>
        }
        actions={
          <>
            <LinkButton href={media} variant="secondary">
              <Images /> Media library
            </LinkButton>
            {hasRole(me?.role, "contributor") && (
              <LinkButton href={`/projects/${projectId}/upload`}>
                <UploadCloud /> Upload evidence
              </LinkButton>
            )}
          </>
        }
      />

      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <Stat label="Total media" value={p.stats?.assets_total ?? 0} icon={<Images />} tone="bg-surface-muted text-text-muted" href={media} />
        <Stat label="Ready" value={byState.ready ?? 0} icon={<CheckCircle2 />} tone="bg-accent-soft text-accent" href={`${media}?state=ready`} />
        <Stat label="Needs review" value={byState.review_required ?? 0} icon={<AlertTriangle />} tone="bg-warning-soft text-warning" href={`${media}?state=review_required`} />
        <Stat
          label={byState.failed_permanent ? "Failed" : "Processing"}
          value={byState.failed_permanent ?? processing}
          icon={byState.failed_permanent ? <XCircle /> : <Loader2 className={processing ? "animate-spin" : ""} />}
          tone={byState.failed_permanent ? "bg-danger-soft text-danger" : "bg-info-soft text-info"}
        />
      </div>

      <div className="mt-6 grid gap-6 lg:grid-cols-2">
        <SitesPanel projectId={projectId} canEdit={hasRole(me?.role, "manager")} />
        <TaxonomyPanel projectId={projectId} />
      </div>

      {hasRole(me?.role, "manager") && <DeleteProject projectId={projectId} name={p.name} mediaCount={p.stats?.assets_total ?? 0} />}
    </>
  );
}
