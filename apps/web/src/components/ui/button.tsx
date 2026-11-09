import { cva, type VariantProps } from "class-variance-authority";
import { LoaderCircle } from "lucide-react";
import type { ButtonHTMLAttributes, Ref } from "react";

import { cn } from "@/lib/utils";

export const buttonVariants = cva(
  "inline-flex min-h-11 items-center justify-center gap-2 rounded-md border px-4 text-sm font-semibold transition-colors disabled:cursor-not-allowed sm:min-h-10 [&_svg]:size-4 [&_svg]:shrink-0",
  {
    variants: {
      variant: {
        primary:
          "border-sky bg-sky text-ink hover:border-[#00c3e3] hover:bg-[#00c3e3] disabled:border-haze disabled:bg-haze disabled:text-steel",
        secondary:
          "border-line bg-paper text-ink hover:border-control hover:bg-mist disabled:border-line disabled:text-steel",
        dark: "border-ink bg-ink text-paper hover:bg-ink-soft disabled:border-haze disabled:bg-haze disabled:text-steel",
        ghost: "border-transparent bg-transparent text-ink hover:bg-haze disabled:text-steel",
        danger:
          "border-alert bg-paper text-alert hover:bg-alert-soft disabled:border-line disabled:text-steel",
        onInk: "border-sun bg-sun text-ink hover:bg-[#ffd451] disabled:bg-haze disabled:text-steel",
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
