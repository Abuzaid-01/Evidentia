/**
 * Direct browser -> Cloudinary upload using server-signed parameters.
 *
 * The bytes never pass through our API. Every parameter in `fields` was chosen by the server and is
 * covered by the signature, so it is sent back unchanged. Files larger than `chunkSize` use
 * Cloudinary's chunked upload protocol (X-Unique-Upload-Id + Content-Range).
 */
import type { UploadSignResponse } from "@/lib/api/types";

export type CloudinaryUploadResult = {
  public_id: string;
  version: number;
  signature: string;
  asset_id?: string;
  bytes?: number;
  format?: string;
};

export class UploadAborted extends Error {}

type Options = {
  onProgress?: (fraction: number) => void;
  signal?: AbortSignal;
};

function postForm(
  url: string,
  form: FormData,
  headers: Record<string, string>,
  onProgress: (loaded: number) => void,
  signal?: AbortSignal,
): Promise<Record<string, unknown>> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", url);
    Object.entries(headers).forEach(([k, v]) => xhr.setRequestHeader(k, v));
    xhr.upload.onprogress = (event) => onProgress(event.loaded);
    xhr.onload = () => {
      let body: Record<string, unknown> = {};
      try {
        body = JSON.parse(xhr.responseText || "{}");
      } catch {
        /* non-JSON error page */
      }
      if (xhr.status >= 200 && xhr.status < 300) resolve(body);
      else {
        const message = (body.error as { message?: string } | undefined)?.message;
        reject(new Error(message ?? `Cloudinary upload failed (HTTP ${xhr.status})`));
      }
    };
    xhr.onerror = () => reject(new Error("Network error while uploading to Cloudinary"));
    xhr.onabort = () => reject(new UploadAborted("Upload cancelled"));
    signal?.addEventListener("abort", () => xhr.abort(), { once: true });
    xhr.send(form);
  });
}

function formFor(fields: Record<string, string>, file: Blob, filename: string): FormData {
  const form = new FormData();
  Object.entries(fields).forEach(([k, v]) => form.append(k, v));
  form.append("file", file, filename);
  return form;
}

export async function uploadToCloudinary(
  file: File,
  signed: UploadSignResponse,
  { onProgress, signal }: Options = {},
): Promise<CloudinaryUploadResult> {
  const total = file.size;
  const report = (loaded: number) => onProgress?.(Math.min(1, loaded / total));

  let result: Record<string, unknown>;
  if (total <= signed.chunk_size) {
    result = await postForm(signed.upload_url, formFor(signed.fields, file, file.name), {}, report, signal);
  } else {
    const uploadId = crypto.randomUUID();
    result = {};
    for (let start = 0; start < total; start += signed.chunk_size) {
      const end = Math.min(start + signed.chunk_size, total) - 1;
      result = await postForm(
        signed.upload_url,
        formFor(signed.fields, file.slice(start, end + 1), file.name),
        { "X-Unique-Upload-Id": uploadId, "Content-Range": `bytes ${start}-${end}/${total}` },
        (loaded) => report(start + loaded),
        signal,
      );
    }
  }

  if (typeof result.public_id !== "string" || typeof result.signature !== "string") {
    throw new Error("Cloudinary did not return a signed upload result");
  }
  onProgress?.(1);
  return result as unknown as CloudinaryUploadResult;
}
