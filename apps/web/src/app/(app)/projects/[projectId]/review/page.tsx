"use client";

// Basic UI (functional first; styling to be improved later).
import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useParams } from "next/navigation";

import { ErrorState, Skeleton } from "@/components/ui/feedback";
import { PageHeader } from "@/components/ui/page-header";
import { api, unwrap } from "@/lib/api/client";

export default function ReviewQueuePage() {
  const { projectId } = useParams<{ projectId: string }>();
  const queue = useQuery({
    queryKey: ["projects", projectId, "review-queue"],
    queryFn: async () =>
      unwrap(await api.GET("/v1/projects/{project_id}/review-queue", { params: { path: { project_id: projectId } } })),
  });

  return (
    <>
      <PageHeader title="Review queue" description="Highest review priority first. Open an item to approve, reject or edit its observations." />
      {queue.isLoading && <Skeleton className="h-40" />}
      {queue.error && <ErrorState error={queue.error} onRetry={() => queue.refetch()} />}
      {queue.data?.length === 0 && <p className="text-sm text-text-muted">Nothing to review.</p>}
      <ul className="flex flex-col gap-2">
        {queue.data?.map((item) => (
          <li key={item.asset.id} className="flex gap-3 rounded border border-border bg-surface p-2 text-sm">
            {item.asset.thumb_url && (
              // eslint-disable-next-line @next/next/no-img-element
              <img src={item.asset.thumb_url} alt="" className="h-16 w-24 rounded object-cover" />
            )}
            <div className="min-w-0">
              <Link href={`/assets/${item.asset.id}`} className="font-medium text-accent hover:underline">
                {item.asset.caption ?? item.asset.original_filename}
              </Link>
              <div className="text-xs text-text-muted">
                priority {item.asset.review_priority?.toFixed(2) ?? "—"} · {item.pending_observations} pending observation(s)
              </div>
              <div className="text-xs">{(item.review_reasons as string[]).join(" · ")}</div>
            </div>
          </li>
        ))}
      </ul>
    </>
  );
}
