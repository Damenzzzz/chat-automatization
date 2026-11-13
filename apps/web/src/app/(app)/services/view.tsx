"use client";

import { ArrowUpRight } from "lucide-react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import useSWR from "swr";

import { BOT, ICONS, isKind, schedule, type Automation } from "@/components/services/catalog";
import { ServicePanel } from "@/components/services/service-panel";
import { useSession } from "@/components/shell/session";
import { LoadError, Loading, Page, PageHeader } from "@/components/ui/page";
import { api } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";
import { cn } from "@/lib/utils";

function State({ on, attention }: { on: boolean; attention?: string | null }) {
  return (
    <span className="flex items-center gap-1.5 text-xs text-steel">
      <span
        aria-hidden
        className={cn("size-2 rounded-full", attention ? "bg-sun" : on ? "bg-sky" : "bg-control")}
      />
      {attention ?? (on ? "Работает" : "Выключен")}
    </span>
  );
}

function BotRow() {
  const { shop } = useSession();
  const Icon = ICONS[BOT];
  return (
    <li>
      <Link
        href="/bot"
        className="flex min-h-16 items-center gap-3 rounded-lg px-3 py-2.5 transition-colors hover:bg-mist"
      >
        <Icon className="size-5 shrink-0 text-steel" aria-hidden />
        <span className="min-w-0 flex-1">
          <span className="block font-medium">Бот-консультант</span>
          {shop && <State on={!shop.bot_paused} attention={shop.bot_paused ? "На паузе" : null} />}
        </span>
        <ArrowUpRight className="size-4 shrink-0 text-steel" aria-hidden />
      </Link>
    </li>
  );
}

function ServiceRow({ item, active }: { item: Automation; active: boolean }) {
  const Icon = ICONS[item.kind];
  const waiting = item.pending > 0 ? `Ждут решения: ${item.pending}` : null;
  return (
    <li>
      <Link
        href={`/services?service=${item.kind}`}
        scroll={false}
        aria-current={active ? "page" : undefined}
        className={cn(
          "flex min-h-16 items-center gap-3 rounded-lg px-3 py-2.5 transition-colors",
          active ? "bg-sky-soft" : "hover:bg-mist",
        )}
      >
        <Icon className={cn("size-5 shrink-0", active ? "text-ink" : "text-steel")} aria-hidden />
        <span className="min-w-0 flex-1">
          <span className="block font-medium">{item.title}</span>
          <State on={item.enabled} attention={waiting} />
        </span>
      </Link>
    </li>
  );
}

export function ServicesView() {
  const params = useSearchParams();
  const { data, error, mutate } = useSWR("/automations", () => unwrap(api.GET("/automations")));
  const wanted = params.get("service");
  const selected = data?.find((item) => item.kind === wanted) ?? data?.[0];

  return (
    <Page>
      <PageHeader title="Сервисы">
        Автоматизации, которые работают рядом с ботом. Каждую можно включить, настроить и проверить
        до того, как она что-нибудь отправит.
      </PageHeader>
      {error && <LoadError error={error} retry={() => void mutate()} />}
      {!data && !error && <Loading />}
      {data && selected && (
        <div className="grid items-start gap-4 lg:grid-cols-[17rem_minmax(0,1fr)]">
          <nav aria-label="Сервисы" className="panel p-2 lg:sticky lg:top-6">
            <ul className="flex flex-col gap-0.5">
              <BotRow />
              {data.map((item) => (
                <ServiceRow key={item.kind} item={item} active={item.kind === selected.kind} />
              ))}
            </ul>
            <p className="px-3 pt-2 pb-1.5 text-xs text-steel">
              {isKind(wanted) || !wanted
                ? `«${selected.title}» срабатывает ${schedule(selected)}.`
                : "Такого сервиса нет — показываем первый."}
            </p>
          </nav>
          <div className="min-w-0">
            <ServicePanel key={selected.kind} item={selected} />
          </div>
        </div>
      )}
    </Page>
  );
}
