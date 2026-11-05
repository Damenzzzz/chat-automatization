import { LoaderCircle } from "lucide-react";
import type { ReactNode } from "react";

import { errorText } from "@/lib/api/errors";
import { cn } from "@/lib/utils";

import { Button } from "./button";
import { Notice } from "./notice";

export function PageHeader({
  title,
  children,
  actions,
}: {
  title: string;
  children?: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <header className="flex flex-wrap items-end justify-between gap-x-6 gap-y-3 pb-6">
      <div className="max-w-2xl">
        <h1 className="text-2xl">{title}</h1>
        {children && <p className="mt-1.5 text-steel">{children}</p>}
      </div>
      {actions && <div className="flex flex-wrap gap-2">{actions}</div>}
    </header>
  );
}

export function Page({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <div className={cn("mx-auto w-full max-w-5xl px-4 py-6 sm:px-8 sm:py-8", className)}>
      {children}
    </div>
  );
}

export function Section({
  title,
  description,
  actions,
  children,
  className,
}: {
  title: string;
  description?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={cn("border-t border-line py-6", className)}>
      <div className="mb-4 flex flex-wrap items-start justify-between gap-x-6 gap-y-2">
        <div className="max-w-2xl">
          <h2 className="text-lg">{title}</h2>
          {description && <p className="mt-1 text-sm text-steel">{description}</p>}
        </div>
        {actions}
      </div>
      {children}
    </section>
  );
}

export function Loading({
  label = "Загружаем",
  className,
}: {
  label?: string;
  className?: string;
}) {
  return (
    <p role="status" className={cn("flex items-center gap-2 py-6 text-sm text-steel", className)}>
      <LoaderCircle className="size-4 animate-spin" aria-hidden />
      {label}
    </p>
  );
}

export function LoadError({ error, retry }: { error: unknown; retry?: () => void }) {
  return (
    <Notice kind="error" className="my-4">
      <p>{errorText(error)}</p>
      {retry && (
        <button
          type="button"
          onClick={retry}
          className="mt-1 font-medium underline underline-offset-2"
        >
          Попробовать снова
        </button>
      )}
    </Notice>
  );
}

export function Empty({
  title,
  children,
  action,
}: {
  title: string;
  children?: ReactNode;
  action?: ReactNode;
}) {
  return (
    <div className="max-w-md py-8">
      <p className="font-medium">{title}</p>
      {children && <p className="mt-1 text-sm text-steel">{children}</p>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}

export function FormError({ error }: { error: unknown }) {
  const text = errorText(error);
  return text ? <Notice kind="error">{text}</Notice> : null;
}

export { Button };
