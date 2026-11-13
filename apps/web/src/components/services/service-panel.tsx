"use client";

import Link from "next/link";
import { useState } from "react";
import { useSWRConfig } from "swr";

import { Button } from "@/components/ui/button";
import { Notice } from "@/components/ui/notice";
import { FormError, Section } from "@/components/ui/page";
import { useSession } from "@/components/shell/session";
import { api } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";
import { whenShort } from "@/lib/format";

import { ICONS, schedule, type AnySettings, type Automation, type Preview } from "./catalog";
import { FOLLOWUPS_KEY, FollowupQueue } from "./followup-queue";
import { RunHistory, runsKey } from "./run-history";
import { SettingsForm } from "./settings-forms";
import { Toggle } from "./toggle";

function PreviewBox({ preview }: { preview: Preview }) {
  return (
    <div className="mt-4 rounded-lg border border-line bg-mist p-4" aria-live="polite">
      <p className="text-sm font-medium">{preview.summary}</p>
      {preview.text && (
        <p className="mt-3 max-w-xl rounded-lg rounded-tl-sm bg-paper p-3 text-sm whitespace-pre-wrap">
          {preview.text}
        </p>
      )}
      {preview.items && preview.items.length > 0 && (
        <ul className="mt-3 divide-y divide-line text-sm">
          {preview.items.map((item, index) => (
            <li key={index} className="flex flex-wrap justify-between gap-x-4 py-1.5">
              {item.href ? (
                <Link href={item.href} className="text-sky-deep underline underline-offset-4">
                  {item.title}
                </Link>
              ) : (
                <span>{item.title}</span>
              )}
              {item.detail && <span className="text-steel tnum">{item.detail}</span>}
            </li>
          ))}
        </ul>
      )}
      <p className="mt-3 text-xs text-steel">
        Это проверка: никому ничего не отправлено и в истории она не отмечена.
      </p>
    </div>
  );
}

export function ServicePanel({ item }: { item: Automation }) {
  const { isOwner } = useSession();
  const { mutate } = useSWRConfig();
  const saved = item.settings as AnySettings;
  const [draft, setDraft] = useState<AnySettings>(saved);
  const [busy, setBusy] = useState<"save" | "toggle" | "preview" | "run" | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [done, setDone] = useState<string | null>(null);
  const Icon = ICONS[item.kind];
  const path = { params: { path: { kind: item.kind } } };
  const dirty = JSON.stringify(draft) !== JSON.stringify(saved);

  async function act(action: NonNullable<typeof busy>, work: () => Promise<void>) {
    setBusy(action);
    setError(null);
    setDone(null);
    try {
      await work();
    } catch (failure) {
      setError(failure);
    } finally {
      setBusy(null);
    }
  }

  function refresh() {
    return mutate(
      (key) => key === "/automations" || key === runsKey(item.kind) || key === FOLLOWUPS_KEY,
    );
  }

  const save = () =>
    act("save", async () => {
      const next = await unwrap(
        api.PUT("/automations/{kind}", { ...path, body: { settings: draft } }),
      );
      setDraft(next.settings as AnySettings);
      await refresh();
      setDone("Настройки сохранены.");
    });

  const toggle = (enabled: boolean) =>
    act("toggle", async () => {
      await unwrap(api.PUT("/automations/{kind}", { ...path, body: { enabled } }));
      await refresh();
    });

  const check = () =>
    act("preview", async () => {
      setPreview(
        await unwrap(
          api.POST("/automations/{kind}/preview", { ...path, body: { settings: draft } }),
        ),
      );
    });

  const run = () =>
    act("run", async () => {
      const result = await unwrap(api.POST("/automations/{kind}/run", path));
      await refresh();
      setDone(result.summary);
    });

  return (
    <>
      <Section
        title={item.title}
        description={item.description}
        actions={
          <Toggle
            checked={item.enabled}
            disabled={!isOwner || busy !== null}
            label={`${item.title}: включить или выключить`}
            onChange={(next) => void toggle(next)}
          />
        }
      >
        <p className="mb-5 flex items-center gap-2 text-sm text-steel">
          <Icon className="size-4 shrink-0" aria-hidden />
          <span>
            Срабатывает {schedule(item)}.
            {item.last_run_at ? ` Последняя проверка ${whenShort(item.last_run_at)}.` : ""}
          </span>
        </p>
        <SettingsForm
          kind={item.kind}
          value={draft}
          onChange={(next) => {
            setDraft(next);
            setPreview(null);
          }}
          disabled={!isOwner || busy === "save"}
        />
        {!isOwner && (
          <p className="mt-4 text-sm text-steel">
            Настройки меняет владелец магазина. Проверить, что сделает сервис, можно и вам.
          </p>
        )}
        <div className="mt-5 flex flex-wrap gap-2">
          {isOwner && (
            <Button loading={busy === "save"} disabled={!dirty || busy !== null} onClick={save}>
              Сохранить настройки
            </Button>
          )}
          <Button
            variant="secondary"
            loading={busy === "preview"}
            disabled={busy !== null}
            onClick={check}
          >
            Проверить без отправки
          </Button>
          {isOwner && (
            <Button
              variant="secondary"
              loading={busy === "run"}
              disabled={dirty || !item.enabled || busy !== null}
              onClick={run}
              title={
                !item.enabled
                  ? "Сначала включите сервис"
                  : dirty
                    ? "Сначала сохраните настройки"
                    : undefined
              }
            >
              Запустить сейчас
            </Button>
          )}
        </div>
        <div className="mt-3 empty:hidden">
          <FormError error={error} />
          {done && <Notice kind="success">{done}</Notice>}
        </div>
        {preview && <PreviewBox preview={preview} />}
      </Section>

      {item.kind === "followup" && (
        <Section
          id="queue"
          title="Ждут вашего решения"
          description="Сообщения, которые сервис подготовил покупателям. Текст можно поправить перед отправкой."
        >
          <FollowupQueue />
        </Section>
      )}

      <Section title="История запусков">
        <RunHistory kind={item.kind} />
      </Section>
    </>
  );
}
