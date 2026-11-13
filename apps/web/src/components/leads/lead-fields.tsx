"use client";

import { X } from "lucide-react";
import { useState, type ReactNode } from "react";

import { CANCEL_REASONS, LEAD_STATUS } from "@/components/dialogs/labels";
import { memberLabel, type Member } from "@/components/shop/team";
import { cn } from "@/lib/utils";

import {
  fromLocalInput,
  isOpen,
  isOverdue,
  toLocalInput,
  type LeadPatch,
  type LeadRow,
  type LeadStatus,
} from "./use-lead";

export const control =
  "min-h-11 w-full min-w-0 rounded-md border border-control/70 bg-paper px-2.5 text-base text-ink transition-colors hover:border-ink focus-visible:border-sky-deep disabled:bg-mist disabled:text-steel sm:min-h-10";

type FieldProps = {
  lead: LeadRow;
  save: (patch: LeadPatch) => Promise<void>;
  /** В таблице подпись уже есть в шапке колонки, в карточке её надо показать. */
  labelled?: boolean;
};

function Labelled({
  label,
  visible,
  children,
}: {
  label: string;
  visible?: boolean;
  children: ReactNode;
}) {
  return (
    <label className="flex min-w-0 flex-col gap-1.5">
      <span className={visible ? "text-sm font-medium" : "sr-only"}>{label}</span>
      {children}
    </label>
  );
}

export function StatusField({ lead, save, labelled }: FieldProps) {
  return (
    <div className="flex min-w-0 flex-col gap-1.5">
      <Labelled label="Статус заявки" visible={labelled}>
        <select
          value={lead.status}
          onChange={(event) => void save({ status: event.target.value as LeadStatus })}
          className={control}
        >
          {Object.entries(LEAD_STATUS).map(([value, label]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </select>
      </Labelled>
      {lead.status === "cancelled" && (
        <Labelled label="Причина отказа" visible={labelled}>
          <select
            value={lead.cancel_reason ?? ""}
            onChange={(event) =>
              void save({
                cancel_reason: (event.target.value || null) as LeadPatch["cancel_reason"],
              })
            }
            className={control}
          >
            <option value="">Причина отказа</option>
            {Object.entries(CANCEL_REASONS).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </Labelled>
      )}
    </div>
  );
}

export function AssigneeField({ lead, save, labelled, team }: FieldProps & { team: Member[] }) {
  const known = !lead.assignee_id || team.some((member) => member.id === lead.assignee_id);
  return (
    <Labelled label="Ответственный" visible={labelled}>
      <select
        value={lead.assignee_id ?? ""}
        onChange={(event) => void save({ assignee_id: event.target.value || null })}
        className={control}
      >
        <option value="">Не назначен</option>
        {!known && lead.assignee_id && (
          <option value={lead.assignee_id}>{lead.assignee_name ?? "Сотрудник"}</option>
        )}
        {team.map((member) => (
          <option key={member.id} value={member.id}>
            {memberLabel(member)}
          </option>
        ))}
      </select>
    </Labelled>
  );
}

export function RemindField({ lead, save, labelled }: FieldProps) {
  const initial = toLocalInput(lead.remind_at);
  const [value, setValue] = useState(initial);
  const open = isOpen(lead.status);
  const overdue = isOverdue(lead);

  function commit() {
    if (value === initial) return;
    void save({ remind_at: fromLocalInput(value) });
  }

  return (
    <div className="flex min-w-0 flex-col gap-1">
      <Labelled label="Напомнить" visible={labelled}>
        <span className="flex min-w-0 items-center gap-1">
          <input
            type="datetime-local"
            value={value}
            disabled={!open}
            onChange={(event) => setValue(event.target.value)}
            onBlur={commit}
            onKeyDown={(event) => {
              if (event.key === "Enter") commit();
            }}
            className={cn(control, overdue && "border-ink bg-sun-soft")}
          />
          {lead.remind_at && open && (
            <button
              type="button"
              aria-label="Убрать напоминание"
              onClick={() => {
                setValue("");
                void save({ remind_at: null });
              }}
              className="flex size-11 shrink-0 items-center justify-center rounded-md hover:bg-haze sm:size-10"
            >
              <X className="size-4" aria-hidden />
            </button>
          )}
        </span>
      </Labelled>
      {overdue && <p className="text-xs font-semibold">Пора напомнить</p>}
      {!open && labelled && (
        <p className="text-xs text-steel">Напоминание ставится только на открытую заявку.</p>
      )}
    </div>
  );
}

export function NoteField({ lead, save, labelled }: FieldProps) {
  const [value, setValue] = useState(lead.note ?? "");
  return (
    <Labelled label="Заметка" visible={labelled}>
      <textarea
        rows={labelled ? 2 : 1}
        maxLength={2000}
        value={value}
        onChange={(event) => setValue(event.target.value)}
        onBlur={() => {
          if (value.trim() !== (lead.note ?? "")) void save({ note: value });
        }}
        placeholder="Для команды"
        className={cn(control, "resize-y py-2 leading-normal")}
      />
    </Labelled>
  );
}
