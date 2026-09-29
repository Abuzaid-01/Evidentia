import createClient, { type Middleware } from "openapi-fetch";

import { config } from "@/lib/config";

import type { paths } from "./schema";

type TokenGetter = () => Promise<string | null>;
let tokenGetter: TokenGetter = async () => null;

/** Called by the auth layer so every API request carries the current session token. */
export function setTokenGetter(getter: TokenGetter) {
  tokenGetter = getter;
}

export async function authHeader(): Promise<Record<string, string>> {
  const token = await tokenGetter();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

const auth: Middleware = {
  async onRequest({ request }) {
    const token = await tokenGetter();
    if (token) request.headers.set("Authorization", `Bearer ${token}`);
    return request;
  },
};

export const api = createClient<paths>({ baseUrl: config.apiBaseUrl });
api.use(auth);

export type ApiErrorBody = { error?: { code?: string; message?: string; details?: unknown } };

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly code?: string,
    readonly details?: unknown,
  ) {
    super(message);
  }
}

/** Unwrap an openapi-fetch result: return data, or throw a typed ApiError. */
export function unwrap<T>(result: { data?: T; error?: unknown; response: Response }): T {
  if (result.error !== undefined || result.data === undefined) {
    const body = (result.error ?? {}) as ApiErrorBody;
    throw new ApiError(
      body.error?.message ?? `Request failed (${result.response.status})`,
      result.response.status,
      body.error?.code,
      body.error?.details,
    );
  }
  return result.data;
}
