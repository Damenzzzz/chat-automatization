"use client";

import { useState, type ReactNode } from "react";
import useSWR from "swr";

import { Button } from "@/components/ui/button";
import { api } from "@/lib/api/client";
import { errorText, unwrap } from "@/lib/api/errors";
import { cn } from "@/lib/utils";

export function useDemoEnabled(): boolean {
  const { data } = useSWR("/demo", () => unwrap(api.GET("/demo")), {
    shouldRetryOnError: false,
  });
  return data?.enabled ?? false;
}

export async function enterDemo(): Promise<string | null> {
  try {
    await unwrap(api.POST("/demo/login"));
  } catch (failure) {
    return errorText(failure);
  }
  // eslint-disable-next-line @next/next/no-location-assign-relative-destination -- нужна полная перезагрузка: новая сессия
  window.location.href = "/overview";
  return null;
}

export function DemoButton({
  children = "Открыть демо-кабинет",
  variant = "secondary",
  className,
  hideWhenOff = true,
}: {
  children?: ReactNode;
  variant?: "primary" | "secondary" | "dark" | "onInk" | "glow" | "glass";
  className?: string;
  hideWhenOff?: boolean;
}) {
  const enabled = useDemoEnabled();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  if (!enabled && hideWhenOff) return null;
  return (
    <div className="flex flex-col gap-1.5">
      <Button
        variant={variant}
        loading={busy}
        className={cn(className)}
        onClick={async () => {
          setBusy(true);
          setError(await enterDemo());
          setBusy(false);
        }}
      >
        {children}
      </Button>
      {error && (
        <p role="alert" className="text-xs font-medium text-alert">
          {error}
        </p>
      )}
    </div>
  );
}
