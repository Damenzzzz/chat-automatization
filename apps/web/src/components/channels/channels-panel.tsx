"use client";

import { CircleAlert, CircleCheck, Clock } from "lucide-react";
import { useState, type FormEvent, type ReactNode } from "react";
import useSWR from "swr";

import { Button } from "@/components/ui/button";
import { CopyRow } from "@/components/ui/copy";
import { TextField } from "@/components/ui/field";
import { Notice } from "@/components/ui/notice";
import { FormError, LoadError, Loading } from "@/components/ui/page";
import { api, type Schemas } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";

type Channel = Schemas["ChannelOut"];

const KEY = "/channels";

const WHATSAPP_STEPS: { title: string; text: ReactNode }[] = [
  {
    title: "Номер",
    text: "Возьмите номер, на котором нет аккаунта WhatsApp, или удалите аккаунт в приложении на текущем номере. После подключения переписка идёт через кабинет Satushy, а не через телефон.",
  },
  {
    title: "Бизнес-портфолио",
    text: "На business.facebook.com создайте портфолио с названием как в документах ИП.",
  },
  {
    title: "Приложение",
    text: "На developers.facebook.com: My Apps, Create App, тип Business. Привяжите приложение к своему портфолио.",
  },
  {
    title: "Номер в WhatsApp",
    text: "В приложении добавьте продукт WhatsApp, затем API Setup, Add phone number. Введите номер и отображаемое имя магазина, подтвердите кодом из SMS или звонка.",
  },
  {
    title: "Постоянный токен",
    text: "Business Settings, Users, System users, Add (роль Admin). В Assign assets выберите приложение и WhatsApp-аккаунт, полный доступ. Generate token: срок Never, разрешения whatsapp_business_messaging и whatsapp_business_management. Скопируйте токен.",
  },
  {
    title: "Ключ приложения",
    text: "App Settings, Basic, App Secret, Show. Скопируйте: по нему мы проверяем, что сообщения пришли от Meta.",
  },
  { title: "Оплата Meta", text: "WhatsApp Manager, Payment settings: добавьте карту." },
  {
    title: "Ключи в Satushy",
    text: "Вставьте Phone number ID, WhatsApp Business Account ID, токен и App Secret в форму ниже и нажмите «Сохранить ключи».",
  },
  {
    title: "Вебхук",
    text: "Скопируйте отсюда Callback URL и Verify token. В приложении Meta: WhatsApp, Configuration, Webhook, Edit, Verify and save. В Webhook fields подпишитесь на messages.",
  },
  {
    title: "Режим Live",
    text: "Переведите приложение в Live. Нужна ссылка на политику конфиденциальности, шаблон дадим.",
  },
  {
    title: "Верификация бизнеса",
    text: "Business Settings, Security Center: загрузите документы ИП. Для входящих диалогов можно начать и без неё, но она повышает лимиты.",
  },
  {
    title: "Тест",
    text: "Напишите на номер с другого телефона. Бот ответит, а диалог появится в кабинете.",
  },
];

function Status({ channel }: { channel: Channel | undefined }) {
  if (!channel) return <p className="text-sm text-steel">Не подключён</p>;
  if (channel.status === "active") {
    return (
      <p className="flex items-center gap-1.5 text-sm font-medium">
        <CircleCheck className="size-4" aria-hidden />
        Работает{channel.name ? `, ${channel.name}` : ""}
      </p>
    );
  }
  if (channel.status === "error") {
    return (
      <p className="flex items-center gap-1.5 text-sm font-medium text-alert">
        <CircleAlert className="size-4" aria-hidden />
        Ошибка подключения
      </p>
    );
  }
  return (
    <p className="flex items-center gap-1.5 text-sm text-steel">
      <Clock className="size-4" aria-hidden />
      Ждёт проверки
    </p>
  );
}

function ChannelBlock({
  title,
  status,
  description,
  children,
}: {
  title: string;
  status: ReactNode;
  description: ReactNode;
  children?: ReactNode;
}) {
  return (
    <section className="border-t border-line py-6">
      <div className="flex flex-wrap items-baseline justify-between gap-x-6 gap-y-1">
        <h2 className="text-lg">{title}</h2>
        {status}
      </div>
      <p className="mt-1 max-w-2xl text-sm text-steel">{description}</p>
      {children && <div className="mt-4 max-w-2xl">{children}</div>}
    </section>
  );
}

function CheckButton({ channel, onChecked }: { channel: Channel; onChecked: () => void }) {
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<Schemas["CheckOut"] | null>(null);
  const [error, setError] = useState<unknown>(null);

  async function check() {
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      setResult(
        await unwrap(
          api.POST("/channels/{channel_id}/check", {
            params: { path: { channel_id: channel.id } },
          }),
        ),
      );
      onChecked();
    } catch (failure) {
      setError(failure);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex flex-col gap-3">
      <div>
        <Button variant="secondary" loading={busy} onClick={() => void check()}>
          Проверить подключение
        </Button>
      </div>
      <FormError error={error} />
      {result?.ok && (
        <Notice kind="success">
          Подключение работает{result.display_name ? `: ${result.display_name}` : ""}. Напишите на
          этот канал с другого аккаунта, чтобы проверить ответ бота.
        </Notice>
      )}
      {result && !result.ok && (
        <Notice kind="error">Не удалось подключиться: {result.error}</Notice>
      )}
    </div>
  );
}

function TelegramBlock({
  channel,
  refresh,
}: {
  channel: Channel | undefined;
  refresh: () => void;
}) {
  const [token, setToken] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await unwrap(api.POST("/channels/telegram", { body: { token } }));
      setToken("");
      refresh();
    } catch (failure) {
      setError(failure);
    } finally {
      setBusy(false);
    }
  }

  return (
    <ChannelBlock
      title="Telegram"
      status={<Status channel={channel} />}
      description="Создайте бота в @BotFather командой /newbot и вставьте токен, остальное мы настроим сами. Около 5 минут."
    >
      <div className="flex flex-col gap-4">
        <form onSubmit={submit} className="flex flex-col gap-3 sm:flex-row sm:items-end">
          <TextField
            className="flex-1"
            label={channel ? "Новый токен бота" : "Токен бота"}
            placeholder="123456789:AAE..."
            autoComplete="off"
            spellCheck={false}
            required
            value={token}
            onChange={(event) => setToken(event.target.value)}
          />
          <Button type="submit" loading={busy} disabled={!token.trim()}>
            Подключить
          </Button>
        </form>
        <FormError error={error} />
        {channel?.last_error && <Notice kind="error">{channel.last_error}</Notice>}
        {channel && <CheckButton channel={channel} onChecked={refresh} />}
      </div>
    </ChannelBlock>
  );
}

function WebBlock({ channels, refresh }: { channels: Channel[]; refresh: () => void }) {
  const [domain, setDomain] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await unwrap(api.POST("/channels/web", { body: { domain } }));
      setDomain("");
      refresh();
    } catch (failure) {
      setError(failure);
    } finally {
      setBusy(false);
    }
  }

  return (
    <ChannelBlock
      title="Сайт"
      status={<Status channel={channels[0]} />}
      description="Чат появится на вашем сайте. Подойдут Tilda, WordPress и любой другой сайт, где можно вставить код. Около 5 минут."
    >
      <div className="flex flex-col gap-5">
        <form onSubmit={submit} className="flex flex-col gap-3 sm:flex-row sm:items-end">
          <TextField
            className="flex-1"
            label={channels.length ? "Добавить ещё один сайт" : "Адрес сайта"}
            placeholder="pion.kz"
            autoComplete="off"
            spellCheck={false}
            required
            value={domain}
            onChange={(event) => setDomain(event.target.value)}
          />
          <Button type="submit" loading={busy} disabled={!domain.trim()}>
            Получить код
          </Button>
        </form>
        <FormError error={error} />
        {channels.map(
          (channel) =>
            channel.snippet && (
              <div key={channel.id} className="flex flex-col gap-2">
                <CopyRow label={`Код виджета для ${channel.domain}`} value={channel.snippet} />
                <p className="text-xs text-steel">
                  Вставьте эту строку перед закрывающим тегом body.
                </p>
              </div>
            ),
        )}
      </div>
    </ChannelBlock>
  );
}

function WhatsAppBlock({
  channel,
  refresh,
}: {
  channel: Channel | undefined;
  refresh: () => void;
}) {
  const [form, setForm] = useState({
    phone_number_id: "",
    waba_id: "",
    access_token: "",
    app_secret: "",
  });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [saved, setSaved] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    setSaved(false);
    try {
      await unwrap(api.POST("/channels/whatsapp", { body: form }));
      setForm({ phone_number_id: "", waba_id: "", access_token: "", app_secret: "" });
      setSaved(true);
      refresh();
    } catch (failure) {
      setError(failure);
    } finally {
      setBusy(false);
    }
  }

  const set = (key: keyof typeof form) => (event: { target: { value: string } }) =>
    setForm({ ...form, [key]: event.target.value });

  return (
    <ChannelBlock
      title="WhatsApp"
      status={<Status channel={channel} />}
      description="Подключается через ваше приложение Meta, 30–60 минут. Счета Meta за сообщения приходят вам напрямую."
    >
      <div className="flex flex-col gap-5">
        <Notice>
          С 1 октября 2026 ответы в окне 24 часов бесплатны только до 1 000 в месяц на номер, дальше
          каждое сообщение платное. Без карты в WhatsApp Manager доставка может остановиться.
        </Notice>
        <details className="rounded-md border border-line">
          <summary className="flex min-h-11 items-center px-3 text-sm font-medium">
            Пошаговая инструкция, 12 шагов
          </summary>
          <ol className="flex flex-col gap-3 border-t border-line px-3 py-3">
            {WHATSAPP_STEPS.map((step, index) => (
              <li key={step.title} className="flex gap-3 text-sm">
                <span className="w-5 shrink-0 text-right text-steel tnum">{index + 1}.</span>
                <div>
                  <p className="font-medium">{step.title}</p>
                  <p className="text-steel">{step.text}</p>
                </div>
              </li>
            ))}
          </ol>
        </details>
        <form onSubmit={submit} className="flex flex-col gap-4">
          <div className="grid gap-4 sm:grid-cols-2">
            <TextField
              label="Phone number ID"
              inputMode="numeric"
              pattern="\d{5,32}"
              required
              autoComplete="off"
              value={form.phone_number_id}
              onChange={set("phone_number_id")}
            />
            <TextField
              label="WhatsApp Business Account ID"
              inputMode="numeric"
              pattern="\d{5,32}"
              required
              autoComplete="off"
              value={form.waba_id}
              onChange={set("waba_id")}
            />
            <TextField
              label="Постоянный токен"
              type="password"
              required
              minLength={20}
              autoComplete="off"
              value={form.access_token}
              onChange={set("access_token")}
            />
            <TextField
              label="App Secret"
              type="password"
              required
              minLength={16}
              autoComplete="off"
              value={form.app_secret}
              onChange={set("app_secret")}
            />
          </div>
          <FormError error={error} />
          {saved && (
            <Notice kind="success">Ключи сохранены и зашифрованы. Теперь настройте вебхук.</Notice>
          )}
          <div>
            <Button type="submit" loading={busy}>
              Сохранить ключи
            </Button>
          </div>
        </form>
        {channel?.webhook_url && (
          <div className="flex flex-col gap-4 border-t border-line pt-5">
            <CopyRow label="Callback URL" value={channel.webhook_url} />
            {channel.verify_token && (
              <CopyRow label="Verify token" value={channel.verify_token} secret />
            )}
            {channel.last_error && <Notice kind="error">{channel.last_error}</Notice>}
            <CheckButton channel={channel} onChecked={refresh} />
          </div>
        )}
      </div>
    </ChannelBlock>
  );
}

export function ChannelsPanel() {
  const { data, error, isLoading, mutate } = useSWR(KEY, () => unwrap(api.GET("/channels")));
  if (isLoading) return <Loading />;
  if (error || !data) return <LoadError error={error} retry={() => void mutate()} />;
  const refresh = () => void mutate();
  const latest = (type: string) => data.filter((channel) => channel.type === type).at(-1);
  return (
    <div>
      <TelegramBlock channel={latest("telegram")} refresh={refresh} />
      <WebBlock channels={data.filter((channel) => channel.type === "web")} refresh={refresh} />
      <WhatsAppBlock channel={latest("whatsapp")} refresh={refresh} />
      <ChannelBlock
        title="Instagram"
        status={<p className="text-sm text-steel">Скоро</p>}
        description="Вход через Instagram появится, когда Meta одобрит наше приложение. Нужен будет профессиональный аккаунт."
      />
    </div>
  );
}
