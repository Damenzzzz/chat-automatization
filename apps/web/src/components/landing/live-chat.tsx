"use client";

import { ArrowUp, Flower2 } from "lucide-react";
import { useEffect, useRef, useState, type FormEvent } from "react";

import { api, type Schemas } from "@/lib/api/client";
import { errorText, unwrap } from "@/lib/api/errors";
import { money } from "@/lib/format";
import { cn } from "@/lib/utils";

type Draft =
  | { from: "customer"; text: string }
  | { from: "bot"; text: string; cards: Schemas["DemoCard"][] }
  | { from: "note"; text: string };

type Bubble = Draft & { id: number };

const GREETING =
  "Сәлеметсіз бе! Это бот магазина «Цветы Пион». Спросите про букет, цену или доставку — на казахском или русском.";

const SUGGESTIONS = [
  "Есть розовые пионы до 35 000?",
  "51 раушан қанша тұрады?",
  "Анама гүл керек, 25 мыңға дейін",
  "Сколько стоит доставка?",
];

function keepNumbers(text: string): string {
  return text.replace(/(\d) (?=\d{3}\b)/g, "$1\u00a0").replace(/ ₸/g, "\u00a0₸");
}

function sessionId(): string {
  const fresh = () =>
    crypto.randomUUID?.().replaceAll("-", "") ?? Math.random().toString(36).slice(2, 18);
  try {
    const saved = sessionStorage.getItem("satushy-demo-chat");
    if (saved) return saved;
    const id = fresh();
    sessionStorage.setItem("satushy-demo-chat", id);
    return id;
  } catch {
    return fresh();
  }
}

function Card({ card }: { card: Schemas["DemoCard"] }) {
  return (
    <li className="flex min-w-0 items-center gap-3 rounded-lg border border-line bg-paper p-2 pr-3">
      <span className="flex size-10 shrink-0 items-center justify-center rounded-md bg-sun-soft text-ink">
        <Flower2 className="size-5" aria-hidden />
      </span>
      <span className="min-w-0 flex-1">
        <span className="block truncate text-sm font-medium">{card.name}</span>
        <span className="block text-xs text-steel">
          {card.stock ? `в наличии ${card.stock} шт.` : "под заказ"}
        </span>
      </span>
      {card.price !== null && (
        <span className="shrink-0 text-sm font-semibold tnum">{money(card.price)}</span>
      )}
    </li>
  );
}

export function LiveChat({ className }: { className?: string }) {
  const [bubbles, setBubbles] = useState<Bubble[]>([]);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [slow, setSlow] = useState(false);
  const log = useRef<HTMLOListElement>(null);
  const counter = useRef(0);
  const session = useRef<string | null>(null);

  useEffect(() => {
    const timer = setTimeout(
      () => setBubbles([{ id: 0, from: "bot", text: GREETING, cards: [] }]),
      450,
    );
    return () => clearTimeout(timer);
  }, []);

  useEffect(() => {
    log.current?.scrollTo({ top: log.current.scrollHeight, behavior: "smooth" });
  }, [bubbles, busy]);

  async function send(message: string) {
    const clean = message.trim();
    if (!clean || busy) return;
    session.current ??= sessionId();
    const push = (bubble: Draft) =>
      setBubbles((list) => [...list, { ...bubble, id: ++counter.current }]);
    push({ from: "customer", text: clean });
    setText("");
    setBusy(true);
    const slowTimer = setTimeout(() => setSlow(true), 3500);
    try {
      const reply = await unwrap(
        api.POST("/demo/chat", { body: { message: clean, session_id: session.current } }),
      );
      push({
        from: "bot",
        text: keepNumbers(reply.reply ?? "Передал вопрос менеджеру, он скоро ответит."),
        cards: reply.cards,
      });
    } catch (failure) {
      push({
        from: "note",
        text: errorText(failure) ?? "Бот сейчас недоступен. Попробуйте через минуту.",
      });
    } finally {
      clearTimeout(slowTimer);
      setSlow(false);
      setBusy(false);
    }
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    void send(text);
  }

  const asked = bubbles.some((bubble) => bubble.from === "customer");

  return (
    <section
      aria-label="Чат с ботом демо-магазина"
      className={cn(
        "flex h-[34rem] max-h-[78svh] flex-col overflow-hidden rounded-xl bg-paper shadow-[0_30px_60px_-20px_rgb(19_32_59/0.45)]",
        className,
      )}
    >
      <header className="flex items-center gap-3 bg-ink px-4 py-3 text-paper">
        <span className="flex size-10 items-center justify-center rounded-full bg-sun text-ink">
          <Flower2 className="size-5" aria-hidden />
        </span>
        <span className="min-w-0 flex-1">
          <span className="block font-semibold">Цветы Пион</span>
          <span className="block text-xs text-paper/70">
            {busy ? "печатает…" : "отвечает бот Satushy"}
          </span>
        </span>
        <span className="rounded-full bg-paper/10 px-2.5 py-1 text-xs">демо</span>
      </header>

      <ol
        ref={log}
        aria-live="polite"
        className="flex flex-1 flex-col gap-2.5 overflow-y-auto bg-[#e9eef3] bg-[url(/ornament-ink.svg)] bg-size-[120px_120px] px-3 py-4"
      >
        {bubbles.map((bubble) =>
          bubble.from === "note" ? (
            <li
              key={bubble.id}
              className="animate-bubble self-center px-4 text-center text-xs text-steel"
            >
              {bubble.text}
            </li>
          ) : (
            <li
              key={bubble.id}
              className={cn(
                "flex max-w-[88%] animate-bubble flex-col gap-2",
                bubble.from === "customer" ? "self-end" : "self-start",
              )}
            >
              <p
                className={cn(
                  "rounded-xl px-3.5 py-2 text-[0.9375rem] leading-snug whitespace-pre-line",
                  bubble.from === "customer"
                    ? "rounded-br-sm bg-sky text-ink"
                    : "rounded-bl-sm bg-paper text-ink",
                )}
              >
                <span className="sr-only">{bubble.from === "customer" ? "Вы: " : "Бот: "}</span>
                {bubble.text}
              </p>
              {bubble.from === "bot" && bubble.cards.length > 0 && (
                <ul className="flex flex-col gap-1.5" aria-label="Товары из каталога">
                  {bubble.cards.map((card) => (
                    <Card key={card.id} card={card} />
                  ))}
                </ul>
              )}
            </li>
          ),
        )}
        {busy && (
          <li className="flex flex-col gap-1 self-start" role="status">
            <span className="flex gap-1 rounded-xl rounded-bl-sm bg-paper px-3.5 py-3">
              {[0, 1, 2].map((dot) => (
                <span
                  key={dot}
                  className="size-1.5 animate-typing rounded-full bg-steel"
                  style={{ animationDelay: `${dot * 150}ms` }}
                />
              ))}
              <span className="sr-only">Бот печатает</span>
            </span>
            {slow && (
              <span className="px-1 text-xs text-steel">ищет в каталоге и сверяет цены</span>
            )}
          </li>
        )}
      </ol>

      {!asked && (
        <div className="flex gap-2 overflow-x-auto bg-[#e9eef3] px-3 pb-3">
          {SUGGESTIONS.map((suggestion) => (
            <button
              key={suggestion}
              type="button"
              onClick={() => void send(suggestion)}
              className="min-h-9 shrink-0 rounded-full border border-sky-deep/40 bg-paper px-3 text-sm text-ink hover:border-sky-deep"
            >
              {suggestion}
            </button>
          ))}
        </div>
      )}

      <form onSubmit={submit} className="flex items-center gap-2 border-t border-line p-2.5">
        <label htmlFor="demo-chat-input" className="sr-only">
          Сообщение боту
        </label>
        <input
          id="demo-chat-input"
          value={text}
          maxLength={500}
          autoComplete="off"
          onChange={(event) => setText(event.target.value)}
          placeholder="Напишите как покупатель"
          className="min-h-11 min-w-0 flex-1 rounded-full bg-mist px-4 text-base"
        />
        <button
          type="submit"
          disabled={busy || !text.trim()}
          aria-label="Отправить"
          className="flex size-11 shrink-0 items-center justify-center rounded-full bg-sky text-ink disabled:bg-haze disabled:text-steel"
        >
          <ArrowUp className="size-5" aria-hidden />
        </button>
      </form>
    </section>
  );
}
