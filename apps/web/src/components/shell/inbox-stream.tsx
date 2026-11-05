"use client";

import { useEffect } from "react";
import { useSWRConfig } from "swr";

import { api } from "@/lib/api/client";

const RECONNECT_MS = 3000;

export function InboxStream() {
  const { mutate } = useSWRConfig();

  useEffect(() => {
    let source: EventSource | null = null;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let stopped = false;

    function connect() {
      source = new EventSource("/api/conversations/stream");
      source.addEventListener("change", (event) => {
        const { leads } = JSON.parse((event as MessageEvent<string>).data) as { leads: boolean };
        void mutate((key) => typeof key === "string" && key.startsWith("/conversations"));
        if (leads) void mutate((key) => typeof key === "string" && key.startsWith("/leads"));
      });
      source.onerror = () => {
        source?.close();
        timer = setTimeout(async () => {
          await api.GET("/me");
          if (!stopped) connect();
        }, RECONNECT_MS);
      };
    }

    connect();
    return () => {
      stopped = true;
      clearTimeout(timer);
      source?.close();
    };
  }, [mutate]);

  return null;
}
