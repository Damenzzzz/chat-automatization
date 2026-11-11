import createClient from "openapi-fetch";

import type { components, paths } from "./schema";

export type Schemas = components["schemas"];

let refreshing: Promise<boolean> | null = null;

export function refreshSession(): Promise<boolean> {
  refreshing ??= fetch("/auth/refresh", { method: "POST" })
    .then((response) => response.ok)
    .catch(() => false)
    .finally(() => {
      refreshing = null;
    });
  return refreshing;
}

export function goToLogin() {
  const next = window.location.pathname + window.location.search;
  // eslint-disable-next-line @next/next/no-location-assign-relative-destination -- нужна полная перезагрузка: сбросить сессию
  window.location.href = `/login?next=${encodeURIComponent(next)}`;
}

export async function apiFetch(request: Request): Promise<Response> {
  const retry = request.clone();
  const response = await fetch(request);
  if (response.status !== 401) return response;
  if (await refreshSession()) return fetch(retry);
  goToLogin();
  return response;
}

export const api = createClient<paths>({ baseUrl: "/api", fetch: apiFetch });

export const authApi = createClient<paths>({ baseUrl: "" });
