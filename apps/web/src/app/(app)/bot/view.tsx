"use client";

import { useState } from "react";
import useSWR, { useSWRConfig } from "swr";

import { PROFILE_KEY, ProfileForm } from "@/components/bot/profile-form";
import { Autotest, SandboxChat } from "@/components/bot/sandbox";
import { Button } from "@/components/ui/button";
import { FormError, Page, PageHeader, Section } from "@/components/ui/page";
import { api } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";
import { fullDate } from "@/lib/format";

function Versions() {
  const { mutate: mutateGlobal } = useSWRConfig();
  const { data, mutate } = useSWR("/bot-profile/versions", () =>
    unwrap(api.GET("/bot-profile/versions")),
  );
  const [busy, setBusy] = useState<number | null>(null);
  const [error, setError] = useState<unknown>(null);

  async function rollback(version: number) {
    setBusy(version);
    setError(null);
    try {
      await unwrap(api.POST("/bot-profile/rollback", { body: { version } }));
      void mutate();
      void mutateGlobal(PROFILE_KEY);
    } catch (failure) {
      setError(failure);
    } finally {
      setBusy(null);
    }
  }

  if (!data?.length)
    return <p className="text-sm text-steel">Версии появятся после первого сохранения.</p>;
  return (
    <>
      <FormError error={error} />
      <ul className="divide-y divide-line">
        {data.slice(0, 10).map((item) => (
          <li
            key={item.version}
            className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1 py-2.5 text-sm"
          >
            <span>
              <span className="font-medium tnum">Версия {item.version}</span>
              <span className="text-steel">, {fullDate(item.created_at)}</span>
            </span>
            {item.is_active ? (
              <span className="text-steel">Сейчас работает</span>
            ) : (
              <Button
                variant="ghost"
                loading={busy === item.version}
                onClick={() => void rollback(item.version)}
              >
                Вернуть эту версию
              </Button>
            )}
          </li>
        ))}
      </ul>
    </>
  );
}

export function BotView() {
  const { mutate } = useSWRConfig();
  return (
    <Page className="max-w-6xl">
      <PageHeader title="Бот и песочница">
        Настройте, как бот говорит, и сразу проверьте его как покупатель.
      </PageHeader>
      <div className="grid gap-x-10 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
        <Section title="Характер">
          <ProfileForm onSaved={() => void mutate("/bot-profile/versions")} />
        </Section>
        <div className="min-w-0">
          <Section title="Песочница">
            <SandboxChat />
          </Section>
          <Section
            title="Автопроверка"
            description="Мы зададим боту вопросы по вашему каталогу и проверим ответы."
          >
            <Autotest />
          </Section>
          <Section title="Прошлые версии">
            <Versions />
          </Section>
        </div>
      </div>
    </Page>
  );
}
