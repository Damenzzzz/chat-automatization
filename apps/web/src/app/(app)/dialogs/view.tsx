"use client";

import { MessagesSquare, Search } from "lucide-react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";
import useSWR from "swr";

import { CHANNEL_NAMES, customerName, LEAD_STATUS } from "@/components/dialogs/labels";
import { Thread } from "@/components/dialogs/thread";
import { Button } from "@/components/ui/button";
import { Chip } from "@/components/ui/chip";
import { Empty, LoadError, Loading } from "@/components/ui/page";
import { api, type Schemas } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";
import { waitedFor, whenShort } from "@/lib/format";
import { cn } from "@/lib/utils";

type Row = Schemas["ConversationRow"];
type Filter = "all" | "bot" | "human" | "leads" | "mine" | "unassigned";

const FILTERS: { value: Filter; label: string }[] = [
  { value: "all", label: "Все" },
  { value: "bot", label: "Бот" },
  { value: "human", label: "Менеджер" },
  { value: "leads", label: "Заявки" },
  { value: "mine", label: "Мои" },
  { value: "unassigned", label: "Без ответственного" },
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
  mine: {
    title: "За вами нет диалогов",
    text: "Диалог становится вашим, когда вы его перехватываете или вас назначают.",
  },
  unassigned: {
    title: "Все диалоги у менеджеров разобраны",
    text: "Здесь появятся диалоги, которые бот передал человеку, но их ещё никто не взял.",
  },
};

function dialogsHref(filter: Filter, tag: string | null, id?: string): string {
  const params = new URLSearchParams();
  if (id) params.set("id", id);
  if (filter !== "all") params.set("filter", filter);
  if (tag) params.set("tag", tag);
  const query = params.toString();
  return query ? `/dialogs?${query}` : "/dialogs";
}

const ROLE_PREFIX: Record<string, string> = { bot: "Бот: ", manager: "Вы: " };

function RowLink({
  row,
  active,
  filter,
  tag,
}: {
  row: Row;
  active: boolean;
  filter: Filter;
  tag: string | null;
}) {
  return (
    <Link
      href={dialogsHref(filter, tag, row.id)}
      aria-current={active ? "true" : undefined}
      className={cn("block px-4 py-3 hover:bg-mist", active && "bg-sky-soft hover:bg-sky-soft")}
    >
      <span className="flex items-baseline justify-between gap-3">
        <span
          className={cn("min-w-0 truncate text-sm", row.waiting ? "font-semibold" : "font-medium")}
        >
          {row.waiting && (
            <>
              <span
                aria-hidden
                className="mr-1.5 inline-block size-2.5 rounded-full border border-ink bg-sun align-middle"
              />
              <span className="sr-only">Ждёт ответа. </span>
            </>
          )}
          {customerName(row)}
        </span>
        {row.waiting ? (
          <span className="shrink-0 rounded-full bg-sun-soft px-2 text-xs font-semibold tnum">
            <span className="sr-only">ждёт </span>
            {waitedFor(row.last_message_at)}
          </span>
        ) : (
          <span className="shrink-0 text-xs text-steel tnum">{whenShort(row.last_message_at)}</span>
        )}
      </span>
      <span className="mt-0.5 line-clamp-1 text-sm text-steel">
        {ROLE_PREFIX[row.preview_role ?? ""] ?? ""}
        {row.preview ?? "Голосовое сообщение"}
      </span>
      <span className="mt-1 flex flex-wrap gap-x-2 gap-y-0.5 text-xs text-steel">
        <span>{CHANNEL_NAMES[row.channel ?? ""] ?? row.channel}</span>
        {row.mode === "human" && (
          <span className="font-medium text-ink">
            {row.assignee_name ? `у менеджера: ${row.assignee_name}` : "у менеджера"}
          </span>
        )}
        {row.mode !== "human" && row.assignee_name && <span>{row.assignee_name}</span>}
        {row.lead_status && (
          <span className="font-medium text-ink">
            заявка: {LEAD_STATUS[row.lead_status].toLowerCase()}
          </span>
        )}
      </span>
      {row.tags.length > 0 && (
        <span className="mt-1.5 flex flex-wrap gap-1">
          {row.tags.slice(0, 2).map((item) => (
            <Chip key={item} className="max-w-36">
              {item}
            </Chip>
          ))}
          {row.tags.length > 2 && (
            <span className="text-xs text-steel">+{row.tags.length - 2}</span>
          )}
        </span>
      )}
    </Link>
  );
}

function List({
  filter,
  tag,
  activeId,
}: {
  filter: Filter;
  tag: string | null;
  activeId: string | null;
}) {
  const [pages, setPages] = useState<Record<string, Row[]>>({});
  const [next, setNext] = useState<string | null | undefined>(undefined);
  const [loadingMore, setLoadingMore] = useState(false);
  const [input, setInput] = useState("");
  const [q, setQ] = useState("");

  useEffect(() => {
    const timer = setTimeout(() => {
      setQ(input.trim());
      setNext(undefined);
    }, 300);
    return () => clearTimeout(timer);
  }, [input]);

  const { data, error, isLoading, mutate } = useSWR(
    `/conversations?filter=${filter}&q=${q}&tag=${tag ?? ""}`,
    () =>
      unwrap(
        api.GET("/conversations", {
          params: { query: { filter, q: q || undefined, tag: tag ?? undefined } },
        }),
      ),
    { keepPreviousData: true },
  );
  const { data: tags } = useSWR("/conversations/tags", () =>
    unwrap(api.GET("/conversations/tags")),
  );

  const counts = data?.counts;
  const bucket = `${filter}:${q}:${tag ?? ""}`;
  const more = pages[bucket] ?? [];
  const cursor = next === undefined ? data?.next_before : next;

  async function loadMore() {
    if (!cursor) return;
    setLoadingMore(true);
    try {
      const page = await unwrap(
        api.GET("/conversations", {
          params: { query: { filter, before: cursor, q: q || undefined, tag: tag ?? undefined } },
        }),
      );
      setPages({ ...pages, [bucket]: [...more, ...page.items] });
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
        <div className="relative mt-3">
          <Search
            className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-steel"
            aria-hidden
          />
          <label htmlFor="dialog-search" className="sr-only">
            Поиск по диалогам
          </label>
          <input
            id="dialog-search"
            type="search"
            value={input}
            onChange={(event) => setInput(event.target.value)}
            placeholder="Имя, телефон или текст"
            className="min-h-10 w-full rounded-md border border-control bg-paper pr-3 pl-9 text-sm hover:border-ink"
          />
        </div>
        <nav aria-label="Фильтр диалогов" className="mt-3 -ml-1 flex flex-wrap gap-1">
          {FILTERS.map((item) => {
            const active = item.value === filter;
            const value = counts?.[item.value];
            return (
              <Link
                key={item.value}
                href={dialogsHref(item.value, tag)}
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
        {tags && tags.length > 0 && (
          <nav aria-label="Фильтр по метке" className="mt-2 flex flex-wrap gap-1.5">
            {tags.slice(0, 12).map((item) => {
              const active = item.tag === tag;
              return (
                <Link
                  key={item.tag}
                  href={dialogsHref(filter, active ? null : item.tag)}
                  aria-current={active ? "true" : undefined}
                  onClick={() => setNext(undefined)}
                  className={cn(
                    "flex min-h-8 max-w-full items-center gap-1 rounded-full border px-2.5 text-xs",
                    active ? "border-ink bg-ink text-paper" : "border-line text-ink hover:bg-haze",
                  )}
                >
                  <span className="truncate">{item.tag}</span>
                  <span className={cn("tnum", active ? "text-haze" : "text-steel")}>
                    {item.count}
                  </span>
                </Link>
              );
            })}
          </nav>
        )}
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto">
        {isLoading && !data && <Loading className="px-4" />}
        {error ? (
          <div className="px-4">
            <LoadError error={error} retry={() => void mutate()} />
          </div>
        ) : null}
        {data && rows.length === 0 && (
          <div className="px-4">
            {q || tag ? (
              <Empty title="Ничего не нашлось">
                {tag && !q
                  ? `С меткой «${tag}» здесь диалогов нет.`
                  : "Проверьте написание или поищите по телефону."}
              </Empty>
            ) : (
              <Empty title={EMPTY[filter].title}>{EMPTY[filter].text}</Empty>
            )}
          </div>
        )}
        <ul className="divide-y divide-line">
          {rows.map((row) => (
            <li key={row.id}>
              <RowLink row={row} active={row.id === activeId} filter={filter} tag={tag} />
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
  const filter: Filter = FILTERS.some((item) => item.value === raw) ? (raw as Filter) : "all";
  const tag = params.get("tag");

  return (
    <div
      className={cn(
        "flex min-h-0 lg:flex-1",
        id ? "max-lg:h-[calc(100dvh-3.5rem)]" : "max-lg:h-[calc(100dvh-7rem)]",
      )}
    >
      <h1 className="sr-only">Диалоги</h1>
      <div
        className={cn(
          "flex min-h-0 w-full flex-col border-r border-line lg:w-80 lg:shrink-0 xl:w-96",
          id && "max-lg:hidden",
        )}
      >
        <List filter={filter} tag={tag} activeId={id} />
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
