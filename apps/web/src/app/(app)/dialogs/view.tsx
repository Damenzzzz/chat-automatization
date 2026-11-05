"use client";

import { MessagesSquare } from "lucide-react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useState } from "react";
import useSWR from "swr";

import { CHANNEL_NAMES, customerName, LEAD_STATUS } from "@/components/dialogs/labels";
import { Thread } from "@/components/dialogs/thread";
import { Button } from "@/components/ui/button";
import { Empty, LoadError, Loading } from "@/components/ui/page";
import { api, type Schemas } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";
import { whenShort } from "@/lib/format";
import { cn } from "@/lib/utils";

type Row = Schemas["ConversationRow"];
type Filter = "all" | "bot" | "human" | "leads";

const FILTERS: { value: Filter; label: string }[] = [
  { value: "all", label: "Все" },
  { value: "bot", label: "Бот" },
  { value: "human", label: "Менеджер" },
  { value: "leads", label: "Заявки" },
];

const EMPTY: Record<Filter, { title: string; text: string }> = {
  all: {
    title: "Диалогов пока нет",
    text: "Подключите канал, и переписки покупателей появятся здесь.",
  },
  bot: { title: "Бот сейчас ни с кем не говорит", text: "Новые диалоги появятся здесь сами." },
  human: {
    title: "Нет диалогов у менеджера",
    text: "Сюда попадают диалоги, которые перехватили или которые бот передал.",
  },
  leads: {
    title: "Заявок пока нет",
    text: "Когда покупатель оставит заявку, диалог появится здесь.",
  },
};

const ROLE_PREFIX: Record<string, string> = { bot: "Бот: ", manager: "Вы: " };

function RowLink({ row, active, filter }: { row: Row; active: boolean; filter: Filter }) {
  const params = new URLSearchParams({ id: row.id });
  if (filter !== "all") params.set("filter", filter);
  return (
    <Link
      href={`/dialogs?${params}`}
      aria-current={active ? "true" : undefined}
      className={cn("block px-4 py-3 hover:bg-mist", active && "bg-haze hover:bg-haze")}
    >
      <span className="flex items-baseline justify-between gap-3">
        <span
          className={cn("min-w-0 truncate text-sm", row.waiting ? "font-semibold" : "font-medium")}
        >
          {row.waiting && (
            <>
              <span
                aria-hidden
                className="mr-1.5 inline-block size-2 rounded-full bg-ink align-middle"
              />
              <span className="sr-only">Ждёт ответа. </span>
            </>
          )}
          {customerName(row)}
        </span>
        <span className="shrink-0 text-xs text-steel tnum">{whenShort(row.last_message_at)}</span>
      </span>
      <span className="mt-0.5 line-clamp-1 text-sm text-steel">
        {ROLE_PREFIX[row.preview_role ?? ""] ?? ""}
        {row.preview ?? "Голосовое сообщение"}
      </span>
      <span className="mt-1 flex flex-wrap gap-x-2 gap-y-0.5 text-xs text-steel">
        <span>{CHANNEL_NAMES[row.channel ?? ""] ?? row.channel}</span>
        {row.mode === "human" && <span className="font-medium text-ink">у менеджера</span>}
        {row.lead_status && (
          <span className="font-medium text-ink">
            заявка: {LEAD_STATUS[row.lead_status].toLowerCase()}
          </span>
        )}
      </span>
    </Link>
  );
}

function List({ filter, activeId }: { filter: Filter; activeId: string | null }) {
  const [pages, setPages] = useState<Record<string, Row[]>>({});
  const [next, setNext] = useState<string | null | undefined>(undefined);
  const [loadingMore, setLoadingMore] = useState(false);

  const { data, error, isLoading, mutate } = useSWR(`/conversations?filter=${filter}`, () =>
    unwrap(api.GET("/conversations", { params: { query: { filter } } })),
  );

  const counts = data?.counts;
  const more = pages[filter] ?? [];
  const cursor = next === undefined ? data?.next_before : next;

  async function loadMore() {
    if (!cursor) return;
    setLoadingMore(true);
    try {
      const page = await unwrap(
        api.GET("/conversations", { params: { query: { filter, before: cursor } } }),
      );
      setPages({ ...pages, [filter]: [...more, ...page.items] });
      setNext(page.next_before ?? null);
    } finally {
      setLoadingMore(false);
    }
  }

  const seen = new Set(data?.items.map((row) => row.id));
  const rows = [...(data?.items ?? []), ...more.filter((row) => !seen.has(row.id))];

  return (
    <>
      <div className="border-b border-line px-4 pt-4 pb-3">
        <p aria-hidden className="display text-xl">
          Диалоги
        </p>
        <nav aria-label="Фильтр диалогов" className="mt-3 -ml-1 flex flex-wrap gap-1">
          {FILTERS.map((item) => {
            const active = item.value === filter;
            const value = counts?.[item.value];
            return (
              <Link
                key={item.value}
                href={item.value === "all" ? "/dialogs" : `/dialogs?filter=${item.value}`}
                aria-current={active ? "true" : undefined}
                onClick={() => setNext(undefined)}
                className={cn(
                  "flex min-h-9 items-center gap-1.5 rounded-md px-2.5 text-sm",
                  active ? "bg-ink text-paper" : "text-ink hover:bg-haze",
                )}
              >
                {item.label}
                {value !== undefined && value > 0 && (
                  <span className={cn("text-xs tnum", active ? "text-haze" : "text-steel")}>
                    {value}
                  </span>
                )}
              </Link>
            );
          })}
        </nav>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto">
        {isLoading && <Loading className="px-4" />}
        {error ? (
          <div className="px-4">
            <LoadError error={error} retry={() => void mutate()} />
          </div>
        ) : null}
        {data && rows.length === 0 && (
          <div className="px-4">
            <Empty title={EMPTY[filter].title}>{EMPTY[filter].text}</Empty>
          </div>
        )}
        <ul className="divide-y divide-line">
          {rows.map((row) => (
            <li key={row.id}>
              <RowLink row={row} active={row.id === activeId} filter={filter} />
            </li>
          ))}
        </ul>
        {cursor && (
          <div className="p-4">
            <Button
              variant="secondary"
              className="w-full"
              loading={loadingMore}
              onClick={() => void loadMore()}
            >
              Показать ещё
            </Button>
          </div>
        )}
      </div>
    </>
  );
}

export function DialogsView() {
  const params = useSearchParams();
  const id = params.get("id");
  const raw = params.get("filter");
  const filter: Filter = raw === "bot" || raw === "human" || raw === "leads" ? raw : "all";

  return (
    <div className="flex min-h-0 max-lg:h-[calc(100dvh-3.5rem)] lg:flex-1">
      <h1 className="sr-only">Диалоги</h1>
      <div
        className={cn(
          "flex min-h-0 w-full flex-col border-r border-line lg:w-80 lg:shrink-0 xl:w-96",
          id && "max-lg:hidden",
        )}
      >
        <List filter={filter} activeId={id} />
      </div>
      <div className={cn("flex min-h-0 min-w-0 flex-1 flex-col", !id && "max-lg:hidden")}>
        {id ? (
          <Thread key={id} id={id} />
        ) : (
          <div className="flex flex-1 flex-col items-center justify-center gap-2 bg-mist p-8 text-center text-steel">
            <MessagesSquare className="size-6" aria-hidden />
            <p>Выберите диалог слева.</p>
          </div>
        )}
      </div>
    </div>
  );
}
