"use client";

import { useState } from "react";
import { useSWRConfig } from "swr";

import { useSession } from "@/components/shell/session";
import { Button } from "@/components/ui/button";
import { SelectField } from "@/components/ui/field";
import { Notice } from "@/components/ui/notice";
import { FormError } from "@/components/ui/page";
import { api } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";
import { useNiches } from "@/lib/niches";

import { PROFILE_KEY } from "./profile-form";

/** Готовые настройки бота под категорию магазина: тон, приветствие, что уточнять. */
export function NichePreset({ onApplied }: { onApplied: () => void }) {
  const { shop } = useSession();
  const { niches } = useNiches();
  const { mutate } = useSWRConfig();
  const [picked, setPicked] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [applied, setApplied] = useState<string | null>(null);

  if (!niches.length) return null;
  const key = picked ?? niches.find((item) => item.title === shop?.niche)?.key ?? "";
  const niche = niches.find((item) => item.key === key);
  const clarify = Array.isArray(niche?.rules.custom) ? (niche.rules.custom as string[]) : [];
  const handoff = typeof niche?.rules.handoff === "string" ? niche.rules.handoff : null;

  async function apply() {
    if (!niche) return;
    setBusy(true);
    setError(null);
    setApplied(null);
    try {
      const profile = await unwrap(api.POST("/bot-profile/preset", { body: { niche: niche.key } }));
      void mutate(PROFILE_KEY, profile, { revalidate: false });
      setApplied(niche.title);
      onApplied();
    } catch (failure) {
      setError(failure);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mb-6 flex flex-col gap-4 rounded-lg border border-line bg-mist p-4">
      <div>
        <h3 className="text-base">Заготовка по категории</h3>
        <p className="mt-1 text-sm text-steel">
          Заменит тон, приветствие и правила бота. Доставка, оплата и скидки останутся вашими.
          Вернуть прежние настройки можно в «Прошлых версиях».
        </p>
      </div>
      <SelectField
        label="Категория магазина"
        hint={niche?.hint}
        value={key}
        onChange={(event) => {
          setPicked(event.target.value);
          setApplied(null);
        }}
      >
        <option value="">Выберите</option>
        {niches.map((item) => (
          <option key={item.key} value={item.key}>
            {item.title}
          </option>
        ))}
      </SelectField>
      {niche && (
        <dl className="flex flex-col gap-2 text-sm">
          <div>
            <dt className="text-steel">Тон</dt>
            <dd>{niche.tone}</dd>
          </div>
          <div>
            <dt className="text-steel">Приветствие</dt>
            <dd>{niche.greeting}</dd>
          </div>
          {handoff && (
            <div>
              <dt className="text-steel">Когда звать менеджера</dt>
              <dd>{handoff}</dd>
            </div>
          )}
          {clarify.length > 0 && (
            <div>
              <dt className="text-steel">Правила бота</dt>
              <dd>
                <ul className="list-disc pl-5">
                  {clarify.map((line) => (
                    <li key={line}>{line}</li>
                  ))}
                </ul>
              </dd>
            </div>
          )}
        </dl>
      )}
      <FormError error={error} />
      {applied && (
        <Notice kind="success">Заготовка «{applied}» применена. Проверьте бота в песочнице.</Notice>
      )}
      <div>
        <Button variant="secondary" disabled={!niche} loading={busy} onClick={() => void apply()}>
          Применить заготовку
        </Button>
      </div>
    </div>
  );
}
