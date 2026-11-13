import { cn } from "@/lib/utils";

export function Toggle({
  checked,
  onChange,
  disabled,
  label,
}: {
  checked: boolean;
  onChange: (next: boolean) => void;
  disabled?: boolean;
  label: string;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className="group inline-flex min-h-11 shrink-0 items-center gap-2.5 rounded-md px-1 text-sm font-medium disabled:cursor-not-allowed disabled:opacity-60"
    >
      <span
        className={cn(
          "relative h-6 w-11 rounded-full border transition-colors",
          checked ? "border-sky-deep bg-sky" : "border-control bg-haze",
        )}
      >
        <span
          className={cn(
            "absolute top-0.5 left-0.5 size-[1.125rem] rounded-full bg-paper transition-transform",
            checked && "translate-x-5",
          )}
        />
      </span>
      <span className="w-[5.5rem] text-left">{checked ? "Включён" : "Выключен"}</span>
    </button>
  );
}
