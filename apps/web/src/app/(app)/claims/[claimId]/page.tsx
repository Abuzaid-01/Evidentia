"use client";

// Claim workspace: a guided flow (add proof -> AI check -> submit -> approval) that shows only the
// actions that make sense right now. Same API as before; the full four-eyes workflow is unchanged.
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, CheckCircle2, Circle, ImageIcon, Link2, Lock, ShieldCheck, Sparkles, Trash2, X } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useState, type ReactNode } from "react";
import { toast } from "sonner";

import { Badge, type BadgeTone } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { ErrorState, Skeleton } from "@/components/ui/feedback";
import { Input, Select } from "@/components/ui/form";
import { api, unwrap } from "@/lib/api/client";
import { useAssets, useMe } from "@/lib/api/hooks";
import { hasRole } from "@/lib/api/types";
import { cn } from "@/lib/utils";

type Relation = "supports" | "contradicts" | "context";

const STATUS_TONE: Record<string, BadgeTone> = {
  draft: "neutral",
  in_review: "warning",
  approved: "accent",
  rejected: "danger",
  retracted: "outline",
};
const SUPPORT_TONE: Record<string, BadgeTone> = {
  unsupported: "danger",
  proposed: "info",
  reviewed: "info",
  verified: "accent",
};
const VERDICT_TONE: Record<string, BadgeTone> = {
  supported: "accent",
  partially_supported: "warning",
  not_supported: "danger",
  not_checked: "neutral",
};

function label(value: string) {
  return value.replace(/_/g, " ");
}

function Step({ done, active, n, title }: { done: boolean; active: boolean; n: number; title: string }) {
  return (
    <div className="flex flex-1 items-center gap-2">
      <span
        className={cn(
          "flex size-7 shrink-0 items-center justify-center rounded-full border text-xs font-semibold transition-colors",
          done && "border-accent bg-accent text-accent-contrast",
          active && !done && "border-accent text-accent ring-4 ring-accent/15",
          !done && !active && "border-border text-text-subtle",
        )}
      >
        {done ? <Check className="size-4" /> : n}
      </span>
      <span className={cn("text-xs font-medium", done || active ? "text-text" : "text-text-subtle")}>{title}</span>
    </div>
  );
}

export default function ClaimPage() {
  const { claimId } = useParams<{ claimId: string }>();
  const client = useQueryClient();
  const { data: me } = useMe();
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [pickedAsset, setPickedAsset] = useState<string | null>(null);
  const [relation, setRelation] = useState<Relation>("supports");

  const key = ["claims", claimId];
  const path = { params: { path: { claim_id: claimId } } };
  const claim = useQuery({
    queryKey: key,
    queryFn: async () => unwrap(await api.GET("/v1/claims/{claim_id}", path)),
  });
  const projectId = claim.data?.project_id ?? "";
  const metrics = useQuery({
    queryKey: ["projects", projectId, "metrics"],
    enabled: !!projectId,
    queryFn: async () => unwrap(await api.GET("/v1/projects/{project_id}/metrics", { params: { path: { project_id: projectId } } })),
  });
  const photos = useAssets(projectId);
  const picked = useQuery({
    queryKey: ["assets", pickedAsset],
    enabled: !!pickedAsset,
    queryFn: async () => unwrap(await api.GET("/v1/assets/{asset_id}", { params: { path: { asset_id: pickedAsset! } } })),
  });

  async function run(id: string, success: string | null, call: () => Promise<{ error?: unknown; data?: unknown; response: Response }>) {
    setBusy(id);
    try {
      unwrap(await call());
      await client.invalidateQueries({ queryKey: key });
      await client.invalidateQueries({ queryKey: ["projects", projectId, "claims"] });
      if (success) toast.success(success);
      return true;
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Something went wrong");
      return false;
    } finally {
      setBusy(null);
    }
  }

  if (claim.error) return <ErrorState error={claim.error} />;
  if (!claim.data) return <Skeleton className="h-96" />;

  const c = claim.data;
  const rules = c.rule_check as { passed?: boolean; problems?: string[] } | null;
  const validation = c.validation as { reasoning?: string; unsupported_parts?: string[]; reason?: string; model?: string } | null;
  const rulesOk = !!rules?.passed;
  const editable = c.status === "draft" || c.status === "rejected";
  const isAuthor = !!me && c.created_by_id === me.user.id;
  const canReview = hasRole(me?.role, "reviewer") && (!isAuthor || me?.role === "admin");
  const linkedMetricIds = new Set(c.metrics.map((m) => m.id));
  const linkedKeys = new Set(c.evidence.map((e) => `${e.asset_id}:${e.observation_id ?? ""}`));
  const photoList = photos.data?.pages.flatMap((p) => p.items).filter((a) => a.state === "ready" || a.state === "review_required") ?? [];

  const steps = [
    { title: "Add proof", done: rulesOk },
    { title: "AI check", done: !!c.validated_at },
    { title: "Submit", done: c.status === "in_review" || c.status === "approved" },
    { title: "Approved", done: c.status === "approved" },
  ];
  const current = steps.findIndex((s) => !s.done);

  const validate = () =>
    run("validate", null, () => api.POST("/v1/claims/{claim_id}/validate", path)).then(async (ok) => {
      if (!ok) return;
      const fresh = await client.fetchQuery({ queryKey: key, queryFn: async () => unwrap(await api.GET("/v1/claims/{claim_id}", path)) });
      toast.success(`AI check: ${label(fresh.validation_verdict ?? "done")}`);
    });
  const decide = (action: "submit" | "approve" | "reject" | "retract", message: string) => {
    const opts = { ...path, body: { note: note || null, override: false } };
    const call = {
      submit: () => api.POST("/v1/claims/{claim_id}/submit", opts),
      approve: () => api.POST("/v1/claims/{claim_id}/approve", opts),
      reject: () => api.POST("/v1/claims/{claim_id}/reject", opts),
      retract: () => api.POST("/v1/claims/{claim_id}/retract", opts),
    }[action];
    return run(action, message, call).then((ok) => ok && setNote(""));
  };
  const demoApprove = () => run("demo", "Approved by the Demo reviewer", () => api.POST("/v1/demo/claims/{claim_id}/approve", path));
  const link = (assetId: string, observationId: string | null) =>
    run(`link:${assetId}:${observationId ?? ""}`, "Proof linked", () =>
      api.POST("/v1/claims/{claim_id}/evidence", { ...path, body: { asset_id: assetId, observation_id: observationId, relation } }),
    );

  let nextStep: ReactNode;
  if (c.status === "approved") {
    nextStep = (
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="flex items-center gap-2 text-accent">
          <ShieldCheck className="size-5" /> Approved{c.decision_note ? `: “${c.decision_note}”` : ""}. This claim can now go into reports.
        </p>
        <Link href={`/projects/${c.project_id}/reports`} className="text-sm font-medium text-accent hover:underline">Go to Reports →</Link>
      </div>
    );
  } else if (c.status === "retracted") {
    nextStep = <p className="flex items-center gap-2 text-text-muted"><Lock className="size-4" /> Retracted{c.decision_note ? `: “${c.decision_note}”` : ""}. It can no longer be used.</p>;
  } else if (c.status === "in_review") {
    nextStep = canReview ? (
      <div className="flex flex-col gap-3">
        <p className="text-text-muted">Check the proof below, then decide. A note is required to reject.</p>
        <div className="flex flex-wrap items-center gap-2">
          <Input value={note} onChange={(e) => setNote(e.target.value)} placeholder="Note, e.g. photos checked" className="min-w-60 flex-1" />
          {!c.validated_at && (
            <Button variant="secondary" loading={busy === "validate"} disabled={!!busy} onClick={validate}><Sparkles /> Check with AI first</Button>
          )}
          <Button loading={busy === "approve"} disabled={!!busy || !c.validated_at} onClick={() => decide("approve", "Claim approved")}>
            <CheckCircle2 /> Approve
          </Button>
          <Button variant="danger" loading={busy === "reject"} disabled={!!busy || !note.trim()} onClick={() => decide("reject", "Claim rejected")}>
            <X /> Reject
          </Button>
        </div>
      </div>
    ) : (
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-text-muted">
          {isAuthor
            ? "Waiting for a second person to approve. You wrote this claim, so you can't approve it yourself (four-eyes rule)."
            : "Waiting for a reviewer to approve."}
        </p>
        {me?.features.demo_mode && (
          <Button variant="secondary" loading={busy === "demo"} disabled={!!busy} onClick={demoApprove}>
            <ShieldCheck /> Approve with Demo reviewer
          </Button>
        )}
      </div>
    );
  } else {
    nextStep = (
      <div className="flex flex-col gap-3">
        {!rulesOk ? (
          <div className="text-text-muted">
            <p className="font-medium text-text">Add proof first.</p>
            <ul className="mt-1 list-disc pl-5 text-xs">{rules?.problems?.map((p) => <li key={p}>{p}</li>)}</ul>
          </div>
        ) : (
          <p className="text-text-muted">
            {c.validated_at ? "Proof is in place and the AI has checked it. Send it for approval." : "Proof is in place. Let the AI check the claim against it, then submit."}
          </p>
        )}
        <div className="flex flex-wrap gap-2">
          <Button variant={c.validated_at ? "secondary" : "primary"} loading={busy === "validate"} disabled={!!busy || !rulesOk} onClick={validate}>
            <Sparkles /> {c.validated_at ? "Check again" : "Check with AI"}
          </Button>
          <Button variant={c.validated_at ? "primary" : "secondary"} loading={busy === "submit"} disabled={!!busy || !rulesOk} onClick={() => decide("submit", "Sent for approval")}>
            Submit for approval
          </Button>
        </div>
      </div>
    );
  }

  return (
    <div className="mx-auto flex max-w-5xl flex-col gap-5 text-sm">
      <header>
        <Link href={`/projects/${c.project_id}/claims`} className="text-xs text-accent hover:underline">← All claims</Link>
        <h1 className="mt-2 font-serif text-2xl font-semibold leading-snug">{c.statement}</h1>
        <div className="mt-2 flex flex-wrap gap-2">
          <Badge tone="outline">{label(c.claim_type)}</Badge>
          <Badge tone={STATUS_TONE[c.status]}>{label(c.status)}</Badge>
          <Badge tone={SUPPORT_TONE[c.support_level]}>support: {c.support_level}</Badge>
        </div>
      </header>

      <div className="flex flex-wrap gap-3 rounded-xl border border-border bg-surface px-4 py-3">
        {steps.map((s, i) => (
          <Step key={s.title} n={i + 1} title={s.title} done={s.done} active={i === current} />
        ))}
      </div>

      <Card className="border-accent/30">
        <CardHeader title="Next step" />
        <CardBody>{nextStep}</CardBody>
      </Card>

      {validation && (
        <Card>
          <CardHeader
            title="AI check"
            description={validation.model ? `Checked by ${validation.model}, against the linked proof only` : "The AI could not run; human review decides"}
            action={c.validation_verdict ? <Badge tone={VERDICT_TONE[c.validation_verdict]}>{label(c.validation_verdict)}</Badge> : null}
          />
          <CardBody className="text-text-muted">
            <p>
              {validation.reasoning ??
                (validation.reason === "LLM unavailable"
                  ? "The AI service was busy or over its free limit, so a person made the decision instead."
                  : validation.reason)}
            </p>
            {!!validation.unsupported_parts?.length && (
              <p className="mt-2 text-warning">Not backed by the proof: {validation.unsupported_parts.join("; ")}</p>
            )}
          </CardBody>
        </Card>
      )}

      <Card>
        <CardHeader title="Proof" description="Photos and what they verifiably show. Only human-verified observations count as proof." />
        <CardBody className="flex flex-col gap-4">
          {c.evidence.length === 0 && <p className="text-text-muted">No proof linked yet.</p>}
          <div className="grid gap-3 sm:grid-cols-2">
            {c.evidence.map((e) => (
              <div key={e.id} className="flex gap-3 rounded-lg border border-border p-2">
                {e.thumb_url ? (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img src={e.thumb_url} alt="" className="h-16 w-20 shrink-0 rounded object-cover" />
                ) : (
                  <div className="flex h-16 w-20 shrink-0 items-center justify-center rounded bg-surface-muted"><ImageIcon className="size-5 text-text-subtle" /></div>
                )}
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <Badge tone={e.verified ? "accent" : "warning"}>{e.verified ? "verified" : "not verified"}</Badge>
                    <span className="text-xs text-text-muted">{e.relation}</span>
                  </div>
                  <p className="mt-1 truncate text-xs">{e.pair_summary ?? e.observation_summary ?? "Whole photo"}</p>
                  {e.pair_id ? (
                    <Link href={`/before-after/${e.pair_id}`} className="text-xs text-accent hover:underline">Open comparison</Link>
                  ) : (
                    <Link href={`/assets/${e.asset_id}`} className="block truncate text-xs text-accent hover:underline">{e.asset_caption ?? "Open photo"}</Link>
                  )}
                </div>
                {editable && (
                  <Button
                    size="icon"
                    variant="ghost"
                    aria-label="Remove proof"
                    loading={busy === `remove:${e.id}`}
                    disabled={!!busy}
                    onClick={() => run(`remove:${e.id}`, "Proof removed", () => api.DELETE("/v1/claims/{claim_id}/evidence/{link_id}", { params: { path: { claim_id: claimId, link_id: e.id } } }))}
                  >
                    {busy !== `remove:${e.id}` && <Trash2 />}
                  </Button>
                )}
              </div>
            ))}
          </div>

          {editable && (
            <div className="rounded-lg border border-dashed border-border p-3">
              <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
                <p className="font-medium">Add proof: pick a photo</p>
                <label className="flex items-center gap-2 text-xs text-text-muted">
                  This photo
                  <Select value={relation} onChange={(e) => setRelation(e.target.value as Relation)} className="h-8 w-48">
                    <option value="supports">supports the claim</option>
                    <option value="contradicts">contradicts it</option>
                    <option value="context">gives context</option>
                  </Select>
                </label>
              </div>
              {photoList.length === 0 && <p className="text-xs text-text-muted">No analysed photos in this project yet.</p>}
              <div className="grid grid-cols-3 gap-2 sm:grid-cols-5 lg:grid-cols-6">
                {photoList.map((a) => (
                  <button
                    key={a.id}
                    type="button"
                    onClick={() => setPickedAsset(pickedAsset === a.id ? null : a.id)}
                    className={cn(
                      "overflow-hidden rounded-lg border-2 transition-all hover:border-accent/60",
                      pickedAsset === a.id ? "border-accent ring-4 ring-accent/15" : "border-transparent",
                    )}
                    title={a.caption ?? a.original_filename ?? ""}
                  >
                    {a.thumb_url ? (
                      // eslint-disable-next-line @next/next/no-img-element
                      <img src={a.thumb_url} alt="" className="aspect-[4/3] w-full object-cover" />
                    ) : (
                      <div className="flex aspect-[4/3] items-center justify-center bg-surface-muted"><ImageIcon className="size-5 text-text-subtle" /></div>
                    )}
                  </button>
                ))}
              </div>

              {pickedAsset && (
                <div className="mt-3 rounded-lg bg-surface-muted p-3">
                  {!picked.data ? (
                    <Skeleton className="h-16" />
                  ) : (
                    <>
                      <p className="text-xs text-text-muted">{picked.data.caption ?? picked.data.original_filename}</p>
                      <p className="mt-2 text-xs font-medium">Click what this photo proves:</p>
                      <div className="mt-2 flex flex-wrap gap-2">
                        {picked.data.observations
                          .filter((o) => o.status === "verified" || o.status === "proposed")
                          // skip what can't prove a claim: quality/privacy flags, the raw caption, "other"
                          .filter((o) => !["quality", "sensitive"].includes(o.ontology_type))
                          .filter((o) => o.subject !== "other" && !(o.ontology_type === "scene" && o.subject === "image"))
                          .map((o) => {
                            const linked = linkedKeys.has(`${pickedAsset}:${o.id}`);
                            const verified = o.status === "verified";
                            return (
                              <button
                                key={o.id}
                                type="button"
                                disabled={linked || !!busy}
                                onClick={() => link(pickedAsset, o.id)}
                                className={cn(
                                  "flex items-center gap-1 rounded-full border px-3 py-1 text-xs transition-all active:scale-95 disabled:opacity-60",
                                  verified ? "border-accent/40 bg-accent-soft text-accent hover:border-accent" : "border-border text-text-muted hover:border-text-subtle",
                                )}
                                title={verified ? "Verified by a reviewer" : "Not verified yet: review the photo first for it to count as proof"}
                              >
                                {linked ? <Check className="size-3" /> : verified ? <Link2 className="size-3" /> : <Circle className="size-3" />}
                                {label(o.subject)} {o.predicate !== "visible" && o.predicate !== "depicted" ? label(o.predicate) : ""}
                                {o.confidence != null && <span className="opacity-60">{Math.round(o.confidence * 100)}%</span>}
                              </button>
                            );
                          })}
                        <Button size="sm" variant="secondary" loading={busy === `link:${pickedAsset}:`} disabled={!!busy || linkedKeys.has(`${pickedAsset}:`)} onClick={() => link(pickedAsset, null)}>
                          Whole photo
                        </Button>
                      </div>
                      <p className="mt-2 text-xs text-text-subtle">Green = verified by a reviewer (counts as proof). Grey = AI only; review the photo first.</p>
                    </>
                  )}
                </div>
              )}
            </div>
          )}
        </CardBody>
      </Card>

      <Card>
        <CardHeader title="Numbers" description="Only needed if the claim states a number: every number must match a metric with a declared source." />
        <CardBody>
          {metrics.data?.length === 0 && (
            <p className="text-text-muted">
              No metrics in this project yet. <Link href={`/projects/${c.project_id}/claims`} className="text-accent hover:underline">Add one on the Claims page</Link>.
            </p>
          )}
          <div className="flex flex-col gap-2">
            {metrics.data?.map((m) => {
              const on = linkedMetricIds.has(m.id);
              const mpath = { params: { path: { claim_id: claimId, metric_id: m.id } } };
              return (
                <button
                  key={m.id}
                  type="button"
                  disabled={!editable || !!busy}
                  onClick={() =>
                    run(`metric:${m.id}`, on ? "Metric unlinked" : "Metric linked", () =>
                      on ? api.DELETE("/v1/claims/{claim_id}/metrics/{metric_id}", mpath) : api.PUT("/v1/claims/{claim_id}/metrics/{metric_id}", mpath),
                    )
                  }
                  className={cn(
                    "flex items-center justify-between gap-3 rounded-lg border px-3 py-2 text-left transition-all active:scale-[0.99] disabled:cursor-default disabled:opacity-70",
                    on ? "border-accent/50 bg-accent-soft" : "border-border hover:border-text-subtle",
                  )}
                >
                  <span>
                    <b>{m.name}</b> = {Number(m.value)} {m.unit}
                    <span className="ml-2 text-xs text-text-muted">{label(m.source_type)}: {m.source_reference}</span>
                  </span>
                  <Badge tone={on ? "accent" : "outline"}>{busy === `metric:${m.id}` ? "…" : on ? "linked" : "link"}</Badge>
                </button>
              );
            })}
          </div>
        </CardBody>
      </Card>

      {c.status === "approved" && hasRole(me?.role, "manager") && (
        <details className="rounded-xl border border-border p-4 text-xs text-text-muted">
          <summary className="font-medium">Retract this claim</summary>
          <p className="mt-2">Retracting removes it from future reports; published reports keep it, flagged as retracted.</p>
          <div className="mt-2 flex gap-2">
            <Input value={note} onChange={(e) => setNote(e.target.value)} placeholder="Why? (required)" className="flex-1" />
            <Button variant="danger" size="sm" loading={busy === "retract"} disabled={!!busy || !note.trim()} onClick={() => decide("retract", "Claim retracted")}>
              Retract
            </Button>
          </div>
        </details>
      )}
    </div>
  );
}
