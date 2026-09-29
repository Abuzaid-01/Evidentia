"use client";

import { CalendarRange, FolderPlus, Images, MapPin, Plus } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { CreateProjectDialog } from "@/components/projects/create-project-dialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { EmptyState, ErrorState, Skeleton } from "@/components/ui/feedback";
import { PageHeader } from "@/components/ui/page-header";
import { useMe, useProjects } from "@/lib/api/hooks";
import { hasRole, type Project } from "@/lib/api/types";
import { formatDate, humanize } from "@/lib/utils";

function ProjectCard({ project }: { project: Project }) {
  const stats = project.stats;
  const review = stats?.by_state?.review_required ?? 0;
  return (
    <Link href={`/projects/${project.id}`}>
      <Card className="group h-full p-5 transition hover:-translate-y-0.5 hover:border-accent/50">
        <div className="flex items-start justify-between gap-3">
          <h3 className="font-semibold group-hover:text-accent">{project.name}</h3>
          {project.status !== "active" && <Badge>{humanize(project.status)}</Badge>}
        </div>
        {project.description && <p className="mt-1 line-clamp-2 text-sm text-text-muted">{project.description}</p>}
        <div className="mt-4 flex flex-wrap gap-x-4 gap-y-1 text-xs text-text-muted">
          <span className="flex items-center gap-1">
            <Images className="size-3.5" /> {stats?.assets_total ?? 0} media
          </span>
          <span className="flex items-center gap-1">
            <MapPin className="size-3.5" /> {stats?.sites ?? 0} sites
          </span>
          {(project.starts_on || project.ends_on) && (
            <span className="flex items-center gap-1">
              <CalendarRange className="size-3.5" /> {formatDate(project.starts_on)} – {formatDate(project.ends_on)}
            </span>
          )}
        </div>
        <div className="mt-4 flex gap-2">
          <Badge tone="outline">{humanize(project.taxonomy_preset)}</Badge>
          {review > 0 && <Badge tone="warning">{review} to review</Badge>}
        </div>
      </Card>
    </Link>
  );
}

export default function ProjectsPage() {
  const { data: me } = useMe();
  const projects = useProjects();
  const [open, setOpen] = useState(false);
  const canCreate = hasRole(me?.role, "manager");

  return (
    <>
      <PageHeader
        eyebrow={me?.organization.name}
        title="Projects"
        description="Each project collects field media from its sites and turns it into verified evidence."
        actions={
          canCreate && (
            <Button onClick={() => setOpen(true)}>
              <Plus /> New project
            </Button>
          )
        }
      />
      {projects.isLoading && (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {[0, 1, 2].map((i) => (
            <Skeleton key={i} className="h-40" />
          ))}
        </div>
      )}
      {projects.error && <ErrorState error={projects.error} onRetry={() => projects.refetch()} />}
      {projects.data?.length === 0 && (
        <EmptyState
          icon={FolderPlus}
          title="No projects yet"
          description={canCreate ? "Create your first project to start collecting evidence." : "Ask a manager to create a project."}
          action={canCreate && <Button onClick={() => setOpen(true)}>Create project</Button>}
        />
      )}
      {!!projects.data?.length && (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {projects.data.map((project) => (
            <ProjectCard key={project.id} project={project} />
          ))}
        </div>
      )}
      <CreateProjectDialog open={open} onClose={() => setOpen(false)} />
    </>
  );
}
