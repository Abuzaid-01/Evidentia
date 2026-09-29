import { Cloud } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Card, CardHeader } from "@/components/ui/card";
import type { AssetDetail } from "@/lib/api/types";
import { formatBytes, formatDate, humanize } from "@/lib/utils";

export function LineagePanel({ asset }: { asset: AssetDetail }) {
  const c = asset.cloudinary;
  return (
    <Card>
      <CardHeader
        title={
          <span className="flex items-center gap-2">
            <Cloud className="size-4 text-accent" /> Cloudinary lineage
          </span>
        }
        description="The original is immutable; every rendition records the exact transformation used."
      />
      <dl className="grid grid-cols-[120px_1fr] gap-x-3 gap-y-1.5 px-5 py-3 text-sm">
        <dt className="text-text-muted">Public ID</dt>
        <dd className="break-all font-mono text-xs">{c.public_id}</dd>
        <dt className="text-text-muted">Asset ID</dt>
        <dd className="break-all font-mono text-xs">{c.asset_id ?? "—"}</dd>
        <dt className="text-text-muted">Version</dt>
        <dd className="font-mono text-xs">{c.version ?? "—"}</dd>
        <dt className="text-text-muted">Folder</dt>
        <dd className="break-all font-mono text-xs">{c.asset_folder ?? "—"}</dd>
        <dt className="text-text-muted">Delivery</dt>
        <dd>
          <Badge tone="accent">{c.delivery_type} · signed URLs only</Badge>
        </dd>
      </dl>
      {asset.derivatives.length > 0 && (
        <div className="border-t border-border">
          <table className="w-full text-left text-xs">
            <thead className="text-text-subtle">
              <tr>
                <th className="px-5 py-2 font-medium">Purpose</th>
                <th className="py-2 font-medium">Transformation</th>
                <th className="py-2 font-medium">Source</th>
                <th className="px-5 py-2 text-right font-medium">Size</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {asset.derivatives.map((d) => (
                <tr key={d.id}>
                  <td className="px-5 py-2">
                    {humanize(d.purpose)}
                    {d.generative && (
                      <Badge tone="warning" className="ml-1">
                        generative
                      </Badge>
                    )}
                  </td>
                  <td className="py-2 font-mono">
                    {d.named_transformation ? `t_${d.named_transformation}` : d.transformation}
                    <span className="block text-text-subtle">{d.transformation}</span>
                  </td>
                  <td className="py-2 text-text-muted">
                    {d.source} · {formatDate(d.created_at)}
                  </td>
                  <td className="px-5 py-2 text-right text-text-muted">{formatBytes(d.bytes)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}
