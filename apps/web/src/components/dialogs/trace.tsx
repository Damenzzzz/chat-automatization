import { money } from "@/lib/format";

type Step = Record<string, unknown> & { node?: string };

const INTENTS: Record<string, string> = {
  product: "вопрос о товаре",
  policy: "вопрос о доставке, оплате или условиях",
  order: "хочет заказать",
  human: "просит менеджера",
  smalltalk: "приветствие или разговор",
  offtopic: "вопрос не про магазин",
};

const LANGS: Record<string, string> = {
  ru: "русский",
  kk: "казахский",
  mixed: "смесь русского и казахского",
};

const TOOLS: Record<string, string> = {
  search_products: "поискал товары",
  get_product: "открыл карточку товара",
  search_kb: "поискал в базе знаний",
  create_lead: "создал заявку",
  handoff: "передал диалог менеджеру",
};

function list(value: unknown): string[] {
  return Array.isArray(value) ? value.map(String) : [];
}

function describe(step: Step): string | null {
  switch (step.node) {
    case "understand": {
      const intent = INTENTS[String(step.intent)] ?? String(step.intent);
      const lang = LANGS[String(step.lang)] ?? String(step.lang);
      return `Понял запрос: ${intent}, язык: ${lang}.`;
    }
    case "retrieve": {
      const found = list(step.found);
      const budget =
        typeof step.budget_max === "number" ? `, бюджет до ${money(step.budget_max)}` : "";
      return found.length
        ? `Искал в каталоге «${String(step.query)}»${budget}. Нашёл: ${found.join(", ")}.`
        : `Искал в каталоге «${String(step.query)}»${budget}. Ничего не нашёл.`;
    }
    case "kb": {
      const found = list(step.found);
      return found.length
        ? `Искал в базе знаний «${String(step.query)}» и нашёл подходящие записи: ${found.length}.`
        : `Искал в базе знаний «${String(step.query)}». Ничего не нашёл.`;
    }
    case "order":
      return step.sku
        ? `Начал оформлять заказ, артикул ${String(step.sku)}.`
        : "Начал оформлять заказ.";
    case "handoff":
      return "Покупатель попросил менеджера, диалог передан.";
    case "tools": {
      const calls = Array.isArray(step.calls) ? (step.calls as { name: string }[]) : [];
      const names = calls.map((call) => TOOLS[call.name] ?? call.name);
      return names.length ? `Дополнительно: ${names.join(", ")}.` : null;
    }
    case "guard_out": {
      if (step.ok) {
        const amounts = list(step.amounts).map((amount) => money(Number(amount)));
        return amounts.length
          ? `Проверил суммы по каталогу: ${amounts.join(", ")}. Всё верно.`
          : "Проверил ответ: сумм и артикулов из каталога нет, отправлять можно.";
      }
      return `Проверка не пройдена: ${list(step.errors).join("; ") || "сумма не совпала с каталогом"}. Ответ переписан.`;
    }
    case "fallback":
      return "Точный ответ не получился, поэтому бот сказал, что уточнит у менеджера.";
    case "gate":
      if (step.ok) return null;
      return step.reason === "no_balance"
        ? "Баланс закончился, бот ответил шаблоном без модели."
        : "Покупатель превысил лимит ответов в час, бот ответил шаблоном.";
    case "send":
      return step.delivered === false
        ? `Не доставлено: ${String(step.error ?? "канал недоступен")}.`
        : null;
    case "followup":
      return step.user_id
        ? "Напоминание покупателю: отправил менеджер из раздела «Сервисы»."
        : "Напоминание покупателю: отправлено сервисом «Возврат покупателя».";
    case "meter": {
      const charge = step.charge as { charged_kzt?: number } | undefined;
      if (charge?.charged_kzt !== undefined) return `Списано ${money(charge.charged_kzt)}.`;
      return step.unanswered ? "Вопрос записан в «Бот не знал ответа»." : null;
    }
    default:
      return null;
  }
}

export function HowBotFound({
  steps,
  model,
  latencyMs,
}: {
  steps: Step[];
  model?: string | null;
  latencyMs?: number | null;
}) {
  const lines = steps.map(describe).filter((line): line is string => Boolean(line));
  if (!lines.length) return null;
  return (
    <details className="group mt-1 w-full text-xs text-steel">
      <summary className="flex min-h-8 cursor-pointer items-center justify-end font-medium hover:text-ink">
        Как бот нашёл ответ
      </summary>
      <div className="mt-1 rounded-md border border-line bg-paper p-3 text-left text-ink">
        <ol className="flex list-decimal flex-col gap-1 pl-4">
          {lines.map((line, index) => (
            <li key={index}>{line}</li>
          ))}
        </ol>
        {(model || latencyMs) && (
          <p className="mt-2 text-steel">
            {model}
            {model && latencyMs ? ", " : ""}
            {latencyMs ? `ответ за ${(latencyMs / 1000).toFixed(1).replace(".", ",")} с` : ""}
          </p>
        )}
      </div>
    </details>
  );
}
