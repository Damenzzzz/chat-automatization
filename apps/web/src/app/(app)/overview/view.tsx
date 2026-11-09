"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import useSWR from "swr";

import { DialogsChart } from "@/components/overview/dialogs-chart";
import { Unanswered } from "@/components/overview/unanswered";
import { Empty, LoadError, Loading, Page, PageHeader, Section } from "@/components/ui/page";
import { api, type Schemas } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";
import { count, money, plural } from "@/lib/format";
import { cn } from "@/lib/utils";

const PERIODS = [
  { days: 7, label: "7 дней" },
  { days: 30, label: "30 дней" },
];

function localDate(date: Date): string {
  const shifted = new Date(date.getTime() - date.getTimezoneOffset() * 60_000);
  return shifted.toISOString().slice(0, 10);
}

function rangeOf(days: number) {
  const to = new Date();
  const from = new Date(to.getTime() - (days - 1) * 86_400_000);
  return { date_from: localDate(from), date_to: localDate(to) };
}

function Change({ value }: { value: number | null | undefined }) {
  if (value === null || value === undefined) return <>нет данных за прошлый период</>;
  const rounded = Math.round(Math.abs(value));
  if (rounded === 0) return <>как в прошлый период</>;
  return (
    <>
      на {rounded}% {value > 0 ? "больше" : "меньше"}, чем в прошлый период
    </>
  );
}

function Figure({
  label,
  value,
  note,
  accent,
}: {
  label: string;
  value: string;
  note: React.ReactNode;
  accent?: boolean;
}) {
  return (
    <div
      className={cn(
        "relative min-w-0 overflow-hidden rounded-[20px] p-5 transition-transform hover:-translate-y-0.5",
        accent
          ? "on-ink bg-night text-paper shadow-[0_20px_40px_-20px_rgb(0_178_207/0.6)]"
          : "panel",
      )}
    >
      <span
        aria-hidden
        className={cn(
          "pointer-events-none absolute -top-16 -right-16 size-40 rounded-full blur-2xl",
          accent ? "bg-sky/50" : "bg-sky/15",
        )}
      />
      <dt className={cn("relative text-sm", accent ? "text-paper/70" : "text-steel")}>{label}</dt>
      <dd className="relative">
        <span
          className={cn(
            "display mt-1 block text-[2.25rem] leading-tight tnum",
            accent && "text-sky-gradient",
          )}
        >
          {value}
        </span>
        <span className={cn("mt-1 block text-xs", accent ? "text-paper/60" : "text-steel")}>
          {note}
        </span>
      </dd>
    </div>
  );
}

function Metrics({ data }: { data: Schemas["OverviewOut"] }) {
  const { current, change_percent: change } = data;
  const share = current.bot_resolved_share;
  const seconds =
    current.avg_response_ms === null || current.avg_response_ms === undefined
      ? null
      : current.avg_response_ms / 1000;
  return (
    <dl className="grid grid-cols-2 gap-3 pb-6 lg:grid-cols-4 lg:gap-4">
      <Figure
        label="Диалоги"
        value={count(current.dialogs)}
        note={<Change value={change.dialogs} />}
      />
      <Figure
        accent
        label="Бот справился сам"
        value={share === null || share === undefined ? "нет данных" : `${Math.round(share * 100)}%`}
        note={`${count(current.bot_resolved)} ${plural(current.bot_resolved, "диалог", "диалога", "диалогов")} без менеджера`}
      />
      <Figure
        label="Заявки"
        value={count(current.leads)}
        note={`на ${money(current.leads_total_kzt)}`}
      />
      <Figure
        label="Скорость ответа"
        value={seconds === null ? "нет данных" : `${seconds.toFixed(1).replace(".", ",")} с`}
        note="в среднем"
      />
    </dl>
  );
}

function TopQueries({ items }: { items: Schemas["TopQueryOut"][] }) {
  if (!items.length) {
    return (
      <Empty title="Покупатели ещё ничего не искали">Здесь появятся самые частые запросы.</Empty>
    );
  }
  const max = Math.max(...items.map((item) => item.count));
  return (
    <ol className="flex flex-col gap-3">
      {items.slice(0, 8).map((item) => (
        <li key={item.query}>
          <div className="flex items-baseline justify-between gap-3 text-sm">
            <span className="min-w-0 break-words">{item.query}</span>
            <span className="shrink-0 text-steel tnum">{count(item.count)}</span>
          </div>
          <div aria-hidden className="mt-1 h-1 rounded-sm bg-haze">
            <div
              className="h-full rounded-sm bg-sky"
              style={{ width: `${(item.count / max) * 100}%` }}
            />
          </div>
          {!item.found && <p className="mt-1 text-xs font-medium">Такого нет в каталоге</p>}
          {item.found && item.in_stock === false && (
            <p className="mt-1 text-xs font-medium">Нашёлся, но нет в наличии</p>
          )}
        </li>
      ))}
    </ol>
  );
}

function BalanceLine() {
  const { data } = useSWR("/balance", () => unwrap(api.GET("/balance")));
  if (!data) return null;
  return (
    <Link href="/balance" className="text-sm tnum underline-offset-2 hover:underline">
      На балансе <span className="font-medium">{money(data.balance_kzt)}</span>
    </Link>
  );
}

export function OverviewView() {
  const [days, setDays] = useState(7);
  const range = useMemo(() => rangeOf(days), [days]);
  const suffix = `${range.date_from}&${range.date_to}`;
  const overview = useSWR(`/analytics/overview?${suffix}`, () =>
    unwrap(api.GET("/analytics/overview", { params: { query: range } })),
  );
  const series = useSWR(`/analytics/dialogs_by_day?${suffix}`, () =>
    unwrap(api.GET("/analytics/dialogs_by_day", { params: { query: range } })),
  );
  const queries = useSWR(`/analytics/top_queries?${suffix}`, () =>
    unwrap(api.GET("/analytics/top_queries", { params: { query: range } })),
  );

  return (
    <Page>
      <PageHeader
        title="Обзор"
        actions={
          <div role="group" aria-label="Период" className="flex gap-1">
            {PERIODS.map((period) => (
              <button
                key={period.days}
                type="button"
                aria-pressed={period.days === days}
                onClick={() => setDays(period.days)}
                className={cn(
                  "min-h-11 rounded-md px-3 text-sm sm:min-h-9",
                  period.days === days ? "bg-ink text-paper" : "hover:bg-haze",
                )}
              >
                {period.label}
              </button>
            ))}
          </div>
        }
      >
        <BalanceLine />
      </PageHeader>
      {overview.isLoading && <Loading />}
      {overview.error ? (
        <LoadError error={overview.error} retry={() => void overview.mutate()} />
      ) : null}
      {overview.data && <Metrics data={overview.data} />}
      <Section title="Диалоги по дням">
        {series.data ? (
          <DialogsChart days={series.data} />
        ) : series.error ? (
          <LoadError error={series.error} />
        ) : (
          <Loading />
        )}
      </Section>
      <div className="grid gap-x-10 lg:grid-cols-[minmax(0,2fr)_minmax(0,3fr)]">
        <Section title="Что ищут покупатели">
          {queries.data ? (
            <TopQueries items={queries.data} />
          ) : queries.error ? (
            <LoadError error={queries.error} />
          ) : (
            <Loading />
          )}
        </Section>
        <Section
          title="Бот не знал ответа"
          description="Ответьте один раз, и бот будет знать это дальше."
        >
          <Unanswered range={range} />
        </Section>
      </div>
    </Page>
  );
}
