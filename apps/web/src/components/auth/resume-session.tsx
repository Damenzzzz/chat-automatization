"use client";

import { useSearchParams } from "next/navigation";
import { useEffect } from "react";

import { refreshSession } from "@/lib/api/client";
import { safeNext } from "@/lib/identity";

export function ResumeSession() {
  const next = useSearchParams().get("next");

  useEffect(() => {
    if (!next) return;
    void refreshSession().then((resumed) => {
      if (resumed) window.location.replace(safeNext(next));
    });
  }, [next]);

  return null;
}
