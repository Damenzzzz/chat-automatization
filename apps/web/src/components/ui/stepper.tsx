import { Check } from "lucide-react";

import { cn } from "@/lib/utils";

export function Stepper({
  steps,
  current,
  reached,
  onSelect,
}: {
  steps: string[];
  current: number;
  reached: number;
  onSelect: (step: number) => void;
}) {
  return (
    <ol className="flex gap-1 sm:gap-5" aria-label="Шаги настройки">
      {steps.map((label, index) => {
        const number = index + 1;
        const done = number < current;
        const active = number === current;
        const open = number <= reached;
        return (
          <li key={label} className="min-w-0 flex-1">
            <button
              type="button"
              disabled={!open}
              onClick={() => onSelect(number)}
              aria-current={active ? "step" : undefined}
              aria-label={`Шаг ${number}: ${label}`}
              className="flex min-h-11 w-full flex-col gap-1.5 text-left disabled:cursor-not-allowed"
            >
              <span
                className={cn("h-1 w-full rounded-sm", done || active ? "bg-ink" : "bg-haze")}
              />
              <span
                className={cn(
                  "hidden items-center gap-1.5 text-sm sm:flex",
                  active ? "font-medium text-ink" : "text-steel",
                )}
              >
                {done ? (
                  <Check className="size-3.5" aria-hidden />
                ) : (
                  <span className="tnum">{number}.</span>
                )}
                {label}
              </span>
            </button>
          </li>
        );
      })}
    </ol>
  );
}
