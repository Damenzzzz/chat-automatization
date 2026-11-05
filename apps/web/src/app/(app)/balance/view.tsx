"use client";

import { Download } from "lucide-react";
import { useState, type FormEvent } from "react";
import useSWR from "swr";

import { useSession } from "@/components/shell/session";
import { Button } from "@/components/ui/button";
import { TextField } from "@/components/ui/field";
import { Notice } from "@/components/ui/notice";
import { FormError, LoadError, Loading, Page, PageHeader, Section } from "@/components/ui/page";
import { api, apiFetch, type Schemas } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";
import { count, fullDate, money, plural } from "@/lib/format";
import { cn } from "@/lib/utils";

const PRESETS = [10_000, 30_000, 50_000, 100_000];
const MIN_AMOUNT = 1_000;
const LOW_SHARE = 0.2;

function forecast(days: number | null | undefined): string {
  if (days === null || days === undefined)
    return "Прогноз появится, когда бот начнёт отвечать покупателям.";
  if (days > 365) return "При таком расходе хватит больше чем на год.";
  if (days === 0) return "При таком расходе средств хватит меньше чем на день.";
  return `При таком расходе хватит примерно на ${count(days)} ${plural(days, "день", "дня", "дней")}.`;
}

function Hero({ data }: { data: Schemas["BalanceOut"] }) {
  const empty = data.balance_kzt <= 0;
  const low =
    !empty && data.last_topup_kzt ? data.balance_kzt <= data.last_topup_kzt * LOW_SHARE : false;
  const alarm = empty || low;
  const perReply = data.replies_7d ? Math.ceil(data.spent_7d_kzt / data.replies_7d) : null;
  return (
    <section
      aria-label="Текущий баланс"
      className={cn("rounded-md px-5 py-6 sm:px-6", alarm ? "on-ink bg-ink text-paper" : "bg-mist")}
    >
      <p className={cn("text-sm", alarm ? "text-haze" : "text-steel")}>На балансе</p>
      <p className="display mt-1 text-3xl break-words tnum">{money(data.balance_kzt)}</p>
      <p className="mt-2 max-w-xl">
        {empty
          ? "Баланс закончился. Бот не отвечает покупателям, сообщения ждут менеджера. После пополнения диалоги вернутся к боту сами."
          : low
            ? `Баланс заканчивается. ${forecast(data.days_left)}`
            : forecast(data.days_left)}
      </p>
      <p className={cn("mt-3 text-sm tnum", alarm ? "text-haze" : "text-steel")}>
        За 7 дней списано {money(data.spent_7d_kzt)}, ответов бота: {count(data.replies_7d)}
        {perReply ? `, в среднем около ${money(perReply)} за ответ` : ""}.
      </p>
    </section>
  );
}

async function downloadInvoice(amount: number) {
  const response = await apiFetch(new Request(`/api/billing/invoice?amount_kzt=${amount}`));
  if (!response.ok) {
    const json: unknown = await response.json().catch(() => ({}));
    await unwrap(Promise.resolve({ error: json, response }));
    return;
  }
  const url = URL.createObjectURL(await response.blob());
  const link = document.createElement("a");
  link.href = url;
  link.download = `satushy-schet-${amount}.pdf`;
  link.click();
  URL.revokeObjectURL(url);
}

function InvoiceForm() {
  const [amount, setAmount] = useState("30000");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [done, setDone] = useState(false);
  const value = Number(amount.replace(/\D/g, ""));
  const tooSmall = Boolean(amount) && value < MIN_AMOUNT;

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (value < MIN_AMOUNT) return;
    setBusy(true);
    setError(null);
    setDone(false);
    try {
      await downloadInvoice(value);
      setDone(true);
    } catch (failure) {
      setError(failure);
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} className="flex max-w-xl flex-col gap-4">
      <div role="group" aria-label="Готовые суммы" className="flex flex-wrap gap-2">
        {PRESETS.map((preset) => (
          <button
            key={preset}
            type="button"
            aria-pressed={value === preset}
            onClick={() => setAmount(String(preset))}
            className={cn(
              "min-h-11 rounded-md border px-3 text-sm tnum sm:min-h-10",
              value === preset ? "border-ink bg-mist font-medium" : "border-control hover:bg-mist",
            )}
          >
            {money(preset)}
          </button>
        ))}
      </div>
      <TextField
        label="Сумма в тенге"
        inputMode="numeric"
        value={amount}
        error={tooSmall ? `Минимальная сумма счёта ${money(MIN_AMOUNT)}.` : null}
        onChange={(event) => setAmount(event.target.value.replace(/\D/g, "").slice(0, 9))}
      />
      <FormError error={error} />
      {done && (
        <Notice kind="success">
          Счёт скачан. Оплатите его со счёта ИП или ТОО. Баланс пополним, как только деньги
          поступят.
        </Notice>
      )}
      <div>
        <Button type="submit" loading={busy} disabled={value < MIN_AMOUNT}>
          <Download aria-hidden />
          Счёт для ИП
        </Button>
      </div>
    </form>
  );
}

function Notifications() {
  const { data, mutate } = useSWR("/notifications", () => unwrap(api.GET("/notifications")));
  if (!data?.length)
    return (
      <p className="text-sm text-steel">Предупредим, когда останется 20% и 5% от пополнения.</p>
    );

  async function read(id: string) {
    await unwrap(
      api.POST("/notifications/{notification_id}/read", {
        params: { path: { notification_id: id } },
      }),
    );
    void mutate();
  }

  return (
    <ul className="divide-y divide-line">
      {data.slice(0, 10).map((item) => (
        <li
          key={item.id}
          className="flex flex-wrap items-start justify-between gap-x-4 gap-y-1 py-3 text-sm"
        >
          <div className="min-w-0 flex-1 basis-60">
            <p className={item.read_at ? "text-steel" : "font-medium"}>{item.text}</p>
            <p className="mt-0.5 text-xs text-steel">{fullDate(item.created_at)}</p>
          </div>
          {!item.read_at && (
            <Button variant="ghost" onClick={() => void read(item.id)}>
              Прочитано
            </Button>
          )}
        </li>
      ))}
    </ul>
  );
}

export function BalanceView() {
  const { isOwner } = useSession();
  const { data, error, isLoading, mutate } = useSWR("/balance", () => unwrap(api.GET("/balance")));
  return (
    <Page>
      <PageHeader title="Баланс">
        Каждый ответ бота покупателю оплачивается с этого баланса. Песочница бесплатна.
      </PageHeader>
      {isLoading && <Loading />}
      {error ? <LoadError error={error} retry={() => void mutate()} /> : null}
      {data && <Hero data={data} />}
      {isOwner && (
        <Section
          title="Пополнить"
          description="Выставим счёт на реквизиты вашего ИП или ТОО."
          className="mt-8"
        >
          <InvoiceForm />
        </Section>
      )}
      <Section title="Уведомления">
        <Notifications />
      </Section>
    </Page>
  );
}
