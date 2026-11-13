"use client";

import useSWR from "swr";

import { api, type Schemas } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";

export type Member = Schemas["MemberOut"];

export function memberLabel(member: Member): string {
  return member.name || member.email || member.phone || "Без имени";
}

/** Сотрудники, которым можно назначить заявку или диалог. */
export function useTeam(): Member[] {
  const { data } = useSWR("/team", () => unwrap(api.GET("/team")), { revalidateOnFocus: false });
  return (data ?? []).filter(
    (member) => member.is_active && (member.role === "owner" || member.role === "manager"),
  );
}
