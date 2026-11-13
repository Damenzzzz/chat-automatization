"use client";

import { ChevronDown } from "lucide-react";
import Link from "next/link";
import { Fragment, useState } from "react";

import { CHANNEL_NAMES } from "@/components/dialogs/labels";
import { LeadCard } from "@/components/dialogs/lead-card";
import type { Member } from "@/components/shop/team";
import { Chip } from "@/components/ui/chip";
import { FormError } from "@/components/ui/page";
import { fullDate, money } from "@/lib/format";
import { cn } from "@/lib/utils";

import { AssigneeField, NoteField, RemindField, StatusField } from "./lead-fields";
import { isOverdue, useLeadEdit, type LeadRow } from "./use-lead";

const COLUMNS = 10;

function Customer({ lead }: { lead: LeadRow }) {
  return (
    <div className="flex min-w-0 flex-col gap-1">
      <span className="font-medium break-words">{lead.contact_name || "Без имени"}</span>
      {lead.contact_phone && (
        <a href={`tel:${lead.contact_phone}`} className="tnum underline underline-offset-2">
          {lead.contact_phone}
        </a>
      )}
      {lead.tags.length > 0 && (
        <span className="flex flex-wrap gap-1">
          {lead.tags.map((tag) => (
            <Chip key={tag} className="max-w-36">
              {tag}
            </Chip>
          ))}
        </span>
      )}
    </div>
  );
}

function Row({
  source,
  team,
  checked,
  onToggle,
  open,
  onOpen,
}: {
  source: LeadRow;
  team: Member[];
  checked: boolean;
  onToggle: (id: string) => void;
  open: boolean;
  onOpen: (id: string) => void;
}) {
  const { lead, error, save } = useLeadEdit(source);
  const details = `lead-details-${lead.id}`;
  return (
    <Fragment>
      <tr className={cn("border-b border-line align-top", isOverdue(lead) && "bg-sun-soft/40")}>
        <td className="py-3 pr-2 pl-4">
          <input
            type="checkbox"
            checked={checked}
            onChange={() => onToggle(lead.id)}
            aria-label={`Выбрать заявку ${lead.number}`}
            className="mt-3 size-5 accent-ink"
          />
        </td>
        <td className="py-3 pr-3">
          <button
            type="button"
            aria-expanded={open}
            aria-controls={details}
            onClick={() => onOpen(lead.id)}
            className="flex min-h-10 items-center gap-1 rounded-md px-1.5 font-medium tnum hover:bg-haze"
          >
            <span className="sr-only">Состав заявки </span>
            {lead.number}
            <ChevronDown
              className={cn("size-4 transition-transform", open && "rotate-180")}
              aria-hidden
            />
          </button>
        </td>
        <td className="py-3 pt-5 pr-3 whitespace-nowrap text-steel">{fullDate(lead.created_at)}</td>
        <td className="max-w-56 py-3 pt-5 pr-3">
          <Customer lead={lead} />
        </td>
        <td className="py-3 pt-5 pr-3 whitespace-nowrap">
          {lead.channel ? (CHANNEL_NAMES[lead.channel] ?? lead.channel) : ""}
        </td>
        <td className="py-3 pt-5 pr-3 text-right whitespace-nowrap tnum">
          {lead.total_kzt === null ? "" : money(lead.total_kzt)}
        </td>
        <td className="min-w-48 py-3 pr-3">
          <StatusField lead={lead} save={save} />
        </td>
        <td className="min-w-48 py-3 pr-3">
          <AssigneeField lead={lead} save={save} team={team} />
        </td>
        <td className="min-w-60 py-3 pr-3">
          <RemindField key={lead.remind_at ?? "none"} lead={lead} save={save} />
        </td>
        <td className="min-w-56 py-3 pr-4">
          <NoteField key={lead.note ?? ""} lead={lead} save={save} />
        </td>
      </tr>
      {error ? (
        <tr className="border-b border-line">
          <td colSpan={COLUMNS} className="px-4 py-2">
            <FormError error={error} />
          </td>
        </tr>
      ) : null}
      {open && (
        <tr id={details} className="border-b border-line bg-mist">
          <td colSpan={COLUMNS} className="px-4 py-4">
            <div className="flex max-w-xl flex-col gap-3">
              <LeadCard lead={lead} managed={false} />
              {lead.conversation_id && (
                <Link
                  href={`/dialogs?id=${lead.conversation_id}`}
                  className="inline-flex min-h-10 items-center self-start text-sm font-medium underline underline-offset-2"
                >
                  Открыть диалог
                </Link>
              )}
            </div>
          </td>
        </tr>
      )}
    </Fragment>
  );
}

export function LeadTable({
  rows,
  team,
  selected,
  onToggle,
  onToggleAll,
}: {
  rows: LeadRow[];
  team: Member[];
  selected: Set<string>;
  onToggle: (id: string) => void;
  onToggleAll: () => void;
}) {
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const all = rows.length > 0 && rows.every((lead) => selected.has(lead.id));

  function toggleDetails(id: string) {
    const next = new Set(expanded);
    if (!next.delete(id)) next.add(id);
    setExpanded(next);
  }
  const heading = "py-2.5 pr-3 font-normal";
  return (
    <div className="overflow-x-auto panel max-md:hidden">
      <table className="w-full min-w-[84rem] text-sm">
        <caption className="sr-only">Заявки</caption>
        <thead className="text-left text-steel">
          <tr className="border-b border-line">
            <th scope="col" className="py-2.5 pr-2 pl-4 font-normal">
              <input
                type="checkbox"
                checked={all}
                onChange={onToggleAll}
                aria-label="Выбрать все заявки на странице"
                className="size-5 align-middle accent-ink"
              />
            </th>
            <th scope="col" className={heading}>
              №
            </th>
            <th scope="col" className={heading}>
              Создана
            </th>
            <th scope="col" className={heading}>
              Покупатель
            </th>
            <th scope="col" className={heading}>
              Канал
            </th>
            <th scope="col" className={cn(heading, "text-right")}>
              Сумма
            </th>
            <th scope="col" className={heading}>
              Статус
            </th>
            <th scope="col" className={heading}>
              Ответственный
            </th>
            <th scope="col" className={heading}>
              Напомнить
            </th>
            <th scope="col" className="py-2.5 pr-4 font-normal">
              Заметка
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.map((lead) => (
            <Row
              key={lead.id}
              source={lead}
              team={team}
              checked={selected.has(lead.id)}
              onToggle={onToggle}
              open={expanded.has(lead.id)}
              onOpen={toggleDetails}
            />
          ))}
        </tbody>
      </table>
    </div>
  );
}
