"use client";

import Link from "next/link";
import type { ReactNode } from "react";
import useSWR from "swr";

import { CHANNEL_NAMES, customerName } from "@/components/dialogs/labels";
import { useSession } from "@/components/shell/session";
import { buttonVariants } from "@/components/ui/button";
import { Loading } from "@/components/ui/page";
import { api } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";
import { money, plural, waitedFor } from "@/lib/format";
import { cn } from "@/lib/utils";

type Range = { date_from: string; date_to: string };

const LOW_BALANCE_DAYS = 5;
const MAX_WAITING = 5;

function Row({
  urgent,
  title,
  text,
  wait,
  href,
  action,
  primary,
}: {
  urgent?: boolean;
  title: string;
  text: ReactNode;
  wait?: string;
  href: string;
  action: string;
  primary?: boolean;
}) {
  return (
    <li className="flex flex-wrap items-center gap-x-4 gap-y-2 px-4 py-3 sm:px-5">
      <span
        aria-hidden
        className={cn(
          "size-2.5 shrink-0 rounded-full",
          urgent ? "border border-ink bg-sun" : "bg-sky",
        )}
      />
      <div className="min-w-0 flex-1 basis-48">
        <p className="truncate text-sm font-semibold">{title}</p>
        <p className="line-clamp-1 text-sm text-steel">{text}</p>
      </div>
      {wait && (
        <span className="rounded-full bg-sun-soft px-2.5 py-0.5 text-xs font-semibold tnum">
          ждёт {wait}
        </span>
      )}
      <Link
        href={href}
        className={cn(
          buttonVariants({ variant: primary ? "primary" : "secondary" }),
          "min-h-9 px-3 sm:min-h-9",
        )}
      >
        {action}
      </Link>
    </li>
  );
}

export function Queue({ range }: { range: Range }) {
  const { shop, isOwner } = useSession();
  const waiting = useSWR("/conversations?filter=human", () =>
    unwrap(api.GET("/conversations", { params: { query: { filter: "human" } } })),
  );
  const leads = useSWR("/leads?status=new&badge", () =>
    unwrap(api.GET("/leads", { params: { query: { status: "new" } } })),
  );
  const unanswered = useSWR(`/analytics/unanswered?${range.date_from}&${range.date_to}`, () =>
    unwrap(api.GET("/analytics/unanswered", { params: { query: range } })),
  );
  const balance = useSWR(isOwner ? "/balance" : null, () => unwrap(api.GET("/balance")));

  if (!waiting.data && waiting.isLoading) return <Loading />;

  const dialogs = (waiting.data?.items ?? []).filter((row) => row.waiting);
  const fresh = leads.data?.items ?? [];
  const total = fresh.reduce((sum, lead) => sum + (lead.total_kzt ?? 0), 0);
  const questions = unanswered.data?.total ?? 0;
  const top = unanswered.data?.groups[0];
  const days = balance.data?.days_left;
  const empty = balance.data !== undefined && balance.data.balance_kzt <= 0;
  const low = empty || (days !== null && days !== undefined && days <= LOW_BALANCE_DAYS);
  const nothing = !dialogs.length && !fresh.length && !questions && !low && !shop?.bot_paused;

  if (nothing) {
    return (
      <p className="px-4 py-5 text-sm text-steel sm:px-5">
        Всё разобрано: никто не ждёт менеджера, новых заявок нет. Бот отвечает сам.
      </p>
    );
  }

  return (
    <ul className="divide-y divide-line">
      {shop?.bot_paused && (
        <Row
          urgent
          title="Бот на паузе"
          text="Покупатели не получают ответа, пока вы не ответите сами или не включите бота."
          href="/dialogs"
          action="К диалогам"
        />
      )}
      {dialogs.slice(0, MAX_WAITING).map((row) => (
        <Row
          key={row.id}
          urgent
          primary
          title={`${customerName(row)}, ${CHANNEL_NAMES[row.channel ?? ""] ?? "чат"}`}
          text={row.preview ?? "Голосовое сообщение"}
          wait={waitedFor(row.last_message_at)}
          href={`/dialogs?id=${row.id}&filter=human`}
          action="Ответить"
        />
      ))}
      {dialogs.length > MAX_WAITING && (
        <Row
          urgent
          title={`Ещё ${dialogs.length - MAX_WAITING} ждут ответа`}
          text="Откройте список, чтобы увидеть всех."
          href="/dialogs?filter=human"
          action="Все"
        />
      )}
      {fresh.length > 0 && (
        <Row
          title={`${fresh.length} ${plural(fresh.length, "новая заявка", "новые заявки", "новых заявок")} на ${money(total)}`}
          text={
            [...new Set(fresh.map((lead) => lead.contact_name).filter(Boolean))].join(", ") ||
            "Позвоните покупателям и подтвердите заказ."
          }
          href="/leads?status=new"
          action="Открыть"
        />
      )}
      {questions > 0 && (
        <Row
          title={`${questions} ${plural(questions, "вопрос", "вопроса", "вопросов")} бот не знал`}
          text={top ? `Чаще всего: «${top.question}»` : "Ответьте один раз, и бот запомнит."}
          href="#unanswered"
          action="Научить бота"
        />
      )}
      {low && (
        <Row
          urgent={empty}
          title={empty ? "Баланс закончился" : `Баланса хватит примерно на ${days} дн.`}
          text={
            empty
              ? "Бот передаёт все диалоги менеджеру. Пополните баланс, и он вернётся к работе."
              : `На счёте ${money(balance.data?.balance_kzt)}. Пополните заранее, чтобы бот не остановился.`
          }
          href="/balance"
          action="Пополнить"
        />
      )}
    </ul>
  );
}
