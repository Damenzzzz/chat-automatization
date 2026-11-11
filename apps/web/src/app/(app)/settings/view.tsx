"use client";

import { useState, type FormEvent } from "react";
import useSWR, { useSWRConfig } from "swr";

import { useSession } from "@/components/shell/session";
import { BusinessForm } from "@/components/shop/business-form";
import { setAlerts, useAlertsEnabled } from "@/components/shell/attention";
import { TemplatesForm } from "@/components/shop/templates-form";
import { Button } from "@/components/ui/button";
import { TextField } from "@/components/ui/field";
import { FormError, LoadError, Loading, Page, PageHeader, Section } from "@/components/ui/page";
import { api } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";
import { parseIdentity } from "@/lib/identity";

const ROLES: Record<string, string> = {
  owner: "Владелец",
  manager: "Менеджер",
  admin: "Администратор",
};

function Team() {
  const { me } = useSession();
  const { data, error, isLoading, mutate } = useSWR("/team", () => unwrap(api.GET("/team")));
  const [raw, setRaw] = useState("");
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<unknown>(null);
  const [inputError, setInputError] = useState<string | null>(null);
  const [confirming, setConfirming] = useState<string | null>(null);

  async function invite(event: FormEvent) {
    event.preventDefault();
    const identity = parseIdentity(raw);
    if (!identity) {
      setInputError("Введите казахстанский номер, например +7 700 123 45 67, или почту.");
      return;
    }
    setInputError(null);
    setBusy(true);
    setFailure(null);
    try {
      await unwrap(
        api.POST("/team/invite", {
          body: { ...identity, name: name.trim() || null, role: "manager" },
        }),
      );
      setRaw("");
      setName("");
      void mutate();
    } catch (problem) {
      setFailure(problem);
    } finally {
      setBusy(false);
    }
  }

  async function remove(id: string) {
    setFailure(null);
    try {
      await unwrap(api.DELETE("/team/{user_id}", { params: { path: { user_id: id } } }));
      void mutate();
    } catch (problem) {
      setFailure(problem);
    } finally {
      setConfirming(null);
    }
  }

  if (isLoading) return <Loading />;
  if (error || !data) return <LoadError error={error} retry={() => void mutate()} />;

  return (
    <div className="flex max-w-2xl flex-col gap-5">
      <ul className="divide-y divide-line border-y border-line">
        {data.map((member) => (
          <li
            key={member.id}
            className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2 py-2.5 text-sm"
          >
            <div className="min-w-0">
              <p className="font-medium break-words">
                {member.name || member.phone || member.email}
              </p>
              <p className="break-words text-steel">
                {ROLES[member.role] ?? member.role}
                {member.name ? `, ${member.phone ?? member.email}` : ""}
                {member.is_active ? "" : ", доступ отключён"}
              </p>
            </div>
            {member.id !== me?.user_id &&
              member.is_active &&
              (confirming === member.id ? (
                <div className="flex gap-2">
                  <Button variant="danger" onClick={() => void remove(member.id)}>
                    Отключить доступ
                  </Button>
                  <Button variant="ghost" onClick={() => setConfirming(null)}>
                    Отмена
                  </Button>
                </div>
              ) : (
                <Button variant="ghost" onClick={() => setConfirming(member.id)}>
                  Убрать
                </Button>
              ))}
          </li>
        ))}
      </ul>
      <form onSubmit={invite} className="flex flex-col gap-3">
        <div className="grid gap-3 sm:grid-cols-2">
          <TextField
            label="Телефон или почта менеджера"
            required
            value={raw}
            error={inputError}
            onChange={(event) => setRaw(event.target.value)}
          />
          <TextField
            label="Имя"
            maxLength={200}
            value={name}
            onChange={(event) => setName(event.target.value)}
          />
        </div>
        <FormError error={failure} />
        <div>
          <Button type="submit" variant="secondary" loading={busy}>
            Добавить менеджера
          </Button>
        </div>
      </form>
      <p className="text-sm text-steel">
        Менеджер входит по коду на этот номер или почту и видит диалоги и заявки.
      </p>
    </div>
  );
}

function TelegramNotifications() {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [url, setUrl] = useState<string | null>(null);

  async function link() {
    setBusy(true);
    setError(null);
    try {
      const result = await unwrap(api.POST("/me/telegram/link"));
      setUrl(result.url);
    } catch (failure) {
      setError(failure);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex max-w-2xl flex-col gap-3">
      {url ? (
        <p className="text-sm">
          <a
            href={url}
            target="_blank"
            rel="noreferrer"
            className="font-medium underline underline-offset-2"
          >
            Откройте бота в Telegram
          </a>{" "}
          и нажмите Start. Ссылка одноразовая и скоро устареет.
        </p>
      ) : (
        <div>
          <Button variant="secondary" loading={busy} onClick={() => void link()}>
            Получать уведомления в Telegram
          </Button>
        </div>
      )}
      <FormError error={error} />
    </div>
  );
}

function BrowserAlerts() {
  const enabled = useAlertsEnabled();
  const [denied, setDenied] = useState(false);

  async function enable() {
    if ("Notification" in window && Notification.permission !== "granted") {
      setDenied((await Notification.requestPermission()) === "denied");
    }
    setAlerts(true);
  }

  return (
    <div className="flex max-w-2xl flex-col gap-3">
      <div>
        {enabled ? (
          <Button variant="secondary" onClick={() => setAlerts(false)}>
            Выключить звук и уведомления
          </Button>
        ) : (
          <Button variant="secondary" onClick={() => void enable()}>
            Включить звук и уведомления
          </Button>
        )}
      </div>
      <p role="status" className="text-sm text-steel">
        {enabled
          ? "Включено на этом устройстве. Работает, пока кабинет открыт во вкладке."
          : "Выключено. Настройка действует только на этом устройстве."}
        {denied && " Браузер запретил уведомления: останется только звук."}
      </p>
    </div>
  );
}

export function SettingsView() {
  const { shop, isOwner } = useSession();
  const { mutate } = useSWRConfig();
  return (
    <Page>
      <PageHeader title="Настройки">
        {isOwner
          ? "Данные магазина, шаблоны, команда и уведомления."
          : "Уведомления о покупателях, которые ждут ответа."}
      </PageHeader>
      {isOwner && (
        <>
          <Section title="Магазин">
            {shop ? (
              <BusinessForm
                key={shop.id}
                shop={shop}
                saveLabel="Сохранить"
                showSaved
                onDone={(saved) => void mutate("/shop", saved, { revalidate: false })}
              />
            ) : (
              <Loading />
            )}
          </Section>
          <Section
            title="Шаблоны ответов"
            description="Готовые ответы появятся кнопками под полем сообщения в диалогах."
          >
            {shop ? (
              <TemplatesForm
                key={shop.id}
                templates={shop.reply_templates}
                onDone={(saved) => void mutate("/shop", saved, { revalidate: false })}
              />
            ) : (
              <Loading />
            )}
          </Section>
          <Section title="Команда">
            <Team />
          </Section>
        </>
      )}
      <Section
        title="Уведомления в Telegram"
        description="Напишем, когда покупатель ждёт менеджера, пришла заявка или на балансе мало денег."
      >
        <TelegramNotifications />
      </Section>
      <Section
        title="Уведомления в браузере"
        description="Звук и всплывающее уведомление, когда новый покупатель ждёт ответа менеджера."
      >
        <BrowserAlerts />
      </Section>
    </Page>
  );
}
