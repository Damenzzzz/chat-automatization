"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import useSWR from "swr";

import { DialogsChart } from "@/components/overview/dialogs-chart";
import { Queue } from "@/components/overview/queue";
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
  const perLead = current.leads > 0 ? Math.round(current.spent_kzt / current.leads) : null;
  const spentShare =
    current.leads_total_kzt > 0 ? (current.spent_kzt / current.leads_total_kzt) * 100 : null;
  return (
    <dl className="grid grid-cols-2 gap-3 pb-4 lg:grid-cols-4 lg:gap-4">
      <Figure
        label="Заявки"
        value={money(current.leads_total_kzt)}
        note={
          <>
            {count(current.leads)} {plural(current.leads, "заявка", "заявки", "заявок")},{" "}
            <Change value={change.leads_total_kzt} />
          </>
        }
      />
      <Figure
        accent
        label="Бот справился сам"
        value={share === null || share === undefined ? "нет данных" : `${Math.round(share * 100)}%`}
        note={`${count(current.bot_resolved)} из ${count(current.dialogs)} ${plural(current.dialogs, "диалога", "диалогов", "диалогов")}`}
      />
      <Figure
        label="Расход на бота"
        value={money(current.spent_kzt)}
        note={
          spentShare === null
            ? "за ответы покупателям"
            : `${spentShare < 1 ? spentShare.toFixed(1).replace(".", ",") : Math.round(spentShare)}% от суммы заявок`
        }
      />
      <Figure
        label="Цена одной заявки"
        value={perLead === null ? "нет заявок" : money(perLead)}
        note="расход, делённый на заявки"
      />
    </dl>
  );
}

function Funnel({ data }: { data: Schemas["MetricsOut"] }) {
  const steps = [
    { label: "Диалоги", value: data.dialogs },
    { label: "Бот нашёл товар", value: Math.min(data.found_dialogs, data.dialogs) },
    { label: "Оставили заявку", value: data.leads },
    { label: "Заказ выполнен", value: data.leads_done },
  ];
  const max = Math.max(data.dialogs, 1);
  return (
    <ol className="flex flex-col gap-2.5">
      {steps.map((step, index) => {
        const previous = steps[index - 1]?.value;
        const rate = previous ? Math.round((step.value / previous) * 100) : null;
        return (
          <li
            key={step.label}
            className="grid grid-cols-[minmax(0,9rem)_minmax(0,1fr)_auto] items-center gap-3 text-sm"
          >
            <span className="text-steel">{step.label}</span>
            <span aria-hidden className="h-3.5 rounded-sm bg-haze">
              <span
                className="block h-full rounded-sm bg-sky"
                style={{ width: `${Math.min(100, (step.value / max) * 100)}%` }}
              />
            </span>
            <span className="min-w-16 text-right tnum">
              <span className="font-semibold">{count(step.value)}</span>
              {rate !== null && <span className="ml-1.5 text-xs text-steel">{rate}%</span>}
            </span>
          </li>
        );
      })}
    </ol>
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
  const overview = useSWR(
    `/analytics/overview?${suffix}`,
    () => unwrap(api.GET("/analytics/overview", { params: { query: range } })),
    { keepPreviousData: true },
  );
  const series = useSWR(
    `/analytics/dialogs_by_day?${suffix}`,
    () => unwrap(api.GET("/analytics/dialogs_by_day", { params: { query: range } })),
    { keepPreviousData: true },
  );
  const queries = useSWR(
    `/analytics/top_queries?${suffix}`,
    () => unwrap(api.GET("/analytics/top_queries", { params: { query: range } })),
    { keepPreviousData: true },
  );

  return (
    <Page>
      <PageHeader
        title="Сегодня"
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
      <section aria-label="Ждут вас" className="mb-4 overflow-hidden panel">
        <h2 className="border-b border-line px-4 py-3 text-lg sm:px-5">Ждут вас</h2>
        <Queue range={range} />
      </section>
      {overview.isLoading && !overview.data && <Loading />}
      {overview.error ? (
        <LoadError error={overview.error} retry={() => void overview.mutate()} />
      ) : null}
      {overview.data && <Metrics data={overview.data} />}
      {overview.data && (
        <Section
          title="Путь покупателя"
          description="Сколько диалогов дошло до заявки и выполненного заказа за период."
        >
          <Funnel data={overview.data.current} />
        </Section>
      )}
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
          id="unanswered"
          title="Бот не знал ответа"
          description="Ответьте один раз, и бот будет знать это дальше."
        >
          <Unanswered range={range} />
        </Section>
      </div>
    </Page>
  );
}
