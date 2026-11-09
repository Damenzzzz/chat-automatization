"use client";

import { useState } from "react";

import { count, plural, shortDay } from "@/lib/format";
import { cn } from "@/lib/utils";

type Day = { day: string; dialogs: number };

function dialogsWord(value: number): string {
  return `${count(value)} ${plural(value, "диалог", "диалога", "диалогов")}`;
}

export function DialogsChart({ days }: { days: Day[] }) {
  const [active, setActive] = useState<number | null>(null);
  const max = Math.max(1, ...days.map((day) => day.dialogs));
  const total = days.reduce((sum, day) => sum + day.dialogs, 0);
  const peak = days.reduce<Day | null>(
    (best, day) => (!best || day.dialogs > best.dialogs ? day : best),
    null,
  );
  const shown = active === null ? null : days[active];
  const every = days.length > 14 ? Math.ceil(days.length / 5) : days.length > 7 ? 2 : 1;

  return (
    <figure className="m-0">
      <p aria-live="off" className="mb-3 min-h-5 text-sm text-steel tnum">
        {shown ? (
          <>
            <span className="font-medium text-ink">{shortDay(shown.day)}:</span>{" "}
            {dialogsWord(shown.dialogs)}
          </>
        ) : peak && peak.dialogs > 0 ? (
          <>
            Больше всего {shortDay(peak.day)}: {dialogsWord(peak.dialogs)}
          </>
        ) : (
          "За этот период диалогов не было"
        )}
      </p>
      <div
        role="img"
        aria-label={`Диалоги по дням: всего ${dialogsWord(total)}. Таблица с числами ниже.`}
        onPointerLeave={() => setActive(null)}
        className="flex h-40 items-end gap-0.5 border-b border-control"
      >
        {days.map((day, index) => (
          <div
            key={day.day}
            onPointerEnter={() => setActive(index)}
            onPointerDown={() => setActive(index)}
            className="flex h-full min-w-0 flex-1 items-end justify-center"
          >
            <div
              className={cn(
                "w-full max-w-10 rounded-t-sm transition-colors",
                index === active ? "bg-ink" : "bg-gradient-to-t from-sky to-glow",
              )}
              style={{ height: day.dialogs ? `${Math.max(3, (day.dialogs / max) * 100)}%` : 0 }}
            />
          </div>
        ))}
      </div>
      <div aria-hidden className="mt-1.5 flex gap-0.5 text-xs text-steel">
        {days.map((day, index) => (
          <span
            key={day.day}
            className="min-w-0 flex-1 overflow-visible text-center whitespace-nowrap"
          >
            {index % every === 0 ? shortDay(day.day).replace(".", "") : ""}
          </span>
        ))}
      </div>
      <details className="mt-3 text-sm">
        <summary className="inline-flex min-h-9 items-center font-medium">
          Показать таблицей
        </summary>
        <table className="mt-2 w-full max-w-xs">
          <thead className="text-left text-steel">
            <tr>
              <th scope="col" className="py-1 font-normal">
                День
              </th>
              <th scope="col" className="py-1 text-right font-normal">
                Диалогов
              </th>
            </tr>
          </thead>
          <tbody className="tnum">
            {days.map((day) => (
              <tr key={day.day} className="border-t border-line">
                <td className="py-1">{shortDay(day.day)}</td>
                <td className="py-1 text-right">{count(day.dialogs)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </details>
    </figure>
  );
}
