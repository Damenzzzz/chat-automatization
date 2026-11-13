import { X } from "lucide-react";
import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

export function Chip({
  children,
  onRemove,
  removeLabel,
  className,
}: {
  children: ReactNode;
  onRemove?: () => void;
  removeLabel?: string;
  className?: string;
}) {
  return (
    <span
      className={cn(
        "inline-flex max-w-full items-center gap-1 rounded-full bg-haze px-2 py-0.5 text-xs text-ink",
        className,
      )}
    >
      <span className="truncate">{children}</span>
      {onRemove && (
        <button
          type="button"
          onClick={onRemove}
          aria-label={removeLabel ?? "Убрать"}
          className="-mr-1 flex size-6 shrink-0 items-center justify-center rounded-full hover:bg-line"
        >
          <X className="size-3" aria-hidden />
        </button>
      )}
    </span>
  );
}
