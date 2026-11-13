import type { ReactNode } from "react";

import { SelectField, TextArea, TextField } from "@/components/ui/field";
import { cn } from "@/lib/utils";

import {
  hourLabel,
  hours,
  type AnySettings,
  type DigestSettings,
  type FollowupSettings,
  type Kind,
  type LeadReminderSettings,
  type StockSettings,
} from "./catalog";

type FormProps<T> = { value: T; onChange: (next: T) => void; disabled: boolean };

const WEEKDAYS = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"];
const SECTIONS: [DigestSettings["sections"][number], string][] = [
  ["dialogs", "Диалоги за вчера"],
  ["leads", "Заявки и их сумма"],
  ["money", "Расход на ответы бота"],
  ["waiting", "Что ждёт вас сейчас"],
  ["unanswered", "Вопросы, на которые бот не ответил"],
  ["stock", "Товары на исходе"],
];
const CHANNELS: [FollowupSettings["channels"][number], string][] = [
  ["telegram", "Telegram"],
  ["whatsapp", "WhatsApp"],
  ["web", "Чат на сайте"],
];

function toggled<T>(list: T[], item: T): T[] {
  return list.includes(item) ? list.filter((other) => other !== item) : [...list, item];
}

function clamp(raw: string, min: number, max: number): number {
  const value = Math.round(Number(raw));
  return Number.isFinite(value) ? Math.min(max, Math.max(min, value)) : min;
}

function Group({ legend, hint, children }: { legend: string; hint?: string; children: ReactNode }) {
  return (
    <fieldset className="min-w-0">
      <legend className="text-sm font-medium text-ink">{legend}</legend>
      <div className="mt-1.5 flex flex-wrap gap-x-5 gap-y-1">{children}</div>
      {hint && <p className="mt-1.5 text-xs text-steel">{hint}</p>}
    </fieldset>
  );
}

function Check({
  checked,
  onChange,
  disabled,
  children,
  type = "checkbox",
  name,
}: {
  checked: boolean;
  onChange: () => void;
  disabled: boolean;
  children: ReactNode;
  type?: "checkbox" | "radio";
  name?: string;
}) {
  return (
    <label className="flex min-h-11 items-center gap-2.5 text-base">
      <input
        type={type}
        name={name}
        checked={checked}
        disabled={disabled}
        onChange={onChange}
        className="size-5 accent-ink"
      />
      {children}
    </label>
  );
}

function Recipients({ value, onChange, disabled }: FormProps<"owner" | "team">) {
  return (
    <SelectField
      label="Кому писать в Telegram"
      value={value}
      disabled={disabled}
      onChange={(event) => onChange(event.target.value as "owner" | "team")}
      hint="Telegram привязывается в настройках, в разделе уведомлений."
    >
      <option value="owner">Только владельцу</option>
      <option value="team">Владельцу и менеджерам</option>
    </SelectField>
  );
}

function HourSelect({
  label,
  value,
  onChange,
  disabled,
  hint,
}: FormProps<number> & { label: string; hint?: string }) {
  return (
    <SelectField
      label={label}
      hint={hint}
      value={value}
      disabled={disabled}
      onChange={(event) => onChange(Number(event.target.value))}
    >
      {hours.map((hour) => (
        <option key={hour} value={hour}>
          {hourLabel(hour)}
        </option>
      ))}
    </SelectField>
  );
}

function DigestForm({ value, onChange, disabled }: FormProps<DigestSettings>) {
  return (
    <>
      <div className="grid gap-4 sm:grid-cols-2">
        <HourSelect
          label="Во сколько присылать"
          value={value.hour}
          disabled={disabled}
          onChange={(hour) => onChange({ ...value, hour })}
          hint="По времени Алматы."
        />
        <Recipients
          value={value.recipients}
          disabled={disabled}
          onChange={(recipients) => onChange({ ...value, recipients })}
        />
      </div>
      <fieldset>
        <legend className="text-sm font-medium text-ink">По каким дням</legend>
        <div className="mt-1.5 flex flex-wrap gap-1.5">
          {WEEKDAYS.map((day, index) => {
            const on = value.weekdays.includes(index);
            return (
              <button
                key={day}
                type="button"
                aria-pressed={on}
                disabled={disabled || (on && value.weekdays.length === 1)}
                onClick={() =>
                  onChange({ ...value, weekdays: toggled(value.weekdays, index).sort() })
                }
                className={cn(
                  "min-h-11 min-w-11 rounded-md px-3 text-sm font-medium transition-colors disabled:cursor-not-allowed",
                  on ? "bg-ink text-paper" : "bg-mist text-ink hover:bg-haze",
                )}
              >
                {day}
              </button>
            );
          })}
        </div>
      </fieldset>
      <Group legend="Что входит в сводку">
        {SECTIONS.map(([key, label]) => {
          const on = value.sections.includes(key);
          return (
            <Check
              key={key}
              checked={on}
              disabled={disabled || (on && value.sections.length === 1)}
              onChange={() => onChange({ ...value, sections: toggled(value.sections, key) })}
            >
              {label}
            </Check>
          );
        })}
      </Group>
    </>
  );
}

function StockForm({ value, onChange, disabled }: FormProps<StockSettings>) {
  return (
    <>
      <div className="grid gap-4 sm:grid-cols-2">
        <TextField
          label="Сообщать, когда осталось"
          type="number"
          inputMode="numeric"
          min={0}
          max={1000}
          value={value.threshold}
          disabled={disabled}
          onChange={(event) =>
            onChange({ ...value, threshold: clamp(event.target.value, 0, 1000) })
          }
          hint="Штук или меньше. О каждом товаре пишем один раз, пока остаток не пополнят."
        />
        <Recipients
          value={value.recipients}
          disabled={disabled}
          onChange={(recipients) => onChange({ ...value, recipients })}
        />
      </div>
      <TextField
        label="Только эти категории"
        value={value.categories.join(", ")}
        disabled={disabled}
        onChange={(event) =>
          onChange({
            ...value,
            categories: event.target.value.split(",").map((name) => name.trimStart()),
          })
        }
        hint="Через запятую, как в каталоге. Пусто — следим за всеми товарами."
      />
      <Check
        checked={value.include_out_of_stock}
        disabled={disabled}
        onChange={() => onChange({ ...value, include_out_of_stock: !value.include_out_of_stock })}
      >
        Сообщать и о товарах, которые уже закончились
      </Check>
    </>
  );
}

function FollowupForm({ value, onChange, disabled }: FormProps<FollowupSettings>) {
  return (
    <>
      <Group legend="Кто отправляет">
        <Check
          type="radio"
          name="followup-mode"
          checked={value.mode === "approve"}
          disabled={disabled}
          onChange={() => onChange({ ...value, mode: "approve" })}
        >
          Сначала показать мне
        </Check>
        <Check
          type="radio"
          name="followup-mode"
          checked={value.mode === "auto"}
          disabled={disabled}
          onChange={() => onChange({ ...value, mode: "auto" })}
        >
          Отправлять сразу, без одобрения
        </Check>
      </Group>
      <TextArea
        label="Текст сообщения"
        rows={3}
        maxLength={500}
        value={value.text}
        disabled={disabled}
        onChange={(event) => onChange({ ...value, text: event.target.value })}
        hint={`${value.text.length} из 500. Перед отправкой текст можно поправить для каждого покупателя.`}
      />
      <div className="grid gap-4 sm:grid-cols-3">
        <TextField
          label="Написать через"
          type="number"
          inputMode="numeric"
          min={1}
          max={20}
          value={value.delay_hours}
          disabled={disabled}
          onChange={(event) =>
            onChange({ ...value, delay_hours: clamp(event.target.value, 1, 20) })
          }
          hint="Часов молчания покупателя."
        />
        <HourSelect
          label="Не писать с"
          value={value.quiet_from}
          disabled={disabled}
          onChange={(quiet_from) => onChange({ ...value, quiet_from })}
        />
        <HourSelect
          label="Не писать до"
          value={value.quiet_to}
          disabled={disabled}
          onChange={(quiet_to) => onChange({ ...value, quiet_to })}
          hint="Одинаковое время — писать круглые сутки."
        />
      </div>
      <Group
        legend="В каких каналах"
        hint="Пишем только тем, кто спрашивал про товар, не оставил заявку и молчит меньше суток: позже WhatsApp не разрешает писать первым. Одному покупателю — не чаще раза в неделю."
      >
        {CHANNELS.map(([key, label]) => {
          const on = value.channels.includes(key);
          return (
            <Check
              key={key}
              checked={on}
              disabled={disabled || (on && value.channels.length === 1)}
              onChange={() => onChange({ ...value, channels: toggled(value.channels, key) })}
            >
              {label}
            </Check>
          );
        })}
      </Group>
    </>
  );
}

function LeadRemindersForm({ value, onChange, disabled }: FormProps<LeadReminderSettings>) {
  return (
    <>
      <div className="grid gap-4 sm:grid-cols-2">
        <TextField
          label="Напомнить о новой заявке через"
          type="number"
          inputMode="numeric"
          min={1}
          max={48}
          value={value.hours}
          disabled={disabled}
          onChange={(event) => onChange({ ...value, hours: clamp(event.target.value, 1, 48) })}
          hint="Часов, если заявку никто не взял в работу."
        />
        <Recipients
          value={value.recipients}
          disabled={disabled}
          onChange={(recipients) => onChange({ ...value, recipients })}
        />
      </div>
      <p className="text-sm text-steel">
        Срок по отдельной заявке ставится на странице «Заявки», в колонке «Напомнить».
      </p>
    </>
  );
}

export function SettingsForm({
  kind,
  value,
  onChange,
  disabled,
}: FormProps<AnySettings> & { kind: Kind }) {
  const change = onChange as (next: unknown) => void;
  return (
    <div className="flex flex-col gap-4">
      {kind === "digest" && (
        <DigestForm value={value as DigestSettings} onChange={change} disabled={disabled} />
      )}
      {kind === "stock" && (
        <StockForm value={value as StockSettings} onChange={change} disabled={disabled} />
      )}
      {kind === "followup" && (
        <FollowupForm value={value as FollowupSettings} onChange={change} disabled={disabled} />
      )}
      {kind === "lead_reminders" && (
        <LeadRemindersForm
          value={value as LeadReminderSettings}
          onChange={change}
          disabled={disabled}
        />
      )}
    </div>
  );
}
