import { cn } from "@/lib/utils";

export function Wordmark({ className }: { className?: string }) {
  return <span className={cn("display text-xl tracking-tight", className)}>Satushy</span>;
}
