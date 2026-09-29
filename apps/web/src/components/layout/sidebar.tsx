"use client";

import {
  BarChart3,
  ClipboardCheck,
  Cloud,
  FileCheck2,
  FileText,
  FolderKanban,
  GitCompareArrows,
  Images,
  LayoutDashboard,
  MapPin,
  Play,
  Search,
  Sparkles,
  UploadCloud,
  Webhook,
} from "lucide-react";
import Link from "next/link";
import { useParams, usePathname } from "next/navigation";
import type { ReactNode } from "react";

import { useMe, useProject } from "@/lib/api/hooks";
import { cn } from "@/lib/utils";

import { IdentityMenu } from "./identity-menu";
import { Logo } from "./logo";

function NavLink({ href, icon, children, exact }: { href: string; icon: ReactNode; children: ReactNode; exact?: boolean }) {
  const pathname = usePathname();
  const active = exact ? pathname === href : pathname === href || pathname.startsWith(`${href}/`);
  return (
    <Link
      href={href}
      className={cn(
        "flex items-center gap-2.5 rounded-lg px-3 py-2 text-sm transition-colors [&_svg]:size-4",
        active ? "bg-accent-soft font-medium text-accent" : "text-text-muted hover:bg-surface-muted hover:text-text",
      )}
    >
      {icon}
      <span className="truncate">{children}</span>
    </Link>
  );
}

function ProjectNav({ projectId }: { projectId: string }) {
  const { data: project } = useProject(projectId);
  const { data: me } = useMe();
  const base = `/projects/${projectId}`;
  return (
    <div className="mt-6">
      <p className="mb-2 truncate px-3 text-xs font-medium uppercase tracking-wider text-text-subtle">
        {project?.name ?? "Project"}
      </p>
      <nav className="flex flex-col gap-0.5">
        {me?.features.demo_mode && (
          <NavLink href={`${base}/demo`} icon={<Play />}>
            Demo mode
          </NavLink>
        )}
        <NavLink href={base} icon={<LayoutDashboard />} exact>
          Overview
        </NavLink>
        <NavLink href={`${base}/upload`} icon={<UploadCloud />}>
          Upload evidence
        </NavLink>
        <NavLink href={`${base}/media`} icon={<Images />}>
          Media library
        </NavLink>
        <NavLink href={`${base}/map`} icon={<MapPin />}>
          Map & Timeline
        </NavLink>
        <NavLink href={`${base}/search`} icon={<Search />}>
          Search
        </NavLink>
        <NavLink href={`${base}/review`} icon={<ClipboardCheck />}>
          Review queue
        </NavLink>
        <NavLink href={`${base}/before-after`} icon={<GitCompareArrows />}>
          Before / after
        </NavLink>
        <NavLink href={`${base}/claims`} icon={<FileCheck2 />}>
          Claims
        </NavLink>
        <NavLink href={`${base}/reports`} icon={<FileText />}>
          Reports
        </NavLink>
        <NavLink href={`${base}/campaigns`} icon={<Sparkles />}>
          Campaign Studio
        </NavLink>
        <NavLink href={`${base}/analytics`} icon={<BarChart3 />}>
          Analytics & Costs
        </NavLink>
      </nav>
    </div>
  );
}

function StatusDot({ ok }: { ok: boolean }) {
  return <span className={cn("size-2 rounded-full", ok ? "bg-accent" : "bg-text-subtle")} />;
}

export function Sidebar() {
  const params = useParams<{ projectId?: string }>();
  const { data: me } = useMe();

  return (
    <aside className="sticky top-0 flex h-screen w-64 shrink-0 flex-col border-r border-border bg-surface/60 px-3 py-5 backdrop-blur">
      <Link href="/projects" className="px-3">
        <Logo />
      </Link>
      <nav className="mt-8 flex flex-col gap-0.5">
        <NavLink href="/projects" icon={<FolderKanban />} exact>
          All projects
        </NavLink>
      </nav>
      {params.projectId && <ProjectNav projectId={params.projectId} />}

      <div className="mt-auto flex flex-col gap-3">
        {me && (
          <div className="space-y-1.5 px-3 text-xs text-text-muted">
            <div className="flex items-center gap-2">
              <Cloud className="size-3.5" />
              <span className="flex-1 truncate">{me.cloudinary_cloud_name ?? "Cloudinary"}</span>
              <StatusDot ok={me.features.cloudinary ?? false} />
            </div>
            <div className="flex items-center gap-2">
              <Webhook className="size-3.5" />
              <span className="flex-1">Webhooks</span>
              <StatusDot ok={me.features.webhooks ?? false} />
            </div>
          </div>
        )}
        <IdentityMenu />
      </div>
    </aside>
  );
}
