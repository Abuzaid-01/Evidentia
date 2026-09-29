"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef } from "react";

import { keys } from "@/lib/api/hooks";
import { authHeader } from "@/lib/api/client";
import { useAuthState } from "@/lib/auth/auth-bridge";
import { config } from "@/lib/config";

export type AssetStateEvent = {
  type: "asset.state_changed";
  asset_id: string;
  project_id: string;
  state: string;
  reason: string | null;
  caption?: string | null;
  top_activity?: string | null;
  at: string;
};

type Listener = (event: AssetStateEvent) => void;
const listeners = new Set<Listener>();

/** Subscribe a component to live asset events (the stream itself is opened once, app-wide). */
export function useAssetEvents(listener: Listener) {
  const ref = useRef(listener);
  useEffect(() => {
    ref.current = listener;
  });
  useEffect(() => {
    const wrapped: Listener = (event) => ref.current(event);
    listeners.add(wrapped);
    return () => {
      listeners.delete(wrapped);
    };
  }, []);
}

function parseBlock(block: string): { event: string; data: string } | null {
  let event = "message";
  const data: string[] = [];
  for (const line of block.split("\n")) {
    if (line.startsWith("event:")) event = line.slice(6).trim();
    else if (line.startsWith("data:")) data.push(line.slice(5).trimStart());
  }
  return data.length ? { event, data: data.join("\n") } : null;
}

/**
 * One SSE connection per tab (fetch-based so it can send the Authorization header), with
 * reconnect/backoff. Every state change refreshes the affected queries.
 */
export function useOrgEventStream() {
  const auth = useAuthState();
  const client = useQueryClient();
  const enabled = auth.ready && auth.signedIn && auth.hasOrganization;

  useEffect(() => {
    if (!enabled) return;
    const controller = new AbortController();
    let attempt = 0;

    const connect = async () => {
      while (!controller.signal.aborted) {
        try {
          const response = await fetch(`${config.apiBaseUrl}/v1/events/stream`, {
            headers: { Accept: "text/event-stream", ...(await authHeader()) },
            signal: controller.signal,
          });
          if (!response.ok || !response.body) throw new Error(`SSE HTTP ${response.status}`);
          attempt = 0;
          const reader = response.body.pipeThrough(new TextDecoderStream()).getReader();
          let buffer = "";
          while (true) {
            const { value, done } = await reader.read();
            if (done) break;
            buffer += value.replace(/\r\n/g, "\n");
            let split: number;
            while ((split = buffer.indexOf("\n\n")) >= 0) {
              const parsed = parseBlock(buffer.slice(0, split));
              buffer = buffer.slice(split + 2);
              if (parsed?.event === "before_after.updated") {
                const event = JSON.parse(parsed.data) as { pair_id: string; project_id: string };
                client.invalidateQueries({ queryKey: keys.pairs(event.project_id) });
                client.invalidateQueries({ queryKey: keys.pair(event.pair_id) });
              }
              if (parsed?.event === "asset.state_changed") {
                const event = JSON.parse(parsed.data) as AssetStateEvent;
                listeners.forEach((listener) => listener(event));
                client.invalidateQueries({ queryKey: keys.assets(event.project_id) });
                client.invalidateQueries({ queryKey: keys.asset(event.asset_id) });
                client.invalidateQueries({ queryKey: keys.project(event.project_id) });
              }
            }
          }
        } catch {
          if (controller.signal.aborted) return;
        }
        attempt += 1;
        const delay = Math.min(30_000, 1000 * 2 ** attempt) * (0.5 + Math.random() / 2);
        await new Promise((resolve) => setTimeout(resolve, delay));
      }
    };
    void connect();
    return () => controller.abort();
  }, [enabled, client]);
}
