import { CircleAlert, CircleCheck, Info } from "lucide-react";
import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

const kinds = {
  error: { icon: CircleAlert, box: "border-alert bg-alert-soft text-alert" },
  success: { icon: CircleCheck, box: "border-ink bg-paper text-ink" },
  info: { icon: Info, box: "border-line bg-mist text-ink" },
};

export function Notice({
  kind = "info",
  children,
  className,
}: {
  kind?: keyof typeof kinds;
  children: ReactNode;
  className?: string;
}) {
  const { icon: Icon, box } = kinds[kind];
  return (
    <div
      role={kind === "error" ? "alert" : "status"}
      className={cn("flex items-start gap-2 rounded-md border px-3 py-2.5 text-sm", box, className)}
    >
      <Icon className="mt-0.5 size-4 shrink-0" aria-hidden />
      <div className="min-w-0">{children}</div>
    </div>
  );
}
