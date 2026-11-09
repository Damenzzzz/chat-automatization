"use client";

import {
  Bot,
  ClipboardList,
  LayoutDashboard,
  LogOut,
  Menu,
  MessagesSquare,
  Package,
  Plug,
  Settings,
  Wallet,
  X,
  type LucideIcon,
} from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useRef, useState, type ReactNode } from "react";
import useSWR, { SWRConfig } from "swr";

import { LoadError } from "@/components/ui/page";
import { api } from "@/lib/api/client";
import { ApiError, unwrap } from "@/lib/api/errors";
import { cn } from "@/lib/utils";

import { InboxStream } from "./inbox-stream";
import { SessionProvider, useSession } from "./session";
import { Wordmark } from "./wordmark";

type Item = { href: string; label: string; icon: LucideIcon; ownerOnly?: boolean };

const NAV: Item[] = [
  { href: "/overview", label: "Обзор", icon: LayoutDashboard },
  { href: "/dialogs", label: "Диалоги", icon: MessagesSquare },
  { href: "/leads", label: "Заявки", icon: ClipboardList },
  { href: "/products", label: "Товары", icon: Package },
  { href: "/bot", label: "Бот и песочница", icon: Bot },
  { href: "/channels", label: "Каналы", icon: Plug, ownerOnly: true },
  { href: "/balance", label: "Баланс", icon: Wallet, ownerOnly: true },
  { href: "/settings", label: "Настройки", icon: Settings, ownerOnly: true },
];

function useWaiting(): number {
  const { data } = useSWR(
    "/conversations?counts",
    () => unwrap(api.GET("/conversations", { params: { query: { limit: 1 } } })),
    { refreshInterval: 60_000 },
  );
  return data?.counts.waiting ?? 0;
}

async function logout() {
  await fetch("/auth/logout", { method: "POST" });
  // eslint-disable-next-line @next/next/no-location-assign-relative-destination -- нужна полная перезагрузка: сбросить сессию
  window.location.href = "/login";
}

function Navigation({ onNavigate }: { onNavigate?: () => void }) {
  const pathname = usePathname();
  const waiting = useWaiting();
  const { me, shop, isOwner } = useSession();
  const items = NAV.filter((item) => !item.ownerOnly || isOwner);
  return (
    <>
      <nav aria-label="Разделы кабинета" className="relative flex-1 overflow-y-auto px-3">
        <ul className="flex flex-col gap-0.5">
          {items.map(({ href, label, icon: Icon }) => {
            const active = pathname === href || pathname.startsWith(`${href}/`);
            return (
              <li key={href}>
                <Link
                  href={href}
                  onClick={onNavigate}
                  aria-current={active ? "page" : undefined}
                  className={cn(
                    "flex min-h-11 items-center gap-3 rounded-md px-3 text-sm transition-colors sm:min-h-10",
                    active
                      ? "bg-gradient-to-r from-glow to-sky font-semibold text-ink shadow-[0_0_24px_-4px_rgb(61_224_245/0.6)]"
                      : "text-paper/70 hover:bg-white/[0.07] hover:text-paper",
                  )}
                >
                  <Icon className="size-4 shrink-0" aria-hidden />
                  <span className="flex-1">{label}</span>
                  {href === "/dialogs" && waiting > 0 && (
                    <span className="rounded-full bg-sun px-2 text-xs font-semibold text-ink tnum">
                      <span className="sr-only">Ждут ответа: </span>
                      {waiting}
                    </span>
                  )}
                </Link>
              </li>
            );
          })}
        </ul>
      </nav>
      <div className="relative border-t border-paper/10 px-3 py-3">
        <p className="truncate px-3 text-sm font-medium text-paper">
          {shop?.name ?? me?.tenant_name ?? ""}
        </p>
        <button
          type="button"
          onClick={() => void logout()}
          className="mt-1 flex min-h-11 w-full items-center gap-3 rounded-md px-3 text-sm text-paper/70 hover:bg-white/[0.07] hover:text-paper sm:min-h-9"
        >
          <LogOut className="size-4" aria-hidden />
          Выйти
        </button>
      </div>
    </>
  );
}

function MobileMenu() {
  const dialog = useRef<HTMLDialogElement>(null);
  const pathname = usePathname();
  const waiting = useWaiting();

  useEffect(() => {
    dialog.current?.close();
  }, [pathname]);

  return (
    <header className="on-ink sticky top-0 z-20 flex h-14 items-center justify-between bg-night/90 px-4 text-paper backdrop-blur-xl lg:hidden">
      <Link href="/overview" aria-label="Satushy, на обзор">
        <Wordmark tone="paper" />
      </Link>
      <button
        type="button"
        onClick={() => dialog.current?.showModal()}
        className="-mr-2 flex min-h-11 items-center gap-2 rounded-md px-2 text-sm font-medium"
      >
        {waiting > 0 && (
          <span className="rounded-full bg-sun px-2 text-xs font-semibold text-ink tnum">
            <span className="sr-only">Ждут ответа: </span>
            {waiting}
          </span>
        )}
        <Menu className="size-5" aria-hidden />
        Меню
      </button>
      <dialog
        ref={dialog}
        aria-label="Меню"
        className="on-ink m-0 h-dvh max-h-none w-[min(20rem,85vw)] max-w-none bg-night text-paper"
        onClick={(event) => {
          if (event.target === dialog.current) dialog.current?.close();
        }}
      >
        <div className="flex h-full flex-col">
          <div className="flex h-14 items-center justify-between px-6">
            <Wordmark tone="paper" />
            <button
              type="button"
              onClick={() => dialog.current?.close()}
              aria-label="Закрыть меню"
              className="-mr-2 flex size-11 items-center justify-center rounded-md hover:bg-ink-soft"
            >
              <X className="size-5" aria-hidden />
            </button>
          </div>
          <Navigation onNavigate={() => dialog.current?.close()} />
        </div>
      </dialog>
    </header>
  );
}

function Banners() {
  const { me, shop, isOwner } = useSession();
  const pathname = usePathname();
  const [leaving, setLeaving] = useState(false);
  if (
    !me?.demo &&
    !me?.impersonated_by &&
    !(isOwner && shop?.status === "onboarding" && pathname !== "/setup")
  )
    return null;
  return (
    <aside aria-label="Напоминания">
      {me?.demo && (
        <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1 bg-sun px-4 py-2 text-sm text-ink sm:px-8">
          <span>
            Это демо-магазин «{me.tenant_name}»: диалоги и заявки ненастоящие, бот отвечает
            по-настоящему.
          </span>
          <a href="/signup" className="font-semibold underline underline-offset-2">
            Подключить свой магазин
          </a>
        </div>
      )}
      {me?.impersonated_by && (
        <div className="on-ink flex flex-wrap items-center justify-between gap-2 bg-ink-soft px-4 py-2 text-sm text-paper sm:px-8">
          <span>Вы вошли как клиент «{me.tenant_name}». Каждое изменение пишется в журнал.</span>
          <button
            type="button"
            disabled={leaving}
            className="font-medium underline underline-offset-2"
            onClick={async () => {
              setLeaving(true);
              await api.DELETE("/admin/impersonate");
              // eslint-disable-next-line @next/next/no-location-assign-relative-destination -- нужна полная перезагрузка: сбросить сессию
              window.location.href = "/overview";
            }}
          >
            Выйти из режима
          </button>
        </div>
      )}
      {isOwner && shop?.status === "onboarding" && pathname !== "/setup" && (
        <div
          className={cn(
            "flex flex-wrap items-center justify-between gap-x-4 gap-y-1 border-b border-sky/40 bg-sky-soft px-4 py-2.5 text-sm sm:px-8",
            pathname === "/dialogs" && "max-lg:hidden",
          )}
        >
          <span>Настройка магазина не закончена.</span>
          <Link
            href={`/setup?step=${shop.onboarding_step}`}
            className="font-medium underline underline-offset-2"
          >
            Продолжить настройку
          </Link>
        </div>
      )}
    </aside>
  );
}

function Frame({ children }: { children: ReactNode }) {
  const { error, retry } = useSession();
  return (
    <div className="min-h-svh bg-canvas lg:grid lg:grid-cols-[16rem_minmax(0,1fr)]">
      <a
        href="#content"
        className="absolute top-2 left-2 z-50 -translate-y-20 rounded-md bg-ink px-3 py-2 text-sm text-paper focus:translate-y-0"
      >
        Перейти к содержимому
      </a>
      <aside className="on-ink sticky top-0 hidden h-svh flex-col overflow-hidden border-r border-white/5 bg-night lg:flex">
        <div
          aria-hidden
          className="aurora top-[-8rem] left-[-6rem] h-72 w-72 animate-aurora-a bg-sky/35"
        />
        <div
          aria-hidden
          className="aurora right-[-8rem] bottom-[-6rem] h-64 w-64 animate-aurora-b bg-sun/15"
        />
        <div className="pointer-events-none absolute inset-x-0 bottom-0 h-48 ornament [mask-image:linear-gradient(to_top,black,transparent)] opacity-40" />
        <div className="relative px-6 pt-6 pb-6">
          <Link href="/overview" aria-label="Satushy, на обзор">
            <Wordmark tone="paper" />
          </Link>
        </div>
        <Navigation />
      </aside>
      <MobileMenu />
      <div className="flex min-w-0 flex-col lg:h-svh lg:overflow-y-auto">
        <Banners />
        <main
          id="content"
          tabIndex={-1}
          className="flex min-h-0 flex-1 flex-col focus:outline-none"
        >
          {error ? (
            <div className="px-4 sm:px-8">
              <LoadError error={error} retry={retry} />
            </div>
          ) : (
            children
          )}
        </main>
      </div>
      <InboxStream />
    </div>
  );
}

export function AppShell({ children }: { children: ReactNode }) {
  return (
    <SWRConfig
      value={{
        shouldRetryOnError: (error) => !(error instanceof ApiError && error.status < 500),
        errorRetryCount: 3,
        dedupingInterval: 1000,
      }}
    >
      <SessionProvider>
        <Frame>{children}</Frame>
      </SessionProvider>
    </SWRConfig>
  );
}
