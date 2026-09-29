"use client";

// Report Studio. Basic UI (functional first; styling to be improved later).
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Share2 } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";

import { ShareDialog } from "@/components/share/share-dialog";
import { Button } from "@/components/ui/button";
import { ErrorState, Skeleton } from "@/components/ui/feedback";
import { api, unwrap } from "@/lib/api/client";
import type { ReportDetail } from "@/lib/api/types";

type Sentence = { text: string; cites: { type: "claim" | "metric"; id: string }[] };

export default function ReportStudioPage() {
  const { reportId } = useParams<{ reportId: string }>();
  const client = useQueryClient();
  const [html, setHtml] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [shareOpen, setShareOpen] = useState(false);
  const key = ["reports", reportId];
  const path = { params: { path: { report_id: reportId } } };

  const report = useQuery({
    queryKey: key,
    queryFn: async () => unwrap(await api.GET("/v1/reports/{report_id}", path)),
    // poll while a PDF is being rendered
    refetchInterval: (q) => (q.state.data?.snapshots.some((s) => s.pdf_status === "pending") ? 3000 : false),
  });

  async function run<T>(label: string, fn: () => Promise<T>) {
    setBusy(true);
    try {
      const out = await fn();
      await client.invalidateQueries({ queryKey: key });
      return out;
    } catch (err) {
      toast.error(`${label}: ${err instanceof Error ? err.message : "failed"}`);
    } finally {
      setBusy(false);
    }
  }

  if (report.error) return <ErrorState error={report.error} />;
  if (!report.data) return <Skeleton className="h-64" />;
  const r = report.data;
  const claimRef = new Map(r.claims.map((c, i) => [c.id, `C${i + 1}`]));

  const setClaims = (ids: string[]) =>
    run("Update claims", async () => unwrap(await api.PATCH("/v1/reports/{report_id}", { ...path, body: { claim_ids: ids } })));
  const generate = () => run("Generate", async () => unwrap(await api.POST("/v1/reports/{report_id}/generate", path)));
  const preview = () =>
    run("Preview", async () => setHtml(unwrap(await api.GET("/v1/reports/{report_id}/preview", path)).html));
  const publish = () =>
    run("Publish", async () => {
      const snap = unwrap(await api.POST("/v1/reports/{report_id}/publish", path));
      toast.success(`Published version ${snap.version}`);
    });
  const removeSentence = (section: "summary" | "overview", index: number) =>
    run("Edit narrative", async () => {
      const narrative = (r.narrative ?? {}) as Record<string, Sentence[]>;
      const body = {
        summary: narrative.summary ?? [],
        overview: narrative.overview ?? [],
        [section]: (narrative[section] ?? []).filter((_, i) => i !== index),
      };
      unwrap(await api.PUT("/v1/reports/{report_id}/narrative", { ...path, body }));
    });

  const snapPath = (version: number) => ({ params: { path: { report_id: reportId, version } } });
  const verify = (version: number) =>
    run("Verify", async () => {
      const v = unwrap(await api.GET("/v1/reports/{report_id}/snapshots/{version}/verify", snapPath(version)));
      if (v.identical) toast.success(`v${version} regenerates identically from its manifest`);
      else toast.error(`v${version} does NOT match its manifest`);
    });
  const openPdf = (version: number) =>
    run("PDF", async () => {
      const link = unwrap(await api.GET("/v1/reports/{report_id}/snapshots/{version}/pdf", snapPath(version)));
      window.open(link.url, "_blank", "noopener");
    });
  const rerender = (version: number) =>
    run("Re-render PDF", async () => unwrap(await api.POST("/v1/reports/{report_id}/snapshots/{version}/pdf", snapPath(version))));
  const viewSnapshot = (version: number) =>
    run("Open", async () => setHtml(unwrap(await api.GET("/v1/reports/{report_id}/snapshots/{version}/html", snapPath(version))).html));

  return (
    <div className="space-y-6 text-sm">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <Link href={`/projects/${r.project_id}/reports`} className="text-xs text-accent hover:underline">← Reports</Link>
          <h1 className="text-lg font-semibold">{r.title}</h1>
          <p className="text-xs text-text-muted">
            {r.audience} · {r.period_start ?? "…"} → {r.period_end ?? "…"} · {r.status} · latest version {r.latest_version || "none"}
          </p>
          {r.warnings.map((w) => <p key={w} className="text-xs text-amber-600">⚠ {w}</p>)}
        </div>
        <Button size="sm" variant="secondary" onClick={() => setShareOpen(true)}>
          <Share2 className="size-3.5 mr-1.5" /> Share Publicly
        </Button>
      </div>

      <section>
        <h2 className="mb-1 font-semibold">Included claims</h2>
        <ul className="space-y-1">
          {r.claims.map((c) => (
            <li key={c.id} className="flex gap-2">
              <span className="font-mono text-xs">{claimRef.get(c.id)}</span>
              <Link className="text-accent hover:underline" href={`/claims/${c.id}`}>{c.statement}</Link>
              <span className="text-xs text-text-muted">{c.claim_type} · {c.status}</span>
              <button className="text-xs text-red-600" disabled={busy} onClick={() => setClaims(r.claim_ids.filter((id) => id !== c.id))}>remove</button>
            </li>
          ))}
        </ul>
        {r.candidate_claims.length > 0 && (
          <>
            <h3 className="mt-2 text-xs font-semibold text-text-muted">Other approved claims</h3>
            <ul>
              {r.candidate_claims.map((c) => (
                <li key={c.id} className="flex gap-2">
                  <button className="text-xs text-accent" disabled={busy} onClick={() => setClaims([...r.claim_ids, c.id])}>add</button>
                  <span>{c.statement}</span>
                </li>
              ))}
            </ul>
          </>
        )}
      </section>

      <section>
        <div className="mb-1 flex items-center gap-2">
          <h2 className="font-semibold">Narrative</h2>
          <Button size="sm" loading={busy} onClick={generate}>Generate from claims</Button>
          <Button size="sm" variant="secondary" disabled={busy} onClick={preview}>Preview</Button>
          <Button size="sm" variant="secondary" disabled={busy} onClick={publish}>Publish</Button>
        </div>
        <NarrativeMeta meta={r.narrative_meta} />
        {(["summary", "overview"] as const).map((section) => (
          <div key={section} className="mb-2">
            <h3 className="text-xs font-semibold uppercase text-text-muted">{section}</h3>
            {((r.narrative as Record<string, Sentence[]> | null)?.[section] ?? []).map((s, i) => (
              <p key={i}>
                {s.text}{" "}
                {s.cites.map((c) => (
                  <Link key={c.id} href={c.type === "claim" ? `/claims/${c.id}` : `/projects/${r.project_id}/claims`} className="mr-1 font-mono text-xs text-accent">
                    [{c.type === "claim" ? claimRef.get(c.id) ?? "claim" : "metric"}]
                  </Link>
                ))}
                <button className="text-xs text-red-600" disabled={busy} onClick={() => removeSentence(section, i)}>✕</button>
              </p>
            ))}
          </div>
        ))}
        {r.narrative_problems.length > 0 && (
          <div className="text-xs text-red-600">
            {r.narrative_problems.map((p) => <p key={`${p.section}${p.index}`}>{p.section} #{p.index + 1}: {p.problems.join("; ")}</p>)}
          </div>
        )}
      </section>

      <section>
        <h2 className="mb-1 font-semibold">Published versions</h2>
        <SnapshotTable snapshots={r.snapshots} busy={busy} onView={viewSnapshot} onVerify={verify} onPdf={openPdf} onRerender={rerender} />
      </section>

      {html && (
        <section>
          <div className="mb-1 flex items-center gap-2">
            <h2 className="font-semibold">Rendered report</h2>
            <button className="text-xs text-accent" onClick={() => setHtml(null)}>close</button>
          </div>
          <iframe title="report" srcDoc={html} sandbox="allow-same-origin allow-popups" className="h-[80vh] w-full rounded border border-border bg-white" />
        </section>
      )}

      <ShareDialog
        projectId={r.project_id}
        targetType="report"
        targetId={r.id}
        defaultTitle={`Report: ${r.title}`}
        open={shareOpen}
        onClose={() => setShareOpen(false)}
      />
    </div>
  );
}

function NarrativeMeta({ meta }: { meta: ReportDetail["narrative_meta"] }) {
  if (!meta) return null;
  const rejected = (meta.rejected as { text: string; problems: string[] }[] | undefined) ?? [];
  return (
    <div className="mb-2 text-xs text-text-muted">
      <p>
        Written by: {String(meta.mode)}
        {meta.model ? ` (${String(meta.provider)}/${String(meta.model)})` : ""}
        {meta.reason ? ` · ${String(meta.reason)}` : ""}
        {meta.edited_by ? ` · edited by ${String(meta.edited_by)}` : ""}
      </p>
      {rejected.length > 0 && (
        <details>
          <summary>{rejected.length} sentence(s) rejected by the citation checks</summary>
          {rejected.map((s, i) => <p key={i}>“{s.text}”: {s.problems.join("; ")}</p>)}
        </details>
      )}
    </div>
  );
}

function SnapshotTable({
  snapshots,
  busy,
  onView,
  onVerify,
  onPdf,
  onRerender,
}: {
  snapshots: ReportDetail["snapshots"];
  busy: boolean;
  onView: (v: number) => void;
  onVerify: (v: number) => void;
  onPdf: (v: number) => void;
  onRerender: (v: number) => void;
}) {
  if (snapshots.length === 0) return <p className="text-xs text-text-muted">Not published yet.</p>;
  return (
    <table className="w-full text-left text-xs">
      <thead className="text-text-muted">
        <tr><th>Version</th><th>Published</th><th>Manifest sha256</th><th>PDF</th><th /></tr>
      </thead>
      <tbody>
        {snapshots.map((s) => (
          <tr key={s.id} className="border-t border-border">
            <td>v{s.version}{(s.retracted_claim_ids?.length ?? 0) > 0 && <span className="text-amber-600"> ({s.retracted_claim_ids?.length} claim(s) since retracted)</span>}</td>
            <td>{new Date(s.published_at).toLocaleString()}</td>
            <td className="font-mono">{s.manifest_sha256.slice(0, 16)}…</td>
            <td>{s.pdf_status}{s.pdf_error ? `: ${s.pdf_error}` : ""}</td>
            <td className="space-x-2">
              <button className="text-accent" disabled={busy} onClick={() => onView(s.version)}>view</button>
              <button className="text-accent" disabled={busy} onClick={() => onVerify(s.version)}>verify</button>
              {s.pdf_status === "ready" && <button className="text-accent" disabled={busy} onClick={() => onPdf(s.version)}>download PDF</button>}
              {(s.pdf_status === "failed" || s.pdf_status === "skipped") && <button className="text-accent" disabled={busy} onClick={() => onRerender(s.version)}>retry PDF</button>}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
