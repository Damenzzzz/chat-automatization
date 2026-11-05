"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { useState, type FormEvent } from "react";
import { useSWRConfig } from "swr";

import { NICHES } from "@/components/auth/auth-flow";
import { Autotest, SandboxChat } from "@/components/bot/sandbox";
import { ProfileForm } from "@/components/bot/profile-form";
import { CatalogImport } from "@/components/catalog/catalog-import";
import { ChannelsPanel } from "@/components/channels/channels-panel";
import { useSession } from "@/components/shell/session";
import { Button } from "@/components/ui/button";
import { SelectField, TextField } from "@/components/ui/field";
import { FormError, Loading, Page } from "@/components/ui/page";
import { Stepper } from "@/components/ui/stepper";
import { api, type Schemas } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";

const STEPS = ["Бизнес", "Товары", "Характер бота", "Песочница", "Каналы"];

function BusinessStep({
  shop,
  onDone,
}: {
  shop: Schemas["ShopOut"];
  onDone: (shop: Schemas["ShopOut"]) => void;
}) {
  const [name, setName] = useState(shop.name);
  const [niche, setNiche] = useState(shop.niche ?? "");
  const [city, setCity] = useState(shop.city ?? "");
  const [links, setLinks] = useState({
    instagram: shop.links.instagram ?? "",
    website: shop.links.website ?? "",
    two_gis: shop.links.two_gis ?? "",
    kaspi: shop.links.kaspi ?? "",
  });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const saved = await unwrap(
        api.PATCH("/shop", {
          body: {
            name: name.trim(),
            niche: niche || null,
            city: city.trim() || null,
            links: {
              instagram: links.instagram.trim() || null,
              website: links.website.trim() || null,
              two_gis: links.two_gis.trim() || null,
              kaspi: links.kaspi.trim() || null,
            },
          },
        }),
      );
      onDone(saved);
    } catch (failure) {
      setError(failure);
      setBusy(false);
    }
  }

  const link = (key: keyof typeof links) => (event: { target: { value: string } }) =>
    setLinks({ ...links, [key]: event.target.value });

  return (
    <form onSubmit={submit} className="flex max-w-2xl flex-col gap-5">
      <div className="grid gap-5 sm:grid-cols-2">
        <TextField
          className="sm:col-span-2"
          label="Название магазина"
          hint="Так бот будет представляться покупателям."
          required
          minLength={2}
          maxLength={200}
          value={name}
          onChange={(event) => setName(event.target.value)}
        />
        <SelectField
          label="Что продаёте"
          value={niche}
          onChange={(event) => setNiche(event.target.value)}
        >
          <option value="">Выберите</option>
          {[...new Set([...NICHES, ...(shop.niche ? [shop.niche] : [])])].map((item) => (
            <option key={item}>{item}</option>
          ))}
        </SelectField>
        <TextField
          label="Город"
          maxLength={100}
          value={city}
          onChange={(event) => setCity(event.target.value)}
        />
      </div>
      <fieldset className="grid gap-5 sm:grid-cols-2">
        <legend className="mb-3 font-medium">Где вас найти, если есть</legend>
        <TextField
          label="Instagram"
          placeholder="@pion.almaty"
          value={links.instagram}
          onChange={link("instagram")}
        />
        <TextField
          label="Сайт"
          placeholder="pion.kz"
          value={links.website}
          onChange={link("website")}
        />
        <TextField
          label="2GIS"
          placeholder="Ссылка на карточку"
          value={links.two_gis}
          onChange={link("two_gis")}
        />
        <TextField
          label="Kaspi"
          placeholder="Ссылка на магазин"
          value={links.kaspi}
          onChange={link("kaspi")}
        />
      </fieldset>
      <FormError error={error} />
      <div>
        <Button type="submit" loading={busy}>
          Сохранить и продолжить
        </Button>
      </div>
    </form>
  );
}

function StepFooter({
  onNext,
  nextLabel = "Продолжить",
  onSkip,
  disabled,
}: {
  onNext: () => void;
  nextLabel?: string;
  onSkip?: () => void;
  disabled?: boolean;
}) {
  return (
    <div className="mt-6 flex flex-wrap gap-2 border-t border-line pt-5">
      <Button onClick={onNext} disabled={disabled}>
        {nextLabel}
      </Button>
      {onSkip && (
        <Button variant="ghost" onClick={onSkip}>
          Пропустить пока
        </Button>
      )}
    </div>
  );
}

export function SetupWizard() {
  const router = useRouter();
  const params = useSearchParams();
  const { shop, isOwner } = useSession();
  const { mutate } = useSWRConfig();
  const [finishing, setFinishing] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [uploaded, setUploaded] = useState(false);

  if (!shop) return <Loading className="px-8" />;

  const reached = Math.max(shop.onboarding_step, shop.status === "onboarding" ? 1 : STEPS.length);
  const requested = Number(params.get("step"));
  const step = requested >= 1 && requested <= reached ? requested : Math.min(reached, STEPS.length);

  async function go(next: number) {
    if (isOwner && next > shop!.onboarding_step) {
      const saved = await unwrap(api.PATCH("/shop", { body: { onboarding_step: next } }));
      await mutate("/shop", saved, { revalidate: false });
    }
    router.push(`/setup?step=${next}`);
    document.getElementById("content")?.focus();
  }

  async function finish() {
    setFinishing(true);
    setError(null);
    try {
      const saved = await unwrap(api.PATCH("/shop", { body: { onboarding_done: true } }));
      await mutate("/shop", saved, { revalidate: false });
      router.push("/overview");
    } catch (failure) {
      setError(failure);
      setFinishing(false);
    }
  }

  return (
    <Page>
      <h1 className="text-2xl">Настройка магазина</h1>
      <p className="mt-1.5 mb-5 text-steel">
        Шаг {step} из {STEPS.length}: {STEPS[step - 1].toLowerCase()}. Можно прервать и вернуться,
        всё сохранится.
      </p>
      <Stepper
        steps={STEPS}
        current={step}
        reached={reached}
        onSelect={(next) => router.push(`/setup?step=${next}`)}
      />
      <div className="mt-8">
        {step === 1 && (
          <BusinessStep
            shop={shop}
            onDone={(saved) => {
              void mutate("/shop", saved, { revalidate: false });
              void go(2);
            }}
          />
        )}
        {step === 2 && (
          <>
            <h2 className="text-lg">Загрузите товары</h2>
            <p className="mt-1 mb-5 max-w-2xl text-sm text-steel">
              ИИ подскажет, что в какой колонке лежит, а вы подтвердите. Позже файл можно загрузить
              снова: цены и остатки обновятся, а новые товары добавятся.
            </p>
            <CatalogImport onDone={() => setUploaded(true)} />
            <StepFooter
              onNext={() => void go(3)}
              onSkip={uploaded ? undefined : () => void go(3)}
              disabled={!uploaded}
            />
          </>
        )}
        {step === 3 && (
          <div className="max-w-2xl">
            <h2 className="mb-5 text-lg">Как бот разговаривает с покупателями</h2>
            <ProfileForm saveLabel="Сохранить и продолжить" onSaved={() => void go(4)} />
          </div>
        )}
        {step === 4 && (
          <>
            <div className="grid gap-8 lg:grid-cols-2">
              <div>
                <h2 className="text-lg">Поговорите с ботом</h2>
                <p className="mt-1 mb-4 text-sm text-steel">
                  Спросите то, что обычно спрашивают ваши покупатели.
                </p>
                <SandboxChat />
              </div>
              <div>
                <h2 className="text-lg">Автопроверка</h2>
                <p className="mt-1 mb-4 text-sm text-steel">
                  Мы зададим боту вопросы по вашему каталогу и проверим ответы.
                </p>
                <Autotest />
              </div>
            </div>
            <StepFooter onNext={() => void go(5)} />
          </>
        )}
        {step === 5 && (
          <>
            <h2 className="mb-2 text-lg">Подключите каналы</h2>
            <p className="mb-4 max-w-2xl text-sm text-steel">
              Начните с Telegram или сайта, они подключаются за пять минут. Бот начнёт отвечать
              покупателям после пополнения баланса.
            </p>
            <ChannelsPanel />
            <FormError error={error} />
            <div className="border-t border-line pt-5">
              <Button loading={finishing} onClick={() => void finish()}>
                Закончить настройку
              </Button>
            </div>
          </>
        )}
      </div>
    </Page>
  );
}
