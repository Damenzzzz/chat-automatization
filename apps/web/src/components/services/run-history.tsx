"use client";

import useSWR from "swr";

import { LoadError } from "@/components/ui/page";
import { api } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";
import { fullDate } from "@/lib/format";
import { cn } from "@/lib/utils";

import type { Kind } from "./catalog";

export function runsKey(kind: Kind) {
  return `/automations/${kind}/runs`;
}

const TRIGGER: Record<string, string> = { schedule: "по расписанию", manual: "вручную" };

export function RunHistory({ kind }: { kind: Kind }) {
  const { data, error, mutate } = useSWR(runsKey(kind), () =>
    unwrap(api.GET("/automations/{kind}/runs", { params: { path: { kind } } })),
  );
  if (error) return <LoadError error={error} retry={() => void mutate()} />;
  if (!data) return <p className="text-sm text-steel">Загружаем историю…</p>;
  if (!data.length)
    return (
      <p className="text-sm text-steel">
        Запусков пока не было. По расписанию в историю попадают только запуски, в которых сервис
        что-то сделал.
      </p>
    );
  return (
    <ol className="divide-y divide-line">
      {data.map((run) => (
        <li key={run.id} className="flex gap-3 py-2.5 text-sm">
          <span
            aria-hidden
            className={cn(
              "mt-1.5 size-2 shrink-0 rounded-full",
              run.status === "failed" ? "bg-alert" : run.status === "ok" ? "bg-sky" : "bg-control",
            )}
          />
          <span className="min-w-0">
            <span className={cn("block", run.status === "failed" && "text-alert")}>
              {run.summary}
            </span>
            <span className="text-steel tnum">
              {fullDate(run.created_at)}, {TRIGGER[run.trigger] ?? run.trigger}
            </span>
          </span>
        </li>
      ))}
    </ol>
  );
}
