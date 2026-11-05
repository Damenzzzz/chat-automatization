"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";
import { useSWRConfig } from "swr";

import { Autotest, SandboxChat } from "@/components/bot/sandbox";
import { ProfileForm } from "@/components/bot/profile-form";
import { CatalogImport } from "@/components/catalog/catalog-import";
import { ChannelsPanel } from "@/components/channels/channels-panel";
import { useSession } from "@/components/shell/session";
import { BusinessForm } from "@/components/shop/business-form";
import { Button } from "@/components/ui/button";
import { FormError, Loading, Page } from "@/components/ui/page";
import { Stepper } from "@/components/ui/stepper";
import { api } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";

const STEPS = ["Бизнес", "Товары", "Характер бота", "Песочница", "Каналы"];

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
          <BusinessForm
            shop={shop}
            saveLabel="Сохранить и продолжить"
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
