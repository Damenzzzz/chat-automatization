"use client";

import { useRef, useState, type FormEvent } from "react";

import { cn } from "@/lib/utils";

type Status = { kind: "idle" | "sending" | "ok" | "error"; text: string };

const FIELD =
  "min-h-12 w-full rounded-lg border border-[#c3ccd8] bg-paper px-3.5 text-base text-ink focus-visible:border-sky-deep focus-visible:outline-sky-deep aria-[invalid=true]:border-alert";

/** Форма заявки отдельного лендинга. Отправляет на `/api/lead` своего же домена. */
export function ContactForm() {
  const [status, setStatus] = useState<Status>({ kind: "idle", text: "" });
  const [invalid, setInvalid] = useState<{ name?: boolean; contact?: boolean }>({});
  // Время открытия формы: робот отправляет её быстрее человека.
  const [openedAt] = useState(() => Date.now());
  const form = useRef<HTMLFormElement>(null);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    const value = (key: string) => String(data.get(key) ?? "").trim();
    const bad = { name: value("name").length < 1, contact: value("contact").length < 3 };
    setInvalid(bad);
    if (bad.name || bad.contact) {
      setStatus({ kind: "error", text: "Укажите имя и контакт, по которому с вами связаться." });
      const first = bad.name ? "name" : "contact";
      event.currentTarget.querySelector<HTMLInputElement>(`[name="${first}"]`)?.focus();
      return;
    }

    setStatus({ kind: "sending", text: "Отправляем заявку…" });
    try {
      const response = await fetch("/api/lead", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: value("name"),
          contact: value("contact"),
          company: value("company"),
          task: value("task"),
          website: String(data.get("website") ?? ""),
          elapsed: Date.now() - openedAt,
          page: window.location.pathname,
        }),
      });
      const reply = (await response.json().catch(() => ({}))) as { ok?: boolean; error?: string };
      if (!response.ok || !reply.ok) throw new Error(reply.error ?? "");
      form.current?.reset();
      setStatus({
        kind: "ok",
        text: "Заявка отправлена. Мы свяжемся с вами по указанному контакту.",
      });
    } catch (failure) {
      const reason =
        failure instanceof Error && !(failure instanceof TypeError) ? failure.message : "";
      setStatus({
        kind: "error",
        text:
          reason ||
          "Заявка не отправилась. Проверьте интернет и нажмите «Отправить заявку» ещё раз.",
      });
    }
  }

  return (
    <form
      ref={form}
      onSubmit={submit}
      noValidate
      className="relative flex flex-col gap-4 rounded-2xl bg-paper p-5 text-ink shadow-[0_24px_56px_-24px_rgb(19_32_59/0.28)] sm:p-9"
    >
      <label className="flex flex-col gap-1.5 text-[0.9375rem] font-semibold">
        Как вас зовут
        <input
          name="name"
          autoComplete="name"
          maxLength={100}
          required
          aria-invalid={invalid.name || undefined}
          className={cn(FIELD, "font-normal")}
        />
      </label>
      <label className="flex flex-col gap-1.5 text-[0.9375rem] font-semibold">
        Телефон, Telegram или почта
        <input
          name="contact"
          autoComplete="tel"
          maxLength={200}
          required
          aria-invalid={invalid.contact || undefined}
          className={cn(FIELD, "font-normal")}
        />
        <span className="text-[0.8125rem] font-normal text-steel">
          Напишем или позвоним туда, куда вам удобнее.
        </span>
      </label>
      <label className="flex flex-col gap-1.5 text-[0.9375rem] font-semibold">
        <span>
          Компания <span className="font-normal text-steel">необязательно</span>
        </span>
        <input
          name="company"
          autoComplete="organization"
          maxLength={150}
          className={cn(FIELD, "font-normal")}
        />
      </label>
      <label className="flex flex-col gap-1.5 text-[0.9375rem] font-semibold">
        <span>
          Что нужно автоматизировать <span className="font-normal text-steel">необязательно</span>
        </span>
        <textarea
          name="task"
          rows={4}
          maxLength={3000}
          className={cn(FIELD, "min-h-28 resize-y py-3 font-normal")}
        />
      </label>
      {/* Ловушка для роботов: человек это поле не видит и не заполняет. */}
      <label aria-hidden className="absolute -left-[200vw] size-px overflow-hidden">
        Не заполняйте это поле
        <input name="website" tabIndex={-1} autoComplete="off" />
      </label>
      <button
        type="submit"
        disabled={status.kind === "sending"}
        className="min-h-12 rounded-full bg-ink px-6 font-semibold text-paper transition-colors hover:bg-[#0c1730] focus-visible:outline-sky-deep disabled:cursor-progress disabled:opacity-60"
      >
        Отправить заявку
      </button>
      <p
        role="status"
        aria-live="polite"
        className={cn(
          "min-h-6 font-semibold",
          status.kind === "ok" && "text-[#0a7a4d]",
          status.kind === "error" && "text-alert",
        )}
      >
        {status.text}
      </p>
      <p className="text-[0.8125rem] text-steel">
        Нажимая «Отправить заявку», вы соглашаетесь на обработку контактных данных для ответа на
        заявку.
      </p>
    </form>
  );
}
