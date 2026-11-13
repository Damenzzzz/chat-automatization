"use client";

import Link from "next/link";

import { CHANNEL_NAMES } from "@/components/dialogs/labels";
import { LeadCard } from "@/components/dialogs/lead-card";
import type { Member } from "@/components/shop/team";
import { Chip } from "@/components/ui/chip";
import { FormError } from "@/components/ui/page";
import { fullDate } from "@/lib/format";
import { cn } from "@/lib/utils";

import { AssigneeField, NoteField, RemindField, StatusField } from "./lead-fields";
import { isOverdue, useLeadEdit, type LeadRow } from "./use-lead";

function Card({ source, team }: { source: LeadRow; team: Member[] }) {
  const { lead, error, save } = useLeadEdit(source);
  return (
    <li className={cn("panel p-5", isOverdue(lead) && "border-ink")}>
      <div className="mb-3 flex flex-wrap items-baseline justify-between gap-x-3 text-xs text-steel">
        <span>
          <span className="font-medium text-ink tnum">№ {lead.number}</span>,{" "}
          {fullDate(lead.created_at)}
          {lead.channel ? `, ${CHANNEL_NAMES[lead.channel] ?? lead.channel}` : ""}
        </span>
        {lead.conversation_id && (
          <Link
            href={`/dialogs?id=${lead.conversation_id}`}
            className="inline-flex min-h-11 items-center font-medium text-ink underline underline-offset-2"
          >
            Открыть диалог
          </Link>
        )}
      </div>
      <LeadCard lead={lead} managed={false} />
      {lead.tags.length > 0 && (
        <p className="mt-3 flex flex-wrap gap-1">
          {lead.tags.map((tag) => (
            <Chip key={tag}>{tag}</Chip>
          ))}
        </p>
      )}
      <div className="mt-4 flex flex-col gap-4 border-t border-line pt-4">
        <StatusField lead={lead} save={save} labelled />
        <AssigneeField lead={lead} save={save} team={team} labelled />
        <RemindField key={lead.remind_at ?? "none"} lead={lead} save={save} labelled />
        <NoteField key={lead.note ?? ""} lead={lead} save={save} labelled />
        <FormError error={error} />
      </div>
    </li>
  );
}

/** Заявки на телефоне: те же поля, что в таблице, но одна под другой. */
export function LeadCards({ rows, team }: { rows: LeadRow[]; team: Member[] }) {
  return (
    <ul className="flex flex-col gap-4 md:hidden">
      {rows.map((lead) => (
        <Card key={lead.id} source={lead} team={team} />
      ))}
    </ul>
  );
}
