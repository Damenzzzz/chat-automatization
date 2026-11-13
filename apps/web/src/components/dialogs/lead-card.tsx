"use client";

import { useState } from "react";
import { useSWRConfig } from "swr";

import { SelectField } from "@/components/ui/field";
import { FormError } from "@/components/ui/page";
import { api, type Schemas } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";
import { fullDate, money } from "@/lib/format";

import { CANCEL_REASONS, LEAD_STATUS } from "./labels";

type LeadItem = { name?: string; sku?: string; qty?: number; quantity?: number; price?: number };

/** `managed = false` — только состав заказа: статус и остальное правят рядом, в таблице заявок. */
export function LeadCard({
  lead,
  managed = true,
}: {
  lead: Schemas["LeadOut"];
  managed?: boolean;
}) {
  const { mutate } = useSWRConfig();
  const [error, setError] = useState<unknown>(null);
  const [status, setStatus] = useState(lead.status);

  async function change(next: string) {
    const previous = status;
    setStatus(next);
    setError(null);
    try {
      await unwrap(
        api.PATCH("/leads/{lead_id}", {
          params: { path: { lead_id: lead.id } },
          body: { status: next as "new" | "in_progress" | "done" | "cancelled" },
        }),
      );
      void mutate(
        (key) =>
          typeof key === "string" && (key.startsWith("/leads") || key.startsWith("/conversations")),
      );
    } catch (failure) {
      setStatus(previous);
      setError(failure);
    }
  }

  const items = lead.items as LeadItem[];
  return (
    <article className="flex flex-col gap-3 text-sm">
      {items.length > 0 && (
        <ul className="flex flex-col gap-1">
          {items.map((item, index) => (
            <li key={index} className="flex justify-between gap-3">
              <span className="min-w-0 break-words">
                {item.name ?? item.sku ?? "Товар"}
                {(item.qty ?? item.quantity) ? ` × ${item.qty ?? item.quantity}` : ""}
              </span>
              {typeof item.price === "number" && (
                <span className="shrink-0 tnum">{money(item.price)}</span>
              )}
            </li>
          ))}
        </ul>
      )}
      {lead.total_kzt !== null && lead.total_kzt !== undefined && (
        <p className="display text-lg">{money(lead.total_kzt)}</p>
      )}
      <dl className="flex flex-col gap-1.5">
        {[
          ["Имя", lead.contact_name],
          ["Телефон", lead.contact_phone],
          ["Адрес", lead.address],
          ["Доставка", lead.delivery_at ? fullDate(lead.delivery_at) : lead.delivery_note],
          ["Комментарий", lead.comment],
          ...(managed
            ? [
                ["Ответственный", lead.assignee_name],
                ["Причина отказа", CANCEL_REASONS[lead.cancel_reason ?? ""]],
                ["Напомнить", lead.remind_at ? fullDate(lead.remind_at) : null],
                ["Заметка", lead.note],
              ]
            : []),
        ]
          .filter(([, value]) => value)
          .map(([label, value]) => (
            <div key={label as string}>
              <dt className="text-steel">{label}</dt>
              <dd className="break-words">
                {label === "Телефон" ? (
                  <a href={`tel:${value as string}`} className="underline underline-offset-2">
                    {value}
                  </a>
                ) : (
                  value
                )}
              </dd>
            </div>
          ))}
      </dl>
      {managed && (
        <SelectField
          label="Статус заявки"
          value={status}
          onChange={(event) => void change(event.target.value)}
        >
          {Object.entries(LEAD_STATUS).map(([value, label]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </SelectField>
      )}
      <FormError error={error} />
    </article>
  );
}
