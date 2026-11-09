"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useRef, useState, type FormEvent } from "react";

import { DemoButton } from "@/components/auth/demo-button";
import { Button } from "@/components/ui/button";
import { SelectField, TextField } from "@/components/ui/field";
import { Notice } from "@/components/ui/notice";
import { FormError } from "@/components/ui/page";
import { api, authApi } from "@/lib/api/client";
import { ApiError, unwrap } from "@/lib/api/errors";
import { parseIdentity, safeNext, type Identity } from "@/lib/identity";

export const NICHES = [
  "Цветы и подарки",
  "Автозапчасти",
  "Электроника",
  "Одежда и обувь",
  "Косметика",
  "Стройматериалы",
  "Другое",
];

const RESEND_SECONDS = 30;

type Shop = { name: string; city: string; niche: string };
type Step = "identity" | "code" | "shop";

function CodeInput({
  value,
  onChange,
  disabled,
}: {
  value: string;
  onChange: (v: string) => void;
  disabled: boolean;
}) {
  return (
    <div className="flex flex-col gap-1.5">
      <label htmlFor="otp" className="text-sm font-medium">
        Код из сообщения
      </label>
      <input
        id="otp"
        autoFocus
        value={value}
        disabled={disabled}
        onChange={(event) => onChange(event.target.value.replace(/\D/g, "").slice(0, 6))}
        inputMode="numeric"
        autoComplete="one-time-code"
        pattern="[0-9]*"
        className="min-h-16 w-full rounded-md border border-control/70 bg-paper px-4 text-center text-2xl font-semibold tracking-[0.35em] tnum hover:border-ink focus-visible:border-sky-deep disabled:bg-mist"
      />
    </div>
  );
}

function ShopFields({ shop, onChange }: { shop: Shop; onChange: (shop: Shop) => void }) {
  return (
    <>
      <TextField
        label="Название магазина"
        required
        minLength={2}
        maxLength={200}
        autoComplete="organization"
        value={shop.name}
        onChange={(event) => onChange({ ...shop, name: event.target.value })}
      />
      <SelectField
        label="Что продаёте"
        value={shop.niche}
        onChange={(event) => onChange({ ...shop, niche: event.target.value })}
      >
        <option value="">Выберите</option>
        {NICHES.map((niche) => (
          <option key={niche}>{niche}</option>
        ))}
      </SelectField>
      <TextField
        label="Город"
        maxLength={100}
        autoComplete="address-level2"
        value={shop.city}
        onChange={(event) => onChange({ ...shop, city: event.target.value })}
      />
    </>
  );
}

export function AuthFlow({ mode }: { mode: "login" | "signup" }) {
  const router = useRouter();
  const params = useSearchParams();
  const [step, setStep] = useState<Step>("identity");
  const [raw, setRaw] = useState("");
  const [identity, setIdentity] = useState<Identity | null>(null);
  const [inputError, setInputError] = useState<string | null>(null);
  const [code, setCode] = useState("");
  const [shop, setShop] = useState<Shop>({ name: "", city: "", niche: "" });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [wait, setWait] = useState(0);
  const [demoCode, setDemoCode] = useState<string | null>(null);
  const lastTried = useRef("");

  useEffect(() => {
    if (wait <= 0) return;
    const timer = setTimeout(() => setWait(wait - 1), 1000);
    return () => clearTimeout(timer);
  }, [wait]);

  async function sendCode(target: Identity) {
    setBusy(true);
    setError(null);
    try {
      const sent = await unwrap(authApi.POST("/auth/request-code", { body: target }));
      setDemoCode(sent.demo_code ?? null);
      setCode("");
      lastTried.current = "";
      setWait(RESEND_SECONDS);
      setStep("code");
    } catch (failure) {
      setError(failure);
    } finally {
      setBusy(false);
    }
  }

  function submitIdentity(event: FormEvent) {
    event.preventDefault();
    const parsed = parseIdentity(raw);
    if (!parsed) {
      setInputError("Введите казахстанский номер, например +7 700 123 45 67, или почту.");
      return;
    }
    setInputError(null);
    setIdentity(parsed);
    void sendCode(parsed);
  }

  async function verify(withShop: boolean) {
    if (!identity) return;
    setBusy(true);
    setError(null);
    const signup =
      withShop && shop.name.trim()
        ? { name: shop.name.trim(), city: shop.city.trim() || null, niche: shop.niche || null }
        : null;
    try {
      await unwrap(authApi.POST("/auth/verify", { body: { ...identity, code, signup } }));
      const current = await unwrap(api.GET("/shop"));
      const next = params.get("next");
      if (next) router.replace(safeNext(next));
      else if (current.status === "onboarding")
        router.replace(`/setup?step=${current.onboarding_step}`);
      else router.replace("/overview");
    } catch (failure) {
      if (failure instanceof ApiError && failure.code === "signup_required") {
        setStep("shop");
      } else {
        setError(failure);
        setBusy(false);
        if (failure instanceof ApiError && failure.code === "wrong_code") setCode("");
      }
      setBusy(false);
    }
  }

  function changeCode(value: string) {
    setCode(value);
    setError(null);
    if (value.length === 6 && lastTried.current !== value && !busy) {
      lastTried.current = value;
      setTimeout(() => codeForm.current?.requestSubmit(), 0);
    }
  }

  const codeForm = useRef<HTMLFormElement>(null);

  if (step === "shop") {
    return (
      <form
        className="flex flex-col gap-4"
        onSubmit={(event) => {
          event.preventDefault();
          void verify(true);
        }}
      >
        <div>
          <h1 className="text-2xl">Новый магазин</h1>
          <p className="mt-1.5 text-steel">
            Этого номера ещё нет в Satushy. Назовите магазин, и кабинет будет готов.
          </p>
        </div>
        <ShopFields shop={shop} onChange={setShop} />
        <FormError error={error} />
        <Button type="submit" loading={busy}>
          Создать магазин
        </Button>
      </form>
    );
  }

  if (step === "code") {
    return (
      <form
        ref={codeForm}
        className="flex flex-col gap-4"
        onSubmit={(event) => {
          event.preventDefault();
          void verify(mode === "signup");
        }}
      >
        <div>
          <h1 className="text-2xl">Введите код</h1>
          <p className="mt-1.5 break-words text-steel">
            Отправили 6 цифр на{" "}
            {identity && ("email" in identity ? identity.email : identity.phone)}.
          </p>
        </div>
        {demoCode && (
          <Notice>
            <p>
              Демо-режим: SMS и письма не отправляем. Ваш код —{" "}
              <strong className="tnum">{demoCode}</strong>.
            </p>
            <button
              type="button"
              className="mt-1 font-semibold underline underline-offset-2"
              onClick={() => changeCode(demoCode)}
            >
              Подставить код
            </button>
          </Notice>
        )}
        <CodeInput value={code} onChange={changeCode} disabled={busy} />
        <FormError error={error} />
        <Button type="submit" loading={busy} disabled={code.length !== 6}>
          Войти
        </Button>
        <div className="flex flex-wrap justify-between gap-2 text-sm">
          <button
            type="button"
            className="font-medium underline underline-offset-2"
            onClick={() => {
              setStep("identity");
              setError(null);
            }}
          >
            Изменить номер или почту
          </button>
          <button
            type="button"
            disabled={wait > 0 || busy}
            onClick={() => identity && void sendCode(identity)}
            className="font-medium underline underline-offset-2 disabled:text-steel disabled:no-underline"
          >
            {wait > 0 ? `Отправить снова через ${wait} с` : "Отправить снова"}
          </button>
        </div>
      </form>
    );
  }

  return (
    <form className="flex flex-col gap-4" onSubmit={submitIdentity} noValidate={false}>
      <div>
        <h1 className="text-2xl">
          {mode === "signup" ? "Регистрация магазина" : "Вход в кабинет"}
        </h1>
        <p className="mt-1.5 text-steel">
          {mode === "signup"
            ? "Настройка займёт около часа, её можно прервать и вернуться."
            : "Пришлём код подтверждения, пароль не нужен."}
        </p>
      </div>
      {mode === "signup" && <ShopFields shop={shop} onChange={setShop} />}
      <TextField
        label="Телефон или почта"
        required
        autoFocus={mode === "login"}
        autoComplete="username"
        placeholder="+7 700 123 45 67"
        value={raw}
        error={inputError}
        onChange={(event) => setRaw(event.target.value)}
      />
      <FormError error={error} />
      {params.get("expired") && <Notice>Сессия истекла, войдите снова.</Notice>}
      <Button type="submit" loading={busy}>
        Получить код
      </Button>
      {mode === "login" && (
        <div className="flex flex-col gap-3 border-t border-line pt-4">
          <p className="text-sm text-steel">
            Хотите сначала посмотреть? Демо-магазин цветов с диалогами, заявками и живым ботом.
          </p>
          <DemoButton />
        </div>
      )}
      <p className="text-sm text-steel">
        {mode === "signup" ? "Уже есть кабинет? " : "Ещё нет кабинета? "}
        <Link
          href={mode === "signup" ? "/login" : "/signup"}
          className="font-medium text-ink underline underline-offset-2"
        >
          {mode === "signup" ? "Войти" : "Зарегистрировать магазин"}
        </Link>
      </p>
    </form>
  );
}
