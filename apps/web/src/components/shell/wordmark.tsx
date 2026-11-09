import { cn } from "@/lib/utils";

export function Mark({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 32 32" aria-hidden className={cn("size-8 shrink-0", className)}>
      <path
        d="M8 2h16a6 6 0 0 1 6 6v12a6 6 0 0 1-6 6H11l-6.2 4.6c-.6.5-1.3 0-1.3-.7V8A6 6 0 0 1 8 2z"
        fill="var(--sky)"
        stroke="var(--ink)"
        strokeWidth="1.6"
      />
      <path
        d="M20.6 10.2c-1-1.1-2.7-1.8-4.4-1.8-2.7 0-4.5 1.4-4.5 3.4 0 4.6 9.2 2.5 9.2 6.8 0 1.6-1.7 2.6-4.1 2.6-2 0-3.8-.8-4.9-2"
        fill="none"
        stroke="var(--ink)"
        strokeWidth="2.4"
        strokeLinecap="round"
      />
      <circle cx="26" cy="6" r="3.6" fill="var(--sun)" stroke="var(--ink)" strokeWidth="1.4" />
    </svg>
  );
}

export function Wordmark({
  className,
  tone = "ink",
}: {
  className?: string;
  tone?: "ink" | "paper";
}) {
  return (
    <span
      className={cn(
        "display inline-flex items-center gap-2 text-xl tracking-tight",
        tone === "paper" ? "text-paper" : "text-ink",
        className,
      )}
    >
      <Mark />
      satushy
    </span>
  );
}
