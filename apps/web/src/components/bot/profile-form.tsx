"use client";

import { useState, type FormEvent } from "react";
import useSWR from "swr";

import { Button } from "@/components/ui/button";
import { SelectField, TextArea } from "@/components/ui/field";
import { Notice } from "@/components/ui/notice";
import { FormError, LoadError, Loading } from "@/components/ui/page";
import { api, type Schemas } from "@/lib/api/client";
import { ApiError, unwrap } from "@/lib/api/errors";
import { cn } from "@/lib/utils";

export const PROFILE_KEY = "/bot-profile";

const PRESETS = [
  {
    name: "Дружелюбный",
    tone: "Тёплый и дружелюбный, коротко и по делу, без лишних эмоций.",
    sample: "Здравствуйте! Да, белые пионы есть. Подскажу букет под ваш бюджет?",
  },
  {
    name: "Деловой",
    tone: "Спокойный и точный: сразу цена, наличие и следующий шаг, без лишних слов.",
    sample: "Белые пионы в наличии, 15\u00a0000\u00a0₸ за букет. Доставка сегодня или завтра?",
  },
  {
    name: "Заботливый",
    tone: "Внимательный советчик: уточняет, для чего покупка, и помогает выбрать.",
    sample: "Подскажите, букет на какой повод? Подберу то, что подойдёт именно вам.",
  },
];

const RULES = [
  {
    key: "delivery",
    prefix: "Доставка",
    label: "Доставка",
    placeholder: "По Алматы от 2 000 ₸, день в день при заказе до 15:00",
  },
  { key: "payment", prefix: "Оплата", label: "Оплата", placeholder: "Kaspi, наличные курьеру" },
  {
    key: "discounts",
    prefix: "Скидки",
    label: "Скидки",
    placeholder: "Скидок нет, кроме акций на сайте",
  },
  {
    key: "handoff",
    prefix: "Когда звать менеджера",
    label: "Когда звать менеджера",
    placeholder: "Индивидуальный заказ, жалоба, опт",
  },
] as const;

const CUSTOM = "custom";
const ADDRESS = "address_form";

type Rules = Record<string, unknown>;

function strip(value: unknown, prefix: string): string {
  const text = typeof value === "string" ? value : "";
  return text.startsWith(`${prefix}: `) ? text.slice(prefix.length + 2) : text;
}

function toRules(
  existing: Rules,
  values: Record<string, string>,
  custom: string,
  address: string,
): Rules {
  const rules: Rules = { ...existing, [ADDRESS]: address };
  for (const { key, prefix } of RULES) {
    if (values[key]?.trim()) rules[key] = `${prefix}: ${values[key].trim()}`;
    else delete rules[key];
  }
  const lines = custom
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean);
  if (lines.length) rules[CUSTOM] = lines;
  else delete rules[CUSTOM];
  return rules;
}

function ProfileFields({
  profile,
  onSaved,
  saveLabel,
}: {
  profile: Schemas["ProfileOut"] | null;
  onSaved: (saved: Schemas["ProfileOut"]) => void;
  saveLabel: string;
}) {
  const [tone, setTone] = useState(profile?.tone ?? PRESETS[0].tone);
  const [greeting, setGreeting] = useState(profile?.greeting ?? "");
  const [address, setAddress] = useState(String(profile?.rules?.[ADDRESS] ?? "вы"));
  const [values, setValues] = useState<Record<string, string>>(
    Object.fromEntries(RULES.map(({ key, prefix }) => [key, strip(profile?.rules?.[key], prefix)])),
  );
  const [custom, setCustom] = useState(
    Array.isArray(profile?.rules?.[CUSTOM]) ? (profile.rules[CUSTOM] as string[]).join("\n") : "",
  );
  const [languages, setLanguages] = useState<string[]>(profile?.languages ?? ["ru", "kk"]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [saved, setSaved] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    setSaved(false);
    try {
      const result = await unwrap(
        api.PUT("/bot-profile", {
          body: {
            tone,
            greeting: greeting.trim() || null,
            rules: toRules(profile?.rules ?? {}, values, custom, address),
            languages,
            model_policy: profile?.model_policy ?? {},
          },
        }),
      );
      setSaved(true);
      onSaved(result);
    } catch (failure) {
      setError(failure);
    } finally {
      setBusy(false);
    }
  }

  function toggleLanguage(code: string, on: boolean) {
    const next = on ? [...languages, code] : languages.filter((item) => item !== code);
    if (next.length) setLanguages(next);
  }

  return (
    <form onSubmit={submit} className="flex flex-col gap-5">
      <fieldset>
        <legend className="mb-2 text-sm font-medium">Тон общения</legend>
        <div className="grid gap-2 sm:grid-cols-3">
          {PRESETS.map((preset) => {
            const selected = tone === preset.tone;
            return (
              <button
                key={preset.name}
                type="button"
                aria-pressed={selected}
                onClick={() => setTone(preset.tone)}
                className={cn(
                  "flex flex-col gap-1.5 rounded-md border px-3 py-2.5 text-left",
                  selected ? "border-ink bg-mist" : "border-control hover:bg-mist",
                )}
              >
                <span className="text-sm font-medium">{preset.name}</span>
                <span className="text-xs text-steel">{preset.sample}</span>
              </button>
            );
          })}
        </div>
      </fieldset>
      <TextArea
        label="Как бот должен говорить"
        hint="Выберите вариант выше или опишите своими словами."
        rows={2}
        maxLength={2000}
        value={tone}
        onChange={(event) => setTone(event.target.value)}
      />
      <TextArea
        label="Приветствие"
        rows={2}
        maxLength={2000}
        placeholder="Здравствуйте! Это «Цветы Пион». Подберём букет и доставим по Алматы."
        value={greeting}
        onChange={(event) => setGreeting(event.target.value)}
      />
      <div className="grid gap-5 sm:grid-cols-2">
        <SelectField
          label="Обращение к покупателю"
          value={address}
          onChange={(event) => setAddress(event.target.value)}
        >
          <option value="вы">На «вы»</option>
          <option value="ты">На «ты»</option>
        </SelectField>
        <fieldset>
          <legend className="mb-2 text-sm font-medium">Языки</legend>
          <div className="flex gap-5">
            {[
              ["ru", "Русский"],
              ["kk", "Казахский"],
            ].map(([code, name]) => (
              <label key={code} className="flex min-h-10 items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  className="size-4 accent-ink"
                  checked={languages.includes(code)}
                  onChange={(event) => toggleLanguage(code, event.target.checked)}
                />
                {name}
              </label>
            ))}
          </div>
        </fieldset>
      </div>
      <div className="grid gap-5 sm:grid-cols-2">
        {RULES.map(({ key, label, placeholder }) => (
          <TextArea
            key={key}
            label={label}
            rows={2}
            placeholder={placeholder}
            value={values[key]}
            onChange={(event) => setValues({ ...values, [key]: event.target.value })}
          />
        ))}
      </div>
      <TextArea
        label="Другие правила"
        hint="Каждое правило с новой строки."
        rows={3}
        value={custom}
        onChange={(event) => setCustom(event.target.value)}
      />
      <FormError error={error} />
      {saved && <Notice kind="success">Сохранено. Бот отвечает по новой версии.</Notice>}
      <div>
        <Button type="submit" loading={busy}>
          {saveLabel}
        </Button>
      </div>
    </form>
  );
}

export function ProfileForm({
  onSaved,
  saveLabel = "Сохранить",
}: {
  onSaved?: () => void;
  saveLabel?: string;
}) {
  const { data, error, isLoading, mutate } = useSWR(
    PROFILE_KEY,
    async () => {
      try {
        return await unwrap(api.GET("/bot-profile"));
      } catch (failure) {
        if (failure instanceof ApiError && failure.status === 404) return null;
        throw failure;
      }
    },
    { revalidateOnFocus: false },
  );
  if (isLoading) return <Loading />;
  if (error) return <LoadError error={error} retry={() => void mutate()} />;
  return (
    <ProfileFields
      key={data?.version ?? "new"}
      profile={data ?? null}
      saveLabel={saveLabel}
      onSaved={(saved) => {
        void mutate(saved, { revalidate: false });
        onSaved?.();
      }}
    />
  );
}
