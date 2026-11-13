import {
  BellRing,
  Bot,
  MessageCircleReply,
  PackageSearch,
  Sunrise,
  type LucideIcon,
} from "lucide-react";

import type { Schemas } from "@/lib/api/client";

export type Automation = Schemas["AutomationOut"];
export type Kind = Automation["kind"];
export type Run = Schemas["RunOut"];
export type Preview = Schemas["Preview"];

export type DigestSettings = Required<Schemas["DigestSettings"]>;
export type StockSettings = Required<Schemas["StockSettings"]>;
export type FollowupSettings = Required<Schemas["FollowupSettings"]>;
export type LeadReminderSettings = Required<Schemas["LeadReminderSettings"]>;
export type AnySettings = DigestSettings | StockSettings | FollowupSettings | LeadReminderSettings;

export const BOT = "bot";

export const ICONS: Record<Kind | typeof BOT, LucideIcon> = {
  bot: Bot,
  digest: Sunrise,
  stock: PackageSearch,
  followup: MessageCircleReply,
  lead_reminders: BellRing,
};

export const KINDS: Kind[] = ["digest", "stock", "followup", "lead_reminders"];

export function isKind(value: string | null): value is Kind {
  return KINDS.includes(value as Kind);
}

export const hours = Array.from({ length: 24 }, (_, hour) => hour);

export function hourLabel(hour: number): string {
  return `${String(hour).padStart(2, "0")}:00`;
}

/** Когда сервис срабатывает — одной строкой, из его настроек. */
export function schedule(item: Automation): string {
  switch (item.kind) {
    case "digest": {
      const settings = item.settings as DigestSettings;
      const days = settings.weekdays.length === 7 ? "каждый день" : "по выбранным дням";
      return `${days} в ${hourLabel(settings.hour)}`;
    }
    case "stock":
      return `раз в час, остаток не больше ${(item.settings as StockSettings).threshold}`;
    case "followup": {
      const settings = item.settings as FollowupSettings;
      const mode = settings.mode === "auto" ? "отправляет сам" : "ждёт вашего одобрения";
      return `через ${settings.delay_hours} ч молчания, ${mode}`;
    }
    case "lead_reminders":
      return `через ${(item.settings as LeadReminderSettings).hours} ч без ответа и по сроку заявки`;
  }
}
