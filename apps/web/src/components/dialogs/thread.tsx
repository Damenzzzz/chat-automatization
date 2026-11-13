"use client";

import { ArrowLeft, Mic, Package, SendHorizontal, Sparkles, TriangleAlert } from "lucide-react";
import Link from "next/link";
import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import useSWR, { useSWRConfig } from "swr";

import { Button } from "@/components/ui/button";
import { Notice } from "@/components/ui/notice";
import { FormError, LoadError, Loading } from "@/components/ui/page";
import { api, type Schemas } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";
import { useSession } from "@/components/shell/session";
import { memberLabel, useTeam } from "@/components/shop/team";
import { clock, money, shortDay } from "@/lib/format";
import { cn } from "@/lib/utils";

import { CHANNEL_NAMES, customerName, LEAD_STATUS, PAUSED } from "./labels";
import { CustomerCard } from "./customer-card";
import { LeadCard } from "./lead-card";
import { HowBotFound } from "./trace";

type Message = Schemas["MessageOut"];
type Detail = Schemas["ConversationDetail"];

function ProductCard({ card }: { card: Schemas["CardOut"] }) {
  const stock =
    card.stock === null || card.stock === undefined
      ? null
      : card.stock > 0
        ? `В наличии: ${card.stock}`
        : "Нет в наличии";
  return (
    <div className="flex w-full max-w-xs gap-3 rounded-md border border-line bg-paper p-2 text-left text-ink">
      <div className="flex size-14 shrink-0 items-center justify-center overflow-hidden rounded-sm bg-mist">
        {card.image ? (
          // eslint-disable-next-line @next/next/no-img-element -- адреса фото магазинов заранее неизвестны
          <img src={card.image} alt="" className="size-full object-cover" />
        ) : (
          <Package className="size-5 text-steel" aria-hidden />
        )}
      </div>
      <div className="min-w-0 text-sm">
        <p className="line-clamp-2 font-medium">{card.name}</p>
        <p className="tnum">{money(card.price)}</p>
        <p className="text-xs text-steel">{[stock, card.sku].filter(Boolean).join(", ")}</p>
      </div>
    </div>
  );
}

function Bubble({ message }: { message: Message }) {
  if (message.role === "system") {
    return <p className="self-center text-center text-xs text-steel">{message.content}</p>;
  }
  const fromCustomer = message.role === "customer";
  return (
    <div
      className={cn(
        "flex max-w-[88%] flex-col gap-1.5 sm:max-w-[75%]",
        fromCustomer ? "items-start self-start" : "items-end self-end",
      )}
    >
      <div
        className={cn(
          "rounded-lg px-3.5 py-2 whitespace-pre-wrap",
          "[overflow-wrap:anywhere]",
          fromCustomer && "border border-line bg-paper",
          message.role === "bot" && "bg-sky-soft",
          message.role === "manager" && "bg-ink text-paper",
        )}
      >
        {message.voice && (
          <span
            className={cn(
              "mb-1 flex items-center gap-1 text-xs",
              message.role === "manager" ? "text-haze" : "text-steel",
            )}
          >
            <Mic className="size-3.5" aria-hidden />
            Голосовое, расшифровка
          </span>
        )}
        {message.content ?? <span className="text-steel">Без текста</span>}
      </div>
      {message.cards.map((card) => (
        <ProductCard key={card.id} card={card} />
      ))}
      <p className="flex items-center gap-1.5 text-xs text-steel">
        <span>
          {message.role === "bot" ? "Бот, " : message.role === "manager" ? "Менеджер, " : ""}
          {clock(message.created_at)}
        </span>
        {message.delivered === false && (
          <span className="flex items-center gap-1 font-medium text-alert">
            <TriangleAlert className="size-3.5" aria-hidden />
            Не доставлено
          </span>
        )}
      </p>
      {message.role === "bot" && (
        <HowBotFound steps={message.steps} model={message.model} latencyMs={message.latency_ms} />
      )}
      {message.role === "manager" && message.delivered === false && (
        <p className="text-xs text-alert">
          {String(message.steps[0]?.error ?? "Канал недоступен")}
        </p>
      )}
    </div>
  );
}

function Messages({ detail }: { detail: Detail }) {
  const end = useRef<HTMLDivElement>(null);
  const last = detail.messages.at(-1)?.id;
  useEffect(() => {
    end.current?.scrollIntoView({ block: "end" });
  }, [last, detail.id]);

  const days: string[] = [];
  return (
    <div
      role="log"
      aria-label="Переписка"
      aria-live="polite"
      tabIndex={0}
      className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto bg-paper px-4 py-4 sm:px-6"
    >
      {detail.messages.map((message) => {
        const day = shortDay(message.created_at);
        const showDay = !days.includes(day);
        if (showDay) days.push(day);
        return (
          <div key={message.id} className="contents">
            {showDay && <p className="self-center text-xs text-steel">{day}</p>}
            <Bubble message={message} />
          </div>
        );
      })}
      <div ref={end} />
    </div>
  );
}

function Composer({ id, human, onSent }: { id: string; human: boolean; onSent: () => void }) {
  const { shop } = useSession();
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [draft, setDraft] = useState<Schemas["DraftOut"] | null>(null);
  const [drafting, setDrafting] = useState(false);
  const field = useRef<HTMLTextAreaElement>(null);
  const templates = shop?.reply_templates ?? [];

  async function send(event?: FormEvent) {
    event?.preventDefault();
    if (!text.trim() || busy) return;
    setBusy(true);
    setError(null);
    try {
      await unwrap(
        api.POST("/conversations/{conversation_id}/reply", {
          params: { path: { conversation_id: id } },
          body: { text },
        }),
      );
      setText("");
      setDraft(null);
      onSent();
    } catch (failure) {
      setError(failure);
    } finally {
      setBusy(false);
    }
  }

  async function suggest() {
    setDrafting(true);
    setError(null);
    try {
      setDraft(
        await unwrap(
          api.POST("/conversations/{conversation_id}/draft", {
            params: { path: { conversation_id: id } },
          }),
        ),
      );
    } catch (failure) {
      setError(failure);
    } finally {
      setDrafting(false);
    }
  }

  function insert(value: string) {
    setText((current) => (current.trim() ? `${current.trimEnd()}\n${value}` : value));
    field.current?.focus();
  }

  function keydown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key !== "Enter" || event.nativeEvent.isComposing) return;
    const touch = window.matchMedia("(pointer: coarse)").matches;
    if (event.metaKey || event.ctrlKey || (!event.shiftKey && !touch)) {
      event.preventDefault();
      void send();
    }
  }

  return (
    <form onSubmit={send} className="flex flex-col gap-2 border-t border-line bg-paper p-3">
      <FormError error={error} />
      {draft && (
        <div className="rounded-md border border-dashed border-sky bg-sky-soft p-3 text-sm">
          <p className="flex flex-wrap items-baseline justify-between gap-x-3 font-medium">
            Черновик бота
            <span className="text-xs font-normal text-steel">
              {draft.verified
                ? "цены сверены с каталогом"
                : "проверьте суммы: бот не нашёл их в каталоге"}
            </span>
          </p>
          <p className="mt-1 [overflow-wrap:anywhere] whitespace-pre-wrap">{draft.text}</p>
          <div className="mt-2 flex flex-wrap gap-2">
            <Button
              variant="dark"
              className="min-h-9 px-3 sm:min-h-9"
              onClick={() => {
                insert(draft.text);
                setDraft(null);
              }}
            >
              Вставить
            </Button>
            <Button
              variant="secondary"
              className="min-h-9 px-3 sm:min-h-9"
              loading={drafting}
              onClick={() => void suggest()}
            >
              Другой вариант
            </Button>
          </div>
        </div>
      )}
      <div className="flex flex-wrap gap-1.5">
        {!draft && (
          <button
            type="button"
            disabled={drafting}
            onClick={() => void suggest()}
            className="flex min-h-8 items-center gap-1.5 rounded-full border border-sky bg-sky-soft px-3 text-xs font-medium hover:bg-paper disabled:opacity-60"
          >
            <Sparkles className="size-3.5" aria-hidden />
            {drafting ? "Бот пишет черновик" : "Черновик от бота"}
          </button>
        )}
        {templates.map((template) => (
          <button
            key={template.title}
            type="button"
            title={template.text}
            onClick={() => insert(template.text)}
            className="min-h-8 rounded-full border border-line bg-paper px-3 text-xs hover:border-control"
          >
            {template.title}
          </button>
        ))}
      </div>
      <div className="flex items-end gap-2">
        <label htmlFor="manager-reply" className="sr-only">
          Ваш ответ покупателю
        </label>
        <textarea
          id="manager-reply"
          ref={field}
          rows={2}
          maxLength={4000}
          value={text}
          onChange={(event) => setText(event.target.value)}
          onKeyDown={keydown}
          placeholder={human ? "Ответ покупателю" : "Напишите сами, и диалог перейдёт к вам"}
          className="min-w-0 flex-1 resize-none rounded-md border border-control px-3 py-2 hover:border-ink"
        />
        <Button type="submit" loading={busy} disabled={!text.trim()}>
          <SendHorizontal aria-hidden />
          <span className="max-sm:sr-only">Отправить</span>
        </Button>
      </div>
      <p className="text-xs text-steel max-sm:hidden">
        Enter отправляет, Shift+Enter переносит строку.
        {!human && " Пока вы не написали, отвечает бот."}
      </p>
    </form>
  );
}

function LeadsPanel({ detail }: { detail: Detail }) {
  if (!detail.leads.length) return null;
  return (
    <div className="flex flex-col gap-6">
      {detail.leads.map((lead) => (
        <LeadCard key={lead.id} lead={lead} />
      ))}
    </div>
  );
}

export function Thread({ id }: { id: string }) {
  const { mutate: mutateGlobal } = useSWRConfig();
  const key = `/conversations/${id}`;
  const { data, error, isLoading, mutate } = useSWR(key, () =>
    unwrap(
      api.GET("/conversations/{conversation_id}", { params: { path: { conversation_id: id } } }),
    ),
  );
  const team = useTeam();
  const [switching, setSwitching] = useState(false);
  const [switchError, setSwitchError] = useState<unknown>(null);
  const [assignee, setAssignee] = useState<string | null | undefined>(undefined);

  function refreshAll() {
    void mutate();
    void mutateGlobal((item) => typeof item === "string" && item.startsWith("/conversations?"));
  }

  async function setMode(path: "takeover" | "release") {
    setSwitching(true);
    setSwitchError(null);
    try {
      const params = { params: { path: { conversation_id: id } } };
      await unwrap(
        path === "takeover"
          ? api.POST("/conversations/{conversation_id}/takeover", params)
          : api.POST("/conversations/{conversation_id}/release", params),
      );
      refreshAll();
    } catch (failure) {
      setSwitchError(failure);
    } finally {
      setSwitching(false);
    }
  }

  async function assign(value: string) {
    setAssignee(value || null);
    setSwitchError(null);
    try {
      await unwrap(
        api.PATCH("/conversations/{conversation_id}", {
          params: { path: { conversation_id: id } },
          body: { assignee_id: value || null },
        }),
      );
      await mutate();
      void mutateGlobal((item) => typeof item === "string" && item.startsWith("/conversations?"));
    } catch (failure) {
      setSwitchError(failure);
    } finally {
      setAssignee(undefined);
    }
  }

  if (isLoading) return <Loading className="px-6" />;
  if (error || !data) {
    return (
      <div className="px-6">
        <LoadError error={error} retry={() => void mutate()} />
      </div>
    );
  }

  const human = data.mode === "human";
  const lead = data.leads[0];
  const assigneeId = assignee === undefined ? data.assignee_id : assignee;
  const outsider =
    data.assignee_id && !team.some((member) => member.id === data.assignee_id)
      ? { id: data.assignee_id, label: data.assignee_name ?? "Сотрудник" }
      : null;

  return (
    <div className="flex min-h-0 flex-1 flex-col lg:flex-row">
      <section
        aria-label={`Диалог: ${customerName(data)}`}
        className="flex min-h-0 min-w-0 flex-1 flex-col"
      >
        <header
          className={cn(
            "flex flex-wrap items-center gap-x-4 gap-y-2 border-b px-4 py-2.5 transition-colors duration-300 sm:px-6",
            human ? "on-ink border-ink bg-ink text-paper" : "border-line bg-paper text-ink",
          )}
        >
          <Link
            href="/dialogs"
            aria-label="К списку диалогов"
            className="-ml-2 flex size-11 items-center justify-center rounded-md lg:hidden"
          >
            <ArrowLeft className="size-5" aria-hidden />
          </Link>
          <div className="min-w-0 flex-1">
            <h2 className="truncate text-base">{customerName(data)}</h2>
            <p className={cn("truncate text-xs", human ? "text-haze" : "text-steel")}>
              {human ? "Отвечает менеджер" : "Отвечает бот"},{" "}
              {CHANNEL_NAMES[data.channel ?? ""] ?? data.channel}
            </p>
          </div>
          <label className="flex min-w-0 items-center gap-2 text-xs">
            <span className={human ? "text-haze" : "text-steel"}>Ответственный</span>
            <select
              value={assigneeId ?? ""}
              disabled={assignee !== undefined}
              onChange={(event) => void assign(event.target.value)}
              className="min-h-11 max-w-44 min-w-0 rounded-md border border-control bg-paper px-2 text-base text-ink hover:border-ink sm:min-h-10 sm:text-sm"
            >
              <option value="">Не назначен</option>
              {outsider && <option value={outsider.id}>{outsider.label}</option>}
              {team.map((member) => (
                <option key={member.id} value={member.id}>
                  {memberLabel(member)}
                </option>
              ))}
            </select>
          </label>
          <Button
            variant={human ? "onInk" : "primary"}
            loading={switching}
            onClick={() => void setMode(human ? "release" : "takeover")}
            className="max-sm:w-full"
          >
            {human ? "Вернуть боту" : "Перехватить"}
          </Button>
        </header>
        {data.paused_reason && PAUSED[data.paused_reason] && (
          <Notice className="m-3 mb-0">{PAUSED[data.paused_reason]}</Notice>
        )}
        {switchError ? (
          <div className="m-3 mb-0">
            <FormError error={switchError} />
          </div>
        ) : null}
        <details className="border-b border-line xl:hidden">
          <summary className="flex min-h-11 items-center px-4 text-sm font-medium sm:px-6">
            Покупатель
            {lead
              ? `, заявка: ${LEAD_STATUS[lead.status].toLowerCase()}${lead.total_kzt ? ` на ${money(lead.total_kzt)}` : ""}`
              : ""}
          </summary>
          <div className="flex flex-col gap-6 px-4 pb-4 sm:px-6">
            <CustomerCard
              conversationId={id}
              customer={data.customer}
              onSaved={() => void mutate()}
            />
            <LeadsPanel detail={data} />
          </div>
        </details>
        <Messages detail={data} />
        {data.channel ? (
          <Composer key={id} id={id} human={human} onSent={refreshAll} />
        ) : (
          <p className="border-t border-line bg-paper px-4 py-3 text-sm text-steel sm:px-6">
            Диалог не связан с каналом, ответить в него нельзя.
          </p>
        )}
      </section>
      <aside
        aria-label="Покупатель"
        className="hidden w-72 shrink-0 flex-col gap-6 overflow-y-auto border-l border-line bg-canvas p-5 xl:flex"
      >
        <CustomerCard conversationId={id} customer={data.customer} onSaved={() => void mutate()} />
        {lead && (
          <div>
            <h2 className="mb-3 text-lg">Заявка</h2>
            <LeadsPanel detail={data} />
          </div>
        )}
      </aside>
    </div>
  );
}
