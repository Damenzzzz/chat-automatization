"use client";

import { CircleCheck, CircleX, SendHorizontal } from "lucide-react";
import { useEffect, useRef, useState, type FormEvent } from "react";

import { Button } from "@/components/ui/button";
import { Notice } from "@/components/ui/notice";
import { FormError } from "@/components/ui/page";
import { api } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";
import { cn } from "@/lib/utils";

type Line = { from: "me" | "bot" | "note"; text: string };

const SUGGESTIONS = [
  "Здравствуйте, что у вас есть?",
  "Сколько стоит доставка?",
  "Сәлеметсіз бе, не ұсынасыз?",
];

export function SandboxChat() {
  const [session, setSession] = useState(() => crypto.randomUUID().replaceAll("-", ""));
  const [lines, setLines] = useState<Line[]>([]);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const log = useRef<HTMLDivElement>(null);

  useEffect(() => {
    log.current?.scrollTo({ top: log.current.scrollHeight });
  }, [lines, busy]);

  async function send(message: string) {
    const value = message.trim();
    if (!value || busy) return;
    setText("");
    setError(null);
    setLines((current) => [...current, { from: "me", text: value }]);
    setBusy(true);
    try {
      const turn = await unwrap(
        api.POST("/sandbox/chat", { body: { message: value, session_id: session } }),
      );
      setLines((current) => [
        ...current,
        turn.reply
          ? { from: "bot", text: turn.reply }
          : {
              from: "note",
              text: "Бот передал диалог менеджеру и молчит. Начните новый диалог, чтобы проверить дальше.",
            },
      ]);
    } catch (failure) {
      setError(failure);
    } finally {
      setBusy(false);
    }
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    void send(text);
  }

  return (
    <div className="flex h-[28rem] flex-col rounded-md border border-line">
      <div className="flex items-center justify-between gap-2 border-b border-line bg-mist px-3 py-2">
        <p className="text-sm text-steel">Покупатели этого не видят, деньги не списываются.</p>
        <button
          type="button"
          className="shrink-0 text-sm font-medium underline underline-offset-2"
          onClick={() => {
            setSession(crypto.randomUUID().replaceAll("-", ""));
            setLines([]);
            setError(null);
          }}
        >
          Новый диалог
        </button>
      </div>
      <div
        ref={log}
        role="log"
        aria-label="Переписка в песочнице"
        className="flex flex-1 flex-col gap-2 overflow-y-auto p-3"
      >
        {lines.length === 0 && (
          <div className="my-auto flex flex-col items-start gap-2">
            <p className="text-sm text-steel">Напишите как покупатель или начните с примера:</p>
            {SUGGESTIONS.map((suggestion) => (
              <button
                key={suggestion}
                type="button"
                onClick={() => void send(suggestion)}
                className="min-h-10 rounded-lg border border-control px-3 py-1.5 text-left text-sm hover:bg-mist"
              >
                {suggestion}
              </button>
            ))}
          </div>
        )}
        {lines.map((line, index) => (
          <p
            key={index}
            className={cn(
              "max-w-[85%] rounded-lg px-3 py-2 text-sm whitespace-pre-wrap",
              line.from === "me" && "self-start border border-line",
              line.from === "bot" && "self-end bg-haze",
              line.from === "note" && "max-w-full self-center text-center text-steel",
            )}
          >
            {line.text}
          </p>
        ))}
        {busy && (
          <p role="status" className="self-end text-sm text-steel">
            Бот думает
          </p>
        )}
      </div>
      {error ? (
        <div className="px-3 pb-2">
          <FormError error={error} />
        </div>
      ) : null}
      <form onSubmit={submit} className="flex gap-2 border-t border-line p-2">
        <label htmlFor="sandbox-message" className="sr-only">
          Сообщение боту
        </label>
        <input
          id="sandbox-message"
          value={text}
          maxLength={2000}
          onChange={(event) => setText(event.target.value)}
          placeholder="Сообщение"
          className="min-h-11 min-w-0 flex-1 rounded-md border border-control px-3 hover:border-ink sm:min-h-10"
        />
        <Button
          type="submit"
          aria-label="Отправить"
          disabled={!text.trim() || busy}
          className="px-3"
        >
          <SendHorizontal aria-hidden />
        </Button>
      </form>
    </div>
  );
}

type Item = {
  question: string;
  answer: string;
  correct: boolean;
  reason: string;
  kind?: string;
};
type Report = { total: number; correct: number; items: Item[] };

export function Autotest({ count = 20 }: { count?: number }) {
  const [report, setReport] = useState<Report | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);

  async function run() {
    setBusy(true);
    setError(null);
    try {
      const result = await unwrap(api.POST("/sandbox/autotest", { body: { count } }));
      setReport(result as unknown as Report);
    } catch (failure) {
      setError(failure);
    } finally {
      setBusy(false);
    }
  }

  const failed = report?.items.filter((item) => !item.correct) ?? [];

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center gap-3">
        <Button variant="secondary" loading={busy} onClick={() => void run()}>
          {report ? "Проверить ещё раз" : `Задать боту ${count} вопросов`}
        </Button>
        {busy && (
          <p role="status" className="text-sm text-steel">
            Вопросы составляются из вашего каталога, это занимает 1–2 минуты.
          </p>
        )}
      </div>
      <FormError error={error} />
      {report && (
        <div>
          <p className="display text-xl">
            <span className="tnum">
              {report.correct} из {report.total}
            </span>{" "}
            ответов верны
          </p>
          {failed.length === 0 ? (
            <Notice kind="success" className="mt-3">
              Ошибок нет. Можно подключать каналы.
            </Notice>
          ) : (
            <p className="mt-1 text-sm text-steel">
              Добавьте недостающее в правила бота или каталог и проверьте ещё раз.
            </p>
          )}
          <ul className="mt-4 divide-y divide-line border-y border-line">
            {[...failed, ...report.items.filter((item) => item.correct)].map((item, index) => (
              <li key={index}>
                <details>
                  <summary className="flex min-h-11 cursor-pointer items-start gap-2 py-2.5 text-sm">
                    {item.correct ? (
                      <CircleCheck
                        className="mt-0.5 size-4 shrink-0 text-steel"
                        aria-label="Верно"
                      />
                    ) : (
                      <CircleX className="mt-0.5 size-4 shrink-0 text-alert" aria-label="Неверно" />
                    )}
                    <span>{item.question}</span>
                  </summary>
                  <div className="pb-3 pl-6 text-sm">
                    <p className="whitespace-pre-wrap">{item.answer || "Бот не ответил."}</p>
                    <p className="mt-1 text-steel">{item.reason}</p>
                  </div>
                </details>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
