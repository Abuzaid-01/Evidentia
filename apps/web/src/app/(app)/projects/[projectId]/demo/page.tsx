"use client";

// Demo mode: the whole evidence workflow on one page, one click per step. Every call is real
// (Cloudinary, AI, database, PDF worker); approvals are made by a separate "Demo reviewer" user.
// The full multi-person workflow stays available on the other pages.
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, FileText, Loader2, Search as SearchIcon, ShieldCheck, Sparkles, UploadCloud } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useState, type FormEvent, type ReactNode } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/form";
import { Uploader } from "@/components/uploads/uploader";
import { api, unwrap } from "@/lib/api/client";
import { keys, useAssets, useMe, useProject } from "@/lib/api/hooks";
import type { AssetSummary, SearchResponse } from "@/lib/api/types";

type ClaimResult = { approved: boolean; steps: string[]; message?: string | null; claim: { id: string; statement: string } };
type ReportResult = { report_id: string; steps: string[]; snapshot: { version: number } };

const READY = new Set(["ready", "review_required"]);

function Step({ n, icon, title, hint, children }: { n: number; icon: ReactNode; title: string; hint: string; children: ReactNode }) {
  return (
    <section className="rounded-xl border border-border bg-surface p-4">
      <div className="mb-3 flex items-center gap-2">
        <span className="flex size-6 items-center justify-center rounded-full bg-accent text-xs font-semibold text-accent-contrast">{n}</span>
        <span className="text-accent [&_svg]:size-4">{icon}</span>
        <h2 className="font-semibold">{title}</h2>
      </div>
      <p className="mb-3 text-xs text-text-muted">{hint}</p>
      {children}
    </section>
  );
}

export default function DemoPage() {
  const { projectId } = useParams<{ projectId: string }>();
  const client = useQueryClient();
  const { data: me } = useMe();
  const { data: project } = useProject(projectId);
  const assets = useAssets(projectId);
  const photos: AssetSummary[] = assets.data?.pages.flatMap((p) => p.items) ?? [];

  const [claims, setClaims] = useState<Record<string, ClaimResult>>({});
  const [busy, setBusy] = useState<string | null>(null);
  const [search, setSearch] = useState<SearchResponse | null>(null);
  const [report, setReport] = useState<ReportResult | null>(null);
  const [html, setHtml] = useState<string | null>(null);

  const snapshots = useQuery({
    queryKey: ["reports", report?.report_id, "snapshots"],
    enabled: !!report,
    queryFn: async () =>
      unwrap(await api.GET("/v1/reports/{report_id}/snapshots", { params: { path: { report_id: report!.report_id } } })),
    refetchInterval: (q) => (q.state.data?.[0]?.pdf_status === "pending" ? 2000 : false),
  });
  const latest = snapshots.data?.[0];

  async function run(key: string, fn: () => Promise<void>) {
    setBusy(key);
    try {
      await fn();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Something went wrong");
    } finally {
      setBusy(null);
    }
  }

  const makeClaim = (asset: AssetSummary) =>
    run(asset.id, async () => {
      const out = unwrap(await api.POST("/v1/demo/assets/{asset_id}/claim", { params: { path: { asset_id: asset.id } }, body: { claim_type: "descriptive" } }));
      setClaims((c) => ({ ...c, [asset.id]: out }));
      if (out.approved) toast.success("Claim approved");
      else toast.warning(out.message ?? "Claim left in review");
      await client.invalidateQueries({ queryKey: keys.assets(projectId) });
    });

  const runSearch = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const query = String(new FormData(event.currentTarget).get("q") || "").trim();
    if (!query) return;
    void run("search", async () => {
      setSearch(unwrap(await api.POST("/v1/search", { body: { project_id: projectId, query, limit: 6, use_llm_planner: false } })));
    });
  };

  const makeReport = () =>
    run("report", async () => {
      setHtml(null);
      setReport(unwrap(await api.POST("/v1/demo/projects/{project_id}/report", { params: { path: { project_id: projectId } }, body: { audience: "internal" } })));
    });

  const snapPath = () => ({ params: { path: { report_id: report!.report_id, version: report!.snapshot.version } } });

  if (me && !me.features.demo_mode) {
    return <p className="text-sm text-text-muted">Demo mode is turned off on this server (DEMO_MODE_ENABLED=false).</p>;
  }

  const approvedCount = Object.values(claims).filter((c) => c.approved).length;

  return (
    <div className="mx-auto flex max-w-5xl flex-col gap-4 text-sm">
      <header>
        <p className="text-xs font-medium uppercase tracking-wider text-accent">Demo mode · {project?.name}</p>
        <h1 className="text-2xl font-semibold">From field photo to verified report</h1>
        <p className="mt-1 text-text-muted">
          Everything here is real: photos go to Cloudinary, AI analyses them, rules check every claim and the PDF is stored privately.
          The only shortcut: approvals are made by a separate <b>Demo reviewer</b> account, so the four-eyes rule still holds.
          The full team workflow is still on the other pages.
        </p>
      </header>

      <Step n={1} icon={<UploadCloud />} title="Upload a field photo" hint="Stored privately in Cloudinary, then analysed by Cloudinary AI (Gemini/Groq as fallback). Watch the status change live.">
        <Uploader projectId={projectId} />
      </Step>

      <Step n={2} icon={<SearchIcon />} title="Search in plain English" hint='Try "man cleaning a manhole". Results explain why they matched and flag words a photo does not mention.'>
        <form onSubmit={runSearch} className="flex gap-2">
          <Input name="q" placeholder="man cleaning a manhole" className="flex-1" />
          <Button type="submit" loading={busy === "search"}>Search</Button>
        </form>
        {search && (
          <ul className="mt-3 flex flex-col gap-2">
            {search.results.length === 0 && <li className="text-text-muted">No matching evidence.</li>}
            {search.results.length > 0 && search.complete_matches === 0 && (
              <li className="text-xs text-warning">No photo matches every word; these are the closest partial matches.</li>
            )}
            {search.results.map((r) => (
              <li key={r.asset.id} className="flex items-center gap-3">
                {r.asset.thumb_url && (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img src={r.asset.thumb_url} alt="" className="h-12 w-16 rounded object-cover" />
                )}
                <div className="min-w-0">
                  <p className="truncate">{r.asset.caption ?? r.asset.original_filename}</p>
                  <p className="text-xs text-text-muted">Why: {r.reasons.join(", ")}</p>
                </div>
              </li>
            ))}
          </ul>
        )}
      </Step>

      <Step n={3} icon={<ShieldCheck />} title="Turn a photo into an approved claim" hint="One click: the reviewer verifies what the AI saw, the AI caption becomes the claim, the best evidence is linked, the AI validates it, and the Demo reviewer approves it.">
        {photos.length === 0 && <p className="text-text-muted">No photos yet: upload one in step 1.</p>}
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {photos.map((a) => {
            const result = claims[a.id];
            const ready = READY.has(a.state);
            return (
              <div key={a.id} className="flex flex-col gap-2 rounded-lg border border-border p-2">
                {a.thumb_url ? (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img src={a.thumb_url} alt="" className="h-32 w-full rounded object-cover" />
                ) : (
                  <div className="flex h-32 items-center justify-center rounded bg-surface-muted text-xs text-text-muted">{a.state}</div>
                )}
                <p className="line-clamp-2 text-xs">{a.caption ?? a.original_filename ?? "Analysing…"}</p>
                {result ? (
                  <div className="text-xs">
                    <p className={result.approved ? "font-medium text-accent" : "font-medium text-warning"}>
                      {result.approved ? "✓ Approved claim" : "Left in review"}:{" "}
                      <Link href={`/claims/${result.claim.id}`} className="underline">{result.claim.statement}</Link>
                    </p>
                    <ul className="mt-1 list-disc pl-4 text-text-muted">{result.steps.map((s) => <li key={s}>{s}</li>)}</ul>
                    {result.message && <p className="mt-1 text-warning">{result.message}</p>}
                  </div>
                ) : (
                  <Button size="sm" disabled={!ready || busy !== null} loading={busy === a.id} onClick={() => makeClaim(a)}>
                    {ready ? "Make claim" : `Waiting (${a.state})`}
                  </Button>
                )}
              </div>
            );
          })}
        </div>
      </Step>

      <Step n={4} icon={<FileText />} title="Publish the evidence report" hint="Uses every approved claim in the project. The AI writes the text; any sentence without a citation or with an unsourced number is thrown out. The published version is frozen and printed to PDF.">
        <div className="flex flex-wrap items-center gap-2">
          <Button loading={busy === "report"} disabled={busy !== null} onClick={makeReport}>
            <Sparkles /> Generate &amp; publish report
          </Button>
          {approvedCount > 0 && <span className="text-xs text-text-muted">{approvedCount} claim(s) approved in this session</span>}
        </div>
        {report && (
          <div className="mt-3 flex flex-col gap-2">
            <ul className="text-xs text-text-muted">
              {report.steps.map((s) => (
                <li key={s} className="flex items-center gap-1"><CheckCircle2 className="size-3 text-accent" /> {s}</li>
              ))}
              <li className="flex items-center gap-1">
                {latest?.pdf_status === "ready" ? <CheckCircle2 className="size-3 text-accent" /> : <Loader2 className="size-3 animate-spin" />}
                PDF: {latest?.pdf_status ?? "pending"}{latest?.pdf_error ? ` (${latest.pdf_error})` : ""}
              </li>
            </ul>
            <div className="flex flex-wrap gap-2">
              <Button size="sm" variant="secondary" disabled={busy !== null}
                onClick={() => run("view", async () => setHtml(unwrap(await api.GET("/v1/reports/{report_id}/snapshots/{version}/html", snapPath())).html))}>
                View report
              </Button>
              <Button size="sm" variant="secondary" disabled={busy !== null}
                onClick={() => run("verify", async () => {
                  const v = unwrap(await api.GET("/v1/reports/{report_id}/snapshots/{version}/verify", snapPath()));
                  if (v.identical) toast.success("Verified: the report rebuilds identically from its frozen record");
                  else toast.error("The report does not match its frozen record");
                })}>
                Verify (tamper check)
              </Button>
              <Button size="sm" variant="secondary" disabled={busy !== null || latest?.pdf_status !== "ready"}
                onClick={() => run("pdf", async () => {
                  const link = unwrap(await api.GET("/v1/reports/{report_id}/snapshots/{version}/pdf", snapPath()));
                  window.open(link.url, "_blank", "noopener");
                })}>
                Download PDF
              </Button>
              <Link href={`/reports/${report.report_id}`} className="self-center text-xs text-accent hover:underline">Open in Report Studio →</Link>
            </div>
            {html && (
              <iframe title="report" srcDoc={html} sandbox="allow-same-origin allow-popups" className="h-[75vh] w-full rounded border border-border bg-white" />
            )}
          </div>
        )}
      </Step>
    </div>
  );
}
