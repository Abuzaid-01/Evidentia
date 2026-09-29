"use client";

import { useParams } from "next/navigation";

import { CampaignStudio } from "@/components/campaigns/campaign-studio";
import { PageHeader } from "@/components/ui/page-header";
import { useAssets, useProject } from "@/lib/api/hooks";

export default function CampaignsPage() {
  const { projectId } = useParams<{ projectId: string }>();
  const { data: project } = useProject(projectId);
  const assetsQuery = useAssets(projectId);

  const assets = assetsQuery.data?.pages.flatMap((page) => page.items) ?? [];

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow={project?.name}
        title="Campaign Studio"
        description="Transform approved field evidence into publication-ready social formats with mandatory face redaction and complete transformation lineage."
      />
      <CampaignStudio projectId={projectId} assets={assets} />
    </div>
  );
}
