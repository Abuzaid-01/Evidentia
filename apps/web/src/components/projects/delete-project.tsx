"use client";

import { useQueryClient } from "@tanstack/react-query";
import { Trash2 } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { Input } from "@/components/ui/form";
import { api, unwrap } from "@/lib/api/client";
import { keys } from "@/lib/api/hooks";

/** "Danger zone" card: delete a project after typing its exact name. Managers and admins only. */
export function DeleteProject({ projectId, name, mediaCount }: { projectId: string; name: string; mediaCount: number }) {
  const router = useRouter();
  const client = useQueryClient();
  const [open, setOpen] = useState(false);
  const [typed, setTyped] = useState("");
  const [deleting, setDeleting] = useState(false);

  async function remove() {
    setDeleting(true);
    try {
      const out = unwrap(
        await api.DELETE("/v1/projects/{project_id}", {
          params: { path: { project_id: projectId }, query: { confirm_name: typed } },
        }),
      );
      client.removeQueries({ queryKey: keys.project(projectId) });
      await client.invalidateQueries({ queryKey: keys.projects });
      toast.success(
        `Deleted "${out.name}": ${out.assets} media, ${out.claims} claims, ${out.reports} reports` +
          (out.cloudinary_files_queued ? `. Removing ${out.cloudinary_files_queued} files from Cloudinary.` : "."),
      );
      router.push("/projects");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not delete the project");
      setDeleting(false);
    }
  }

  return (
    <section className="mt-10 rounded-xl border border-danger/40 p-5">
      <h2 className="text-sm font-semibold text-danger">Danger zone</h2>
      <div className="mt-2 flex flex-wrap items-center justify-between gap-3">
        <p className="max-w-xl text-sm text-text-muted">
          Delete this project and everything in it: {mediaCount} media files (also removed from Cloudinary), their AI
          analysis, claims, metrics and reports. This cannot be undone.
        </p>
        <Button variant="danger" onClick={() => { setTyped(""); setOpen(true); }}>
          <Trash2 /> Delete project
        </Button>
      </div>

      <Dialog
        open={open}
        onClose={() => !deleting && setOpen(false)}
        title="Delete this project?"
        description="Everything in it is permanently removed, including its files in Cloudinary. An audit record of the deletion is kept."
      >
        <label className="text-sm">
          Type <b className="font-mono">{name}</b> to confirm:
          <Input value={typed} onChange={(e) => setTyped(e.target.value)} autoFocus className="mt-2" placeholder={name} disabled={deleting} />
        </label>
        <div className="mt-5 flex justify-end gap-2">
          <Button variant="secondary" onClick={() => setOpen(false)} disabled={deleting}>Cancel</Button>
          <Button variant="danger" loading={deleting} disabled={typed.trim() !== name} onClick={remove}>
            {!deleting && <Trash2 />} Delete forever
          </Button>
        </div>
      </Dialog>
    </section>
  );
}
