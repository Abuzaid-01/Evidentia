import { Badge } from "@/components/ui/badge";
import { Card, CardHeader } from "@/components/ui/card";
import type { AssetDetail } from "@/lib/api/types";
import { formatBytes, formatDate, humanize } from "@/lib/utils";

const TRUSTED = new Set(["exif", "device"]);

function SourceBadge({ source }: { source: string }) {
  if (source === "none") return <Badge tone="neutral">unknown</Badge>;
  return <Badge tone={TRUSTED.has(source) ? "info" : "warning"}>{source.toUpperCase()} · unverified</Badge>;
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="grid grid-cols-[120px_1fr] gap-3 py-1.5 text-sm">
      <dt className="text-text-muted">{label}</dt>
      <dd className="min-w-0 break-words">{children}</dd>
    </div>
  );
}

export function ProvenancePanel({ asset }: { asset: AssetDetail }) {
  const flags = (asset.flags ?? {}) as Record<string, unknown>;
  return (
    <Card>
      <CardHeader title="Provenance" description="Where each fact about this file came from." />
      <dl className="px-5 py-3">
        <Row label="Captured">
          <span className="mr-2">{formatDate(asset.capture_time, true)}</span>
          <SourceBadge source={asset.capture_time_source} />
        </Row>
        <Row label="Location">
          {asset.latitude !== null && asset.longitude !== null ? (
            <span className="mr-2 font-mono">
              {asset.latitude?.toFixed(5)}, {asset.longitude?.toFixed(5)}
            </span>
          ) : (
            <span className="mr-2 text-text-muted">No GPS</span>
          )}
          <SourceBadge source={asset.location_source} />
          {typeof flags.geo_outside_site_m === "number" && (
            <Badge tone="warning" className="ml-1">
              {flags.geo_outside_site_m} m outside site
            </Badge>
          )}
        </Row>
        <Row label="Declared">
          {asset.declared_activity ? humanize(asset.declared_activity) : "—"}
          {asset.contributor_note && <span className="block text-xs text-text-muted">“{asset.contributor_note}”</span>}
        </Row>
        <Row label="File">
          {asset.original_filename ?? "—"}
          <span className="block text-xs text-text-muted">
            {asset.format?.toUpperCase()} · {formatBytes(asset.bytes)}
            {asset.width ? ` · ${asset.width}×${asset.height}` : ""}
          </span>
        </Row>
        <Row label="SHA-256">
          <span className="font-mono text-xs">{asset.sha256 ?? "—"}</span>
        </Row>
        <Row label="pHash">
          <span className="font-mono text-xs">{asset.phash_hex ?? "—"}</span>
        </Row>
        {asset.exif && Object.keys(asset.exif).length > 0 && (
          <Row label="EXIF">
            <span className="flex flex-wrap gap-1">
              {Object.entries(asset.exif).map(([k, v]) => (
                <Badge key={k} tone="outline" className="font-mono">
                  {k}: {String(v)}
                </Badge>
              ))}
            </span>
          </Row>
        )}
      </dl>
    </Card>
  );
}
