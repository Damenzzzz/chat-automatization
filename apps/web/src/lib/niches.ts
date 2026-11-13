"use client";

import useSWR from "swr";

import { api, type Schemas } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";

/** Запасной список: сервер недоступен — регистрация всё равно работает. */
export const FALLBACK_NICHES = [
  "Цветы и подарки",
  "Автозапчасти",
  "Электроника",
  "Одежда и обувь",
  "Косметика",
  "Стройматериалы",
  "Другое",
];

export function useNiches(): { niches: Schemas["NicheOut"][]; titles: string[] } {
  const { data } = useSWR("/niches", () => unwrap(api.GET("/niches")), {
    revalidateOnFocus: false,
    shouldRetryOnError: false,
  });
  const niches = data ?? [];
  return { niches, titles: niches.length ? niches.map((niche) => niche.title) : FALLBACK_NICHES };
}
