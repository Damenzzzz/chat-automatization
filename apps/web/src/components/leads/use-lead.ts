"use client";

import { useState } from "react";
import { useSWRConfig } from "swr";

import { api, type Schemas } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";

export type LeadRow = Schemas["LeadRow"];
export type LeadPatch = Schemas["LeadIn"];
export type LeadStatus = "new" | "in_progress" | "done" | "cancelled";

type Edited = Partial<
  Pick<LeadRow, "status" | "assignee_id" | "assignee_name" | "cancel_reason" | "remind_at" | "note">
>;

export const OPEN_STATUSES = ["new", "in_progress"];

export function isOpen(status: string): boolean {
  return OPEN_STATUSES.includes(status);
}

export function isOverdue(lead: Pick<LeadRow, "status" | "remind_at">): boolean {
  return (
    Boolean(lead.remind_at) &&
    isOpen(lead.status) &&
    new Date(lead.remind_at as string).getTime() <= Date.now()
  );
}

export function toLocalInput(iso: string | null | undefined): string {
  if (!iso) return "";
  const date = new Date(iso);
  const pad = (value: number) => String(value).padStart(2, "0");
  return (
    `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}` +
    `T${pad(date.getHours())}:${pad(date.getMinutes())}`
  );
}

export function fromLocalInput(value: string): string | null {
  if (!value) return null;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : date.toISOString();
}

/** То, что сервер сделает сам: показать сразу, не дожидаясь ответа. */
function expected(patch: LeadPatch): Edited {
  const next: Edited = {};
  if (patch.status) {
    next.status = patch.status;
    if (patch.status !== "cancelled") next.cancel_reason = null;
    if (!isOpen(patch.status)) next.remind_at = null;
  }
  if ("assignee_id" in patch) next.assignee_id = patch.assignee_id ?? null;
  if ("cancel_reason" in patch) next.cancel_reason = patch.cancel_reason ?? null;
  if ("remind_at" in patch) next.remind_at = patch.remind_at ?? null;
  if ("note" in patch) next.note = patch.note?.trim() || null;
  return next;
}

/** Правка одной заявки: меняем на экране сразу, при ошибке возвращаем как было. */
export function useLeadEdit(source: LeadRow) {
  const { mutate } = useSWRConfig();
  const [state, setState] = useState<{ base: string; edited: Edited }>({
    base: source.updated_at,
    edited: {},
  });
  const [error, setError] = useState<unknown>(null);
  // Пришла свежая строка с сервера — свои правки поверх неё больше не нужны.
  const edited = state.base === source.updated_at ? state.edited : {};
  const lead: LeadRow = { ...source, ...edited };

  function setEdited(next: Edited) {
    setState({ base: source.updated_at, edited: next });
  }

  async function save(patch: LeadPatch) {
    const previous = edited;
    setEdited({ ...previous, ...expected(patch) });
    setError(null);
    try {
      const saved = await unwrap(
        api.PATCH("/leads/{lead_id}", { params: { path: { lead_id: source.id } }, body: patch }),
      );
      setEdited({
        status: saved.status,
        assignee_id: saved.assignee_id,
        assignee_name: saved.assignee_name,
        cancel_reason: saved.cancel_reason,
        remind_at: saved.remind_at,
        note: saved.note,
      });
      void mutate(
        (key) =>
          typeof key === "string" && (key.startsWith("/leads") || key.startsWith("/conversations")),
      );
    } catch (failure) {
      setEdited(previous);
      setError(failure);
    }
  }

  return { lead, error, save };
}
