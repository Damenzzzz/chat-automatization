"use client";

import { Check, Copy } from "lucide-react";
import { useState } from "react";

import { cn } from "@/lib/utils";

import { Button } from "./button";

export function CopyButton({
  value,
  label = "Копировать",
  className,
}: {
  value: string;
  label?: string;
  className?: string;
}) {
  const [state, setState] = useState<"idle" | "done" | "failed">("idle");

  async function copy() {
    try {
      await navigator.clipboard.writeText(value);
      setState("done");
    } catch {
      setState("failed");
    }
    setTimeout(() => setState("idle"), 2000);
  }

  return (
    <Button variant="secondary" className={cn("shrink-0", className)} onClick={() => void copy()}>
      {state === "done" ? <Check aria-hidden /> : <Copy aria-hidden />}
      <span aria-live="polite">
        {state === "done"
          ? "Скопировано"
          : state === "failed"
            ? "Выделите и скопируйте вручную"
            : label}
      </span>
    </Button>
  );
}

export function CopyRow({
  label,
  value,
  secret,
}: {
  label: string;
  value: string;
  secret?: boolean;
}) {
  return (
    <div className="flex flex-col gap-1.5">
      <p className="text-sm font-medium">{label}</p>
      <div className="flex flex-col gap-2 sm:flex-row sm:items-start">
        <code
          className={cn(
            "min-h-10 flex-1 rounded-md border border-line bg-mist px-3 py-2 text-sm break-all select-all",
            secret && "tracking-tight",
          )}
        >
          {value}
        </code>
        <CopyButton value={value} />
      </div>
    </div>
  );
}
