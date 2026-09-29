"use client";

import { Card, CardHeader } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/feedback";
import { useTaxonomy } from "@/lib/api/hooks";

export function TaxonomyPanel({ projectId }: { projectId: string }) {
  const taxonomy = useTaxonomy(projectId);
  return (
    <Card>
      <CardHeader
        title="Activity taxonomy"
        description={
          taxonomy.data
            ? `Version ${taxonomy.data.version}. Each question is asked of every photo via Cloudinary AI Vision.`
            : "What counts as evidence in this project."
        }
      />
      {taxonomy.isLoading ? (
        <div className="p-5">
          <Skeleton className="h-24" />
        </div>
      ) : (
        <ol className="divide-y divide-border">
          {taxonomy.data?.activities.map((activity, index) => (
            <li key={activity.key} className="flex gap-3 px-5 py-3">
              <span className="mt-0.5 font-mono text-xs text-text-subtle">{String(index + 1).padStart(2, "0")}</span>
              <div className="min-w-0">
                <p className="text-sm font-medium">{activity.label}</p>
                <p className="text-xs text-text-muted">{activity.question}</p>
              </div>
            </li>
          ))}
        </ol>
      )}
    </Card>
  );
}
