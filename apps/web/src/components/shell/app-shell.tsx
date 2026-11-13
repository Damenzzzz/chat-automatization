"use client";

import {
  Bot,
  ClipboardList,
  Ellipsis,
  LogOut,
  MessagesSquare,
  Package,
  Pause,
  Play,
  Plug,
  Search,
  Settings,
  Sun,
  Wallet,
  Workflow,
  X,
  type LucideIcon,
} from "lucide-react";
import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useRef, useState, type ReactNode } from "react";
import useSWR, { SWRConfig } from "swr";

import { LoadError } from "@/components/ui/page";
import { api } from "@/lib/api/client";
import { ApiError, errorText, unwrap } from "@/lib/api/errors";
import { cn } from "@/lib/utils";

import { useAttention } from "./attention";
import { CommandPalette, openPalette } from "./command-palette";
import { InboxStream } from "./inbox-stream";
import { SessionProvider, useSession } from "./session";
import { Wordmark } from "./wordmark";

type Item = { href: string; label: string; icon: LucideIcon; ownerOnly?: boolean };

const NAV: Item[] = [
  { href: "/overview", label: "Сегодня", icon: Sun },
  { href: "/dialogs", label: "Диалоги", icon: MessagesSquare },
  { href: "/leads", label: "Заявки", icon: ClipboardList },
  { href: "/products", label: "Товары", icon: Package },
  { href: "/bot", label: "Бот и песочница", icon: Bot },
  { href: "/services", label: "Сервисы", icon: Workflow },
  { href: "/channels", label: "Каналы", icon: Plug, ownerOnly: true },
  { href: "/balance", label: "Баланс", icon: Wallet, ownerOnly: true },
  { href: "/settings", label: "Настройки", icon: Settings },
];

function useWaitingCount(): number | undefined {
  const { data } = useSWR(
    "/conversations?counts",
    () => unwrap(api.GET("/conversations", { params: { query: { limit: 1 } } })),
    { refreshInterval: 60_000 },
  );
  return data?.counts.waiting;
}

function useWaiting(): number {
  return useWaitingCount() ?? 0;
}

function useNewLeads(): number {
  const { data } = useSWR(
    "/leads?status=new&badge",
    () => unwrap(api.GET("/leads", { params: { query: { status: "new" } } })),
    { refreshInterval: 60_000 },
  );
  return data?.items.length ?? 0;
}

function Badge({ value, label }: { value: number; label: string }) {
  if (value <= 0) return null;
  return (
    <span className="rounded-full bg-sun px-2 text-xs font-semibold text-ink tnum">
      <span className="sr-only">{label}: </span>
      {value}
    </span>
  );
}

function useTitleCounter(waiting: number) {
  useEffect(() => {
    const apply = () => {
      const base = document.title.replace(/^\(\d+\) /, "");
      const next = waiting > 0 ? `(${waiting}) ${base}` : base;
      if (document.title !== next) document.title = next;
    };
    apply();
    const observer = new MutationObserver(apply);
    observer.observe(document.head, { childList: true, subtree: true, characterData: true });
    return () => observer.disconnect();
  }, [waiting]);
}

function BotSwitch() {
  const { shop, isOwner, refresh } = useSession();
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState<string | null>(null);
  if (!shop) return null;
  const paused = shop.bot_paused;

  async function toggle() {
    setBusy(true);
    setFailed(null);
    try {
      await unwrap(api.PATCH("/shop", { body: { bot_paused: !paused } }));
      refresh();
    } catch (error) {
      setFailed(errorText(error));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mx-3 mb-3 rounded-lg border border-paper/10 bg-white/[0.04] p-3 text-xs text-paper/70">
      <p className="flex items-center gap-2 text-sm font-medium text-paper">
        <span
          aria-hidden
          className={cn(
            "size-2 rounded-full",
            paused ? "bg-sun" : "bg-teal shadow-[0_0_0_3px_rgb(25_211_176/0.25)]",
          )}
        />
        {paused ? "Бот на паузе" : "Бот отвечает"}
      </p>
      <p className="mt-1">
        {paused ? "Сообщения покупателей ждут менеджера." : "Покупатели получают ответ сразу."}
      </p>
      {isOwner && (
        <button
          type="button"
          disabled={busy}
          onClick={() => void toggle()}
          className="mt-2 flex min-h-9 items-center gap-1.5 rounded-md text-sm font-medium text-paper underline-offset-2 hover:underline disabled:opacity-60"
        >
          {paused ? (
            <Play className="size-3.5" aria-hidden />
          ) : (
            <Pause className="size-3.5" aria-hidden />
          )}
          {paused ? "Включить бота" : "Поставить на паузу"}
        </button>
      )}
      {failed && <p className="mt-1 text-sun">{failed}</p>}
    </div>
  );
}

async function logout() {
  await fetch("/auth/logout", { method: "POST" });
  // eslint-disable-next-line @next/next/no-location-assign-relative-destination -- нужна полная перезагрузка: сбросить сессию
  window.location.href = "/login";
}

function Navigation({ onNavigate }: { onNavigate?: () => void }) {
  const pathname = usePathname();
  const waiting = useWaiting();
  const newLeads = useNewLeads();
  const { me, shop, isOwner } = useSession();
  const items = NAV.filter((item) => !item.ownerOnly || isOwner);
  return (
    <>
      <div className="relative px-3 pb-3">
        <button
          type="button"
          onClick={openPalette}
          className="flex min-h-10 w-full items-center gap-3 rounded-md border border-paper/10 bg-white/[0.04] px-3 text-sm text-paper/60 hover:border-paper/25 hover:text-paper"
        >
          <Search className="size-4 shrink-0" aria-hidden />
          <span className="flex-1 text-left">Поиск</span>
          <kbd className="rounded border border-paper/15 px-1.5 text-[11px] max-lg:hidden">⌘K</kbd>
        </button>
      </div>
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
                  {href === "/dialogs" && <Badge value={waiting} label="Ждут ответа" />}
                  {href === "/leads" && <Badge value={newLeads} label="Новые заявки" />}
                </Link>
              </li>
            );
          })}
        </ul>
      </nav>
      <BotSwitch />
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

const TABS: Item[] = [
  { href: "/overview", label: "Сегодня", icon: Sun },
  { href: "/dialogs", label: "Диалоги", icon: MessagesSquare },
  { href: "/leads", label: "Заявки", icon: ClipboardList },
];

function MobileTabs() {
  const dialog = useRef<HTMLDialogElement>(null);
  const pathname = usePathname();
  const params = useSearchParams();
  const waiting = useWaiting();
  const newLeads = useNewLeads();
  const inThread = pathname === "/dialogs" && params.has("id");
  const more = !TABS.some((tab) => pathname === tab.href);

  useEffect(() => {
    dialog.current?.close();
  }, [pathname]);

  const tab =
    "relative flex min-h-14 flex-1 flex-col items-center justify-center gap-0.5 text-[11px]";
  return (
    <>
      <nav
        aria-label="Быстрые разделы"
        className={cn(
          "on-ink fixed inset-x-0 bottom-0 z-20 flex border-t border-white/10 bg-night/95 pb-[env(safe-area-inset-bottom)] text-paper/65 backdrop-blur-xl lg:hidden",
          inThread && "hidden",
        )}
      >
        {TABS.map(({ href, label, icon: Icon }) => {
          const active = pathname === href;
          const count = href === "/dialogs" ? waiting : href === "/leads" ? newLeads : 0;
          return (
            <Link
              key={href}
              href={href}
              aria-current={active ? "page" : undefined}
              className={cn(tab, active && "font-semibold text-glow")}
            >
              <Icon className="size-5" aria-hidden />
              {label}
              {count > 0 && (
                <span className="absolute top-1.5 left-1/2 ml-2 rounded-full bg-sun px-1.5 text-[10px] font-semibold text-ink tnum">
                  <span className="sr-only">Ждут: </span>
                  {count}
                </span>
              )}
            </Link>
          );
        })}
        <button
          type="button"
          onClick={() => dialog.current?.showModal()}
          className={cn(tab, more && "font-semibold text-glow")}
        >
          <Ellipsis className="size-5" aria-hidden />
          Ещё
        </button>
      </nav>
      <dialog
        ref={dialog}
        aria-label="Меню"
        className="on-ink m-0 ml-auto h-dvh max-h-none w-[min(20rem,85vw)] max-w-none bg-night text-paper"
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
    </>
  );
}

function MobileHeader() {
  return (
    <header className="on-ink sticky top-0 z-20 flex h-14 items-center justify-between bg-night/90 px-4 text-paper backdrop-blur-xl lg:hidden">
      <Link href="/overview" aria-label="Satushy, на главную">
        <Wordmark tone="paper" />
      </Link>
      <button
        type="button"
        onClick={openPalette}
        aria-label="Поиск"
        className="-mr-2 flex size-11 items-center justify-center rounded-md"
      >
        <Search className="size-5" aria-hidden />
      </button>
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
  const pathname = usePathname();
  const waiting = useWaitingCount();
  useTitleCounter(waiting ?? 0);
  useAttention(waiting);
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
          <Link href="/overview" aria-label="Satushy, на главную">
            <Wordmark tone="paper" />
          </Link>
        </div>
        <Navigation />
      </aside>
      <MobileHeader />
      <div
        className={cn(
          "flex min-w-0 flex-col lg:h-svh lg:overflow-y-auto",
          pathname !== "/dialogs" && "max-lg:pb-16",
        )}
      >
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
      <Suspense fallback={null}>
        <MobileTabs />
      </Suspense>
      <CommandPalette />
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
