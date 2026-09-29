import { Badge } from "@/components/ui/badge";
import { Card, CardHeader } from "@/components/ui/card";
import type { AnalysisRun } from "@/lib/api/types";
import { humanize } from "@/lib/utils";

export function RunsPanel({ runs }: { runs: AnalysisRun[] }) {
  return (
    <Card>
      <CardHeader
        title="Analysis runs"
        description="Every model call is versioned (provider, model, prompt, schema, taxonomy) for audit and re-runs."
      />
      {runs.length === 0 ? (
        <p className="px-5 py-4 text-sm text-text-muted">No analysis yet.</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs">
            <thead className="text-text-subtle">
              <tr>
                <th className="px-5 py-2 font-medium">Task</th>
                <th className="py-2 font-medium">Provider · model</th>
                <th className="py-2 font-medium">Versions</th>
                <th className="py-2 font-medium">Status</th>
                <th className="px-5 py-2 text-right font-medium">Latency</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {runs.map((run) => (
                <tr key={run.id} className="align-top">
                  <td className="px-5 py-2">
                    {humanize(run.task)}
                    <span className="block text-text-subtle">gen {run.generation}</span>
                  </td>
                  <td className="py-2">
                    <span className="font-medium">{run.provider}</span>
                    <span className="block font-mono text-text-muted">{run.model}</span>
                  </td>
                  <td className="py-2 font-mono text-text-muted">
                    {run.model_version && <span className="block">model {run.model_version}</span>}
                    {run.prompt_version && <span className="block">{run.prompt_version}</span>}
                    {run.schema_version && <span className="block">{run.schema_version}</span>}
                    {run.taxonomy_version && <span className="block">taxonomy v{run.taxonomy_version}</span>}
                  </td>
                  <td className="py-2">
                    <Badge tone={run.status === "succeeded" ? "accent" : run.status === "failed" ? "danger" : "info"}>
                      {run.status}
                    </Badge>
                    {run.error && <span className="mt-1 block max-w-xs break-words text-danger">{run.error}</span>}
                  </td>
                  <td className="px-5 py-2 text-right font-mono text-text-muted">
                    {run.latency_ms ? `${run.latency_ms} ms` : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}
