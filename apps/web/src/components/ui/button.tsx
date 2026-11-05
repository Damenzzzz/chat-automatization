import { cva, type VariantProps } from "class-variance-authority";
import { LoaderCircle } from "lucide-react";
import type { ButtonHTMLAttributes, Ref } from "react";

import { cn } from "@/lib/utils";

export const buttonVariants = cva(
  "inline-flex min-h-11 items-center justify-center gap-2 rounded-md border px-4 text-sm font-medium transition-colors disabled:cursor-not-allowed sm:min-h-10 [&_svg]:size-4 [&_svg]:shrink-0",
  {
    variants: {
      variant: {
        primary:
          "border-ink bg-ink text-paper hover:bg-[#33383c] disabled:border-haze disabled:bg-haze disabled:text-steel",
        secondary:
          "border-control bg-paper text-ink hover:bg-mist disabled:border-line disabled:text-steel",
        ghost: "border-transparent bg-transparent text-ink hover:bg-haze disabled:text-steel",
        danger:
          "border-alert bg-paper text-alert hover:bg-alert-soft disabled:border-line disabled:text-steel",
        onInk: "border-paper bg-paper text-ink hover:bg-haze disabled:bg-haze disabled:text-steel",
      },
    },
    defaultVariants: { variant: "primary" },
  },
);

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> &
  VariantProps<typeof buttonVariants> & { loading?: boolean; ref?: Ref<HTMLButtonElement> };

export function Button({
  variant,
  loading,
  className,
  children,
  disabled,
  type = "button",
  ...props
}: ButtonProps) {
  return (
    <button
      type={type}
      className={cn(buttonVariants({ variant }), className)}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      {...props}
    >
      {loading && <LoaderCircle className="animate-spin" aria-hidden />}
      {children}
    </button>
  );
}
