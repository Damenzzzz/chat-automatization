"use client";

import { useState } from "react";

import { FormError } from "@/components/ui/page";
import { api, type Schemas } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";
import { money, plural, shortDay } from "@/lib/format";

import { CHANNEL_NAMES, LEAD_STATUS } from "./labels";

const LANGS: Record<string, string> = {
  ru: "на русском",
  kk: "на казахском",
  mixed: "на русском и казахском",
};

export function CustomerCard({
  conversationId,
  customer,
  onSaved,
}: {
  conversationId: string;
  customer: Schemas["CustomerOut"];
  onSaved: () => void;
}) {
  const [note, setNote] = useState(customer.note ?? "");
  const [state, setState] = useState<"idle" | "saving" | "saved">("idle");
  const [error, setError] = useState<unknown>(null);
  const name = customer.name || customer.phone || "Покупатель";
  const lang = customer.lang ? LANGS[customer.lang] : null;

  async function save() {
    if (note.trim() === (customer.note ?? "")) return;
    setState("saving");
    setError(null);
    try {
      await unwrap(
        api.PATCH("/conversations/{conversation_id}/customer", {
          params: { path: { conversation_id: conversationId } },
          body: { note },
        }),
      );
      setState("saved");
      onSaved();
    } catch (failure) {
      setError(failure);
      setState("idle");
    }
  }

  return (
    <div className="flex flex-col gap-4 text-sm">
      <div className="flex items-center gap-3">
        <span
          aria-hidden
          className="display flex size-11 shrink-0 items-center justify-center rounded-full bg-sun text-lg"
        >
          {name
            .replace(/[^\p{L}\p{N}]/gu, "")
            .charAt(0)
            .toUpperCase() || "П"}
        </span>
        <div className="min-w-0">
          <p className="truncate font-semibold">{name}</p>
          {customer.phone && (
            <a href={`tel:${customer.phone}`} className="tnum underline underline-offset-2">
              {customer.phone}
            </a>
          )}
        </div>
      </div>
      <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-3 gap-y-1.5">
        <dt className="text-steel">Пишет</dt>
        <dd>
          {[CHANNEL_NAMES[customer.channel] ?? customer.channel, lang].filter(Boolean).join(", ")}
        </dd>
        <dt className="text-steel">С нами</dt>
        <dd>
          с {shortDay(customer.first_seen_at)}, {customer.dialogs}{" "}
          {plural(customer.dialogs, "диалог", "диалога", "диалогов")}
        </dd>
      </dl>
      {customer.leads.length > 0 && (
        <div>
          <p className="mb-1.5 text-steel">Заявки покупателя</p>
          <ul className="flex flex-col gap-1">
            {customer.leads.map((lead) => (
              <li key={lead.id} className="flex items-baseline justify-between gap-3">
                <span className="tnum">{money(lead.total_kzt)}</span>
                <span className="text-xs text-steel">
                  {LEAD_STATUS[lead.status]?.toLowerCase()}, {shortDay(lead.created_at)}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}
      <div>
        <label htmlFor={`note-${customer.id}`} className="mb-1.5 block text-steel">
          Заметка для команды
        </label>
        <textarea
          id={`note-${customer.id}`}
          rows={3}
          maxLength={2000}
          value={note}
          onChange={(event) => {
            setNote(event.target.value);
            setState("idle");
          }}
          onBlur={() => void save()}
          placeholder="Например: постоянный клиент, заказывает оптом"
          className="w-full resize-none rounded-md border border-control bg-paper px-3 py-2 hover:border-ink"
        />
        <p role="status" className="mt-1 min-h-4 text-xs text-steel">
          {state === "saving" ? "Сохраняем" : state === "saved" ? "Сохранено" : ""}
        </p>
        <FormError error={error} />
      </div>
    </div>
  );
}
