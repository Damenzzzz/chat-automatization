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
      <nav aria-label="Разделы кабинета" className="flex-1 overflow-y-auto px-3">
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
                    "flex min-h-11 items-center gap-3 rounded-md px-3 text-sm sm:min-h-10",
                    active ? "bg-haze font-medium" : "text-ink hover:bg-haze/60",
                  )}
                >
                  <Icon className="size-4 shrink-0" aria-hidden />
                  <span className="flex-1">{label}</span>
                  {href === "/dialogs" && waiting > 0 && (
                    <span className="rounded-sm bg-ink px-1.5 text-xs font-medium text-paper tnum">
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
      <div className="border-t border-line px-3 py-3">
        <p className="truncate px-3 text-sm font-medium">{shop?.name ?? me?.tenant_name ?? ""}</p>
        <button
          type="button"
          onClick={() => void logout()}
          className="mt-1 flex min-h-11 w-full items-center gap-3 rounded-md px-3 text-sm text-steel hover:bg-haze hover:text-ink sm:min-h-9"
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
    <header className="sticky top-0 z-20 flex h-14 items-center justify-between border-b border-line bg-mist px-4 lg:hidden">
      <Link href="/overview" aria-label="Satushy, на обзор">
        <Wordmark />
      </Link>
      <button
        type="button"
        onClick={() => dialog.current?.showModal()}
        className="-mr-2 flex min-h-11 items-center gap-2 rounded-md px-2 text-sm font-medium"
      >
        {waiting > 0 && (
          <span className="rounded-sm bg-ink px-1.5 text-xs text-paper tnum">
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
        className="m-0 h-dvh max-h-none w-[min(20rem,85vw)] max-w-none bg-mist text-ink"
        onClick={(event) => {
          if (event.target === dialog.current) dialog.current?.close();
        }}
      >
        <div className="flex h-full flex-col">
          <div className="flex h-14 items-center justify-between px-6">
            <Wordmark />
            <button
              type="button"
              onClick={() => dialog.current?.close()}
              aria-label="Закрыть меню"
              className="-mr-2 flex size-11 items-center justify-center rounded-md hover:bg-haze"
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
  return (
    <>
      {me?.impersonated_by && (
        <div className="on-ink flex flex-wrap items-center justify-between gap-2 bg-ink px-4 py-2 text-sm text-paper sm:px-8">
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
        <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1 border-b border-line bg-mist px-4 py-2.5 text-sm sm:px-8">
          <span>
            Настройка магазина не закончена, поэтому бот пока не готов к работе с покупателями.
          </span>
          <Link
            href={`/setup?step=${shop.onboarding_step}`}
            className="font-medium underline underline-offset-2"
          >
            Продолжить настройку
          </Link>
        </div>
      )}
    </>
  );
}

function Frame({ children }: { children: ReactNode }) {
  const { error, retry } = useSession();
  return (
    <div className="min-h-svh lg:grid lg:grid-cols-[15rem_minmax(0,1fr)]">
      <a
        href="#content"
        className="absolute top-2 left-2 z-50 -translate-y-20 rounded-md bg-ink px-3 py-2 text-sm text-paper focus:translate-y-0"
      >
        Перейти к содержимому
      </a>
      <aside className="sticky top-0 hidden h-svh flex-col bg-mist lg:flex">
        <div className="px-6 pt-6 pb-5">
          <Link href="/overview" aria-label="Satushy, на обзор">
            <Wordmark />
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
