"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";
import useSWR from "swr";

import { CHANNEL_NAMES, LEAD_STATUS } from "@/components/dialogs/labels";
import { LeadCard } from "@/components/dialogs/lead-card";
import { Button } from "@/components/ui/button";
import { Empty, LoadError, Loading, Page, PageHeader } from "@/components/ui/page";
import { api, type Schemas } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";
import { fullDate } from "@/lib/format";
import { cn } from "@/lib/utils";

type Status = "new" | "in_progress" | "done" | "cancelled";
const STATUSES = Object.keys(LEAD_STATUS) as Status[];

export function LeadsView() {
  const router = useRouter();
  const params = useSearchParams();
  const raw = params.get("status");
  const status = STATUSES.includes(raw as Status) ? (raw as Status) : undefined;
  const [more, setMore] = useState<Schemas["LeadRow"][]>([]);
  const [next, setNext] = useState<string | null | undefined>(undefined);
  const [loadingMore, setLoadingMore] = useState(false);

  const { data, error, isLoading, mutate } = useSWR(`/leads?status=${status ?? ""}`, () =>
    unwrap(api.GET("/leads", { params: { query: { status } } })),
  );

  const cursor = next === undefined ? data?.next_before : next;
  const seen = new Set(data?.items.map((lead) => lead.id));
  const rows = [...(data?.items ?? []), ...more.filter((lead) => !seen.has(lead.id))];

  async function loadMore() {
    if (!cursor) return;
    setLoadingMore(true);
    try {
      const page = await unwrap(
        api.GET("/leads", { params: { query: { status, before: cursor } } }),
      );
      setMore([...more, ...page.items]);
      setNext(page.next_before ?? null);
    } finally {
      setLoadingMore(false);
    }
  }

  function pick(value?: Status) {
    setMore([]);
    setNext(undefined);
    router.push(value ? `/leads?status=${value}` : "/leads");
  }

  return (
    <Page>
      <PageHeader title="Заявки">
        Бот оформляет заявку, когда покупатель готов купить. Дальше её ведёт менеджер.
      </PageHeader>
      <div role="group" aria-label="Фильтр по статусу" className="mb-4 -ml-1 flex flex-wrap gap-1">
        {[undefined, ...STATUSES].map((value) => (
          <button
            key={value ?? "all"}
            type="button"
            aria-pressed={value === status}
            onClick={() => pick(value)}
            className={cn(
              "min-h-11 rounded-md px-3 text-sm sm:min-h-9",
              value === status ? "bg-ink text-paper" : "hover:bg-haze",
            )}
          >
            {value ? LEAD_STATUS[value] : "Все"}
          </button>
        ))}
      </div>
      {isLoading && <Loading />}
      {error ? <LoadError error={error} retry={() => void mutate()} /> : null}
      {data && rows.length === 0 && (
        <Empty title={status ? "Таких заявок нет" : "Заявок пока нет"}>
          Проверьте в песочнице, как бот принимает заказ, или подключите канал.
        </Empty>
      )}
      <ul className="grid gap-4 md:grid-cols-2">
        {rows.map((lead) => (
          <li key={lead.id} className="panel p-5">
            <div className="mb-3 flex flex-wrap items-baseline justify-between gap-x-3 text-xs text-steel">
              <span>
                {fullDate(lead.created_at)}
                {lead.channel ? `, ${CHANNEL_NAMES[lead.channel] ?? lead.channel}` : ""}
              </span>
              {lead.conversation_id && (
                <Link
                  href={`/dialogs?id=${lead.conversation_id}`}
                  className="inline-flex min-h-8 items-center font-medium text-ink underline underline-offset-2"
                >
                  Открыть диалог
                </Link>
              )}
            </div>
            <LeadCard key={`${lead.id}-${lead.status}`} lead={lead} />
          </li>
        ))}
      </ul>
      {cursor && (
        <Button variant="secondary" loading={loadingMore} onClick={() => void loadMore()}>
          Показать ещё
        </Button>
      )}
    </Page>
  );
}
