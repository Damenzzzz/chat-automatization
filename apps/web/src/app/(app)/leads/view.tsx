"use client";

import { Download, Search } from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useRef, useState, type ReactNode } from "react";
import useSWR, { useSWRConfig } from "swr";

import { CHANNEL_NAMES, LEAD_STATUS } from "@/components/dialogs/labels";
import { control } from "@/components/leads/lead-fields";
import { LeadCards } from "@/components/leads/lead-cards";
import { LeadTable } from "@/components/leads/lead-table";
import type { LeadRow, LeadStatus } from "@/components/leads/use-lead";
import { useSession } from "@/components/shell/session";
import { memberLabel, useTeam, type Member } from "@/components/shop/team";
import { Button, buttonVariants } from "@/components/ui/button";
import { Notice } from "@/components/ui/notice";
import { Empty, FormError, LoadError, Loading, Page, PageHeader } from "@/components/ui/page";
import { api, type Schemas } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";
import { cn } from "@/lib/utils";

type Channel = "whatsapp" | "instagram" | "telegram" | "web";
type Filters = {
  status?: LeadStatus;
  assignee?: "me" | "none";
  due: boolean;
  channel?: Channel;
  q: string;
};

const STATUSES = Object.keys(LEAD_STATUS) as LeadStatus[];
const CHANNELS = Object.keys(CHANNEL_NAMES) as Channel[];
const BULK_LIMIT = 100;

function readFilters(params: URLSearchParams): Filters {
  const status = params.get("status");
  const assignee = params.get("assignee");
  const channel = params.get("channel");
  const due = params.get("due");
  return {
    status: STATUSES.includes(status as LeadStatus) ? (status as LeadStatus) : undefined,
    assignee: assignee === "me" || assignee === "none" ? assignee : undefined,
    due: due === "1" || due === "true",
    channel: CHANNELS.includes(channel as Channel) ? (channel as Channel) : undefined,
    q: params.get("q")?.trim() ?? "",
  };
}

function toQuery(filters: Filters, withDue = true): string {
  const params = new URLSearchParams();
  if (filters.status) params.set("status", filters.status);
  if (filters.assignee) params.set("assignee", filters.assignee);
  if (filters.due && withDue) params.set("due", "1");
  if (filters.channel) params.set("channel", filters.channel);
  if (filters.q) params.set("q", filters.q);
  return params.toString();
}

function apiQuery(filters: Filters) {
  return {
    status: filters.status,
    assignee: filters.assignee,
    channel: filters.channel,
    q: filters.q || undefined,
    due: filters.due || undefined,
  };
}

function Pill({
  active,
  count,
  attention,
  onClick,
  children,
}: {
  active: boolean;
  count?: number;
  attention?: boolean;
  onClick: () => void;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      aria-pressed={active}
      onClick={onClick}
      className={cn(
        "flex min-h-11 items-center gap-1.5 rounded-md px-3 text-sm sm:min-h-9",
        active ? "bg-ink text-paper" : attention ? "bg-sun-soft hover:bg-sun" : "hover:bg-haze",
      )}
    >
      {children}
      {count !== undefined && count > 0 && (
        <span className={cn("text-xs tnum", active ? "text-haze" : "text-steel")}>{count}</span>
      )}
    </button>
  );
}

function BulkBar({
  ids,
  team,
  onDone,
  onClear,
}: {
  ids: string[];
  team: Member[];
  onDone: (updated: number) => void;
  onClear: () => void;
}) {
  const [assignee, setAssignee] = useState("");
  const [status, setStatus] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);

  async function apply() {
    setBusy(true);
    setError(null);
    try {
      let updated = 0;
      for (let start = 0; start < ids.length; start += BULK_LIMIT) {
        const body: Schemas["BulkIn"] = { ids: ids.slice(start, start + BULK_LIMIT) };
        if (assignee) body.assignee_id = assignee === "none" ? null : assignee;
        if (status) body.status = status as LeadStatus;
        updated += (await unwrap(api.POST("/leads/bulk", { body }))).updated;
      }
      onDone(updated);
    } catch (failure) {
      setError(failure);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mb-3 flex flex-col gap-3 rounded-lg border border-ink bg-paper p-3 max-md:hidden">
      <div className="flex flex-wrap items-end gap-3">
        <p className="min-h-10 self-center text-sm font-semibold tnum">Выбрано: {ids.length}</p>
        <label className="flex w-52 flex-col gap-1 text-xs text-steel">
          Назначить
          <select
            value={assignee}
            onChange={(event) => setAssignee(event.target.value)}
            className={control}
          >
            <option value="">Не менять</option>
            <option value="none">Снять ответственного</option>
            {team.map((member) => (
              <option key={member.id} value={member.id}>
                {memberLabel(member)}
              </option>
            ))}
          </select>
        </label>
        <label className="flex w-44 flex-col gap-1 text-xs text-steel">
          Статус
          <select
            value={status}
            onChange={(event) => setStatus(event.target.value)}
            className={control}
          >
            <option value="">Не менять</option>
            {STATUSES.map((value) => (
              <option key={value} value={value}>
                {LEAD_STATUS[value]}
              </option>
            ))}
          </select>
        </label>
        <Button
          variant="dark"
          loading={busy}
          disabled={!assignee && !status}
          onClick={() => void apply()}
        >
          Изменить выбранные
        </Button>
        <Button variant="ghost" onClick={onClear}>
          Снять выделение
        </Button>
      </div>
      <FormError error={error} />
    </div>
  );
}

function LeadsList({
  data,
  filters,
  team,
  filtered,
}: {
  data: Schemas["LeadList"];
  filters: Filters;
  team: Member[];
  filtered: boolean;
}) {
  const { mutate } = useSWRConfig();
  const [more, setMore] = useState<LeadRow[]>([]);
  const [next, setNext] = useState<string | null | undefined>(undefined);
  const [loadingMore, setLoadingMore] = useState(false);
  const [loadError, setLoadError] = useState<unknown>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [changed, setChanged] = useState<number | null>(null);

  const cursor = next === undefined ? data.next_before : next;
  const seen = new Set(data.items.map((lead) => lead.id));
  const rows = [...data.items, ...more.filter((lead) => !seen.has(lead.id))];
  const ids = rows.filter((lead) => selected.has(lead.id)).map((lead) => lead.id);

  async function loadMore() {
    if (!cursor) return;
    setLoadingMore(true);
    setLoadError(null);
    try {
      const page = await unwrap(
        api.GET("/leads", { params: { query: { ...apiQuery(filters), before: cursor } } }),
      );
      setMore([...more, ...page.items]);
      setNext(page.next_before ?? null);
    } catch (failure) {
      setLoadError(failure);
    } finally {
      setLoadingMore(false);
    }
  }

  function toggle(id: string) {
    const copy = new Set(selected);
    if (!copy.delete(id)) copy.add(id);
    setSelected(copy);
    setChanged(null);
  }

  function toggleAll() {
    const all = rows.every((lead) => selected.has(lead.id));
    setSelected(all ? new Set() : new Set(rows.map((lead) => lead.id)));
    setChanged(null);
  }

  function bulkDone(updated: number) {
    setChanged(updated);
    setSelected(new Set());
    setMore([]);
    setNext(undefined);
    void mutate(
      (key) =>
        typeof key === "string" && (key.startsWith("/leads") || key.startsWith("/conversations")),
    );
  }

  if (rows.length === 0) {
    return (
      <Empty title={filtered ? "Таких заявок нет" : "Заявок пока нет"}>
        {filtered
          ? "Снимите часть фильтров или поищите по другому слову."
          : "Проверьте в песочнице, как бот принимает заказ, или подключите канал."}
      </Empty>
    );
  }

  return (
    <>
      {changed !== null && (
        <Notice kind="success" className="mb-3">
          Изменено: {changed}
        </Notice>
      )}
      {ids.length > 0 && (
        <BulkBar ids={ids} team={team} onDone={bulkDone} onClear={() => setSelected(new Set())} />
      )}
      <LeadTable
        rows={rows}
        team={team}
        selected={selected}
        onToggle={toggle}
        onToggleAll={toggleAll}
      />
      <LeadCards rows={rows} team={team} />
      <FormError error={loadError} />
      {cursor && (
        <Button
          variant="secondary"
          className="mt-4"
          loading={loadingMore}
          onClick={() => void loadMore()}
        >
          Показать ещё
        </Button>
      )}
    </>
  );
}

export function LeadsView() {
  const router = useRouter();
  const params = useSearchParams();
  const { isOwner } = useSession();
  const team = useTeam();
  const filters = readFilters(params);
  const query = toQuery(filters);
  const [input, setInput] = useState(filters.q);
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);

  useEffect(() => () => clearTimeout(timer.current), []);

  const { data, error, isLoading, mutate } = useSWR(
    `/leads?${query}`,
    () => unwrap(api.GET("/leads", { params: { query: apiQuery(filters) } })),
    { keepPreviousData: true },
  );
  const counts = data?.counts;
  const filtered = query !== "";
  const exportQuery = toQuery(filters, false);

  function go(next: Filters, replace = false) {
    const target = toQuery(next);
    const href = target ? `/leads?${target}` : "/leads";
    if (replace) router.replace(href);
    else router.push(href);
  }

  function search(value: string) {
    setInput(value);
    clearTimeout(timer.current);
    timer.current = setTimeout(() => go({ ...filters, q: value.trim() }, true), 300);
  }

  return (
    <Page className="max-w-[100rem]">
      <PageHeader
        title="Заявки"
        actions={
          isOwner && (
            <a
              href={`/api/leads/export${exportQuery ? `?${exportQuery}` : ""}`}
              download
              className={buttonVariants({ variant: "secondary" })}
            >
              <Download aria-hidden />
              Скачать CSV
            </a>
          )
        }
      >
        Бот оформляет заявку, когда покупатель готов купить. Дальше её ведёт менеджер: назначьте
        ответственного, поставьте напоминание и доведите до оплаты.
      </PageHeader>
      <div role="group" aria-label="Фильтр по статусу" className="-ml-1 flex flex-wrap gap-1">
        <Pill active={!filters.status} onClick={() => go({ ...filters, status: undefined })}>
          Все
        </Pill>
        {STATUSES.map((value) => (
          <Pill
            key={value}
            active={value === filters.status}
            count={counts?.[value]}
            onClick={() => go({ ...filters, status: value })}
          >
            {LEAD_STATUS[value]}
          </Pill>
        ))}
      </div>
      <div className="mt-2 mb-4 flex flex-wrap items-center gap-x-3 gap-y-2">
        <div role="group" aria-label="Фильтр по работе" className="-ml-1 flex flex-wrap gap-1">
          <Pill
            active={filters.assignee === "me"}
            count={counts?.mine}
            onClick={() =>
              go({ ...filters, assignee: filters.assignee === "me" ? undefined : "me" })
            }
          >
            Мои
          </Pill>
          <Pill
            active={filters.assignee === "none"}
            onClick={() =>
              go({ ...filters, assignee: filters.assignee === "none" ? undefined : "none" })
            }
          >
            Без ответственного
          </Pill>
          <Pill
            active={filters.due}
            count={counts?.overdue}
            attention={Boolean(counts?.overdue)}
            onClick={() => go({ ...filters, due: !filters.due })}
          >
            Пора напомнить
          </Pill>
        </div>
        <label className="w-40">
          <span className="sr-only">Канал</span>
          <select
            value={filters.channel ?? ""}
            onChange={(event) =>
              go({ ...filters, channel: (event.target.value || undefined) as Channel | undefined })
            }
            className={control}
          >
            <option value="">Все каналы</option>
            {CHANNELS.map((value) => (
              <option key={value} value={value}>
                {CHANNEL_NAMES[value]}
              </option>
            ))}
          </select>
        </label>
        <div className="relative min-w-56 flex-1 sm:max-w-xs">
          <Search
            className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-steel"
            aria-hidden
          />
          <label htmlFor="lead-search" className="sr-only">
            Поиск по заявкам
          </label>
          <input
            id="lead-search"
            type="search"
            value={input}
            maxLength={100}
            onChange={(event) => search(event.target.value)}
            placeholder="Имя, телефон или номер"
            className={cn(control, "pl-9")}
          />
        </div>
      </div>
      {isLoading && !data && <Loading />}
      {error ? <LoadError error={error} retry={() => void mutate()} /> : null}
      {data && (
        <LeadsList key={query} data={data} filters={filters} team={team} filtered={filtered} />
      )}
    </Page>
  );
}
