"use client";

import { useParams } from "next/navigation";

import { Uploader } from "@/components/uploads/uploader";
import { PageHeader } from "@/components/ui/page-header";
import { useProject } from "@/lib/api/hooks";

export default function UploadPage() {
  const { projectId } = useParams<{ projectId: string }>();
  const { data: project } = useProject(projectId);
  return (
    <>
      <PageHeader
        eyebrow={project?.name}
        title="Upload evidence"
        description="Each file is stored privately in Cloudinary, then registered, checked for duplicates and analysed by AI. Watch it happen live."
      />
      <Uploader projectId={projectId} />
    </>
  );
}
