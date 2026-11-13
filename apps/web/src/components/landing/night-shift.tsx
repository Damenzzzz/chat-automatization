"use client";

import { useEffect, useRef, useState } from "react";

import { cn } from "@/lib/utils";

/** Минуты от полуночи: 23:41 — это −19. */
const EVENTS = [
  {
    at: -19,
    channel: "Instagram",
    text: "Покупательница спрашивает белые пионы на завтра. Бот находит букет, называет цену и остаток, присылает карточку.",
  },
  {
    at: 15,
    channel: "WhatsApp",
    text: "Голосовое на казахском: «51 раушан қанша?» Бот расшифровывает и отвечает на казахском.",
  },
  {
    at: 90,
    channel: "Telegram",
    text: "Вопрос про доставку в Каскелен. Ответа в базе нет — бот не выдумывает, обещает уточнить и записывает вопрос.",
  },
  {
    at: 180,
    channel: "Заказы",
    text: "Заказы за день сверены с оплатами. Два расхождения выписаны в таблицу для бухгалтера.",
  },
  {
    at: 300,
    channel: "Накладные",
    text: "Фото накладных от поставщика распознаны, остатки в каталоге обновлены.",
  },
  {
    at: 420,
    channel: "Утро",
    text: "У вас две заявки с адресом и временем, один покупатель ждёт менеджера и один новый вопрос для базы знаний.",
  },
] as const;

const START = EVENTS[0].at;
const END = EVENTS[EVENTS.length - 1].at;
const STEP_MS = 1500;
const RUN_MS = 850;

function clockText(minutes: number): string {
  const total = ((Math.round(minutes) % 1440) + 1440) % 1440;
  return `${String(Math.floor(total / 60)).padStart(2, "0")}:${String(total % 60).padStart(2, "0")}`;
}

/**
 * Ночь магазина: часы идут от 23:41 до 07:00, события появляются по времени,
 * а небо секции светлеет к рассвету. Запускается, когда секция попала на экран.
 */
export function NightShift() {
  const section = useRef<HTMLElement>(null);
  const clock = useRef<HTMLParagraphElement>(null);
  // null — до загрузки скрипта журнал виден целиком (и без JavaScript тоже).
  const [shown, setShown] = useState<number | null>(null);
  const [done, setDone] = useState(false);
  const run = useRef({ timers: [] as number[], frame: 0 });

  function setTime(minutes: number) {
    if (clock.current) clock.current.textContent = clockText(minutes);
    const progress = Math.min(1, Math.max(0, (minutes - START) / (END - START)));
    // Светает ближе к утру, поэтому куб, а не прямая.
    section.current?.style.setProperty("--dawn", (progress ** 3).toFixed(3));
  }

  function stop() {
    run.current.timers.forEach((timer) => window.clearTimeout(timer));
    run.current.timers = [];
    window.cancelAnimationFrame(run.current.frame);
  }

  function play() {
    stop();
    setDone(false);
    setShown(0);
    setTime(START);
    EVENTS.forEach((event, index) => {
      const from = index === 0 ? START : EVENTS[index - 1].at;
      const timer = window.setTimeout(
        () => {
          const started = performance.now();
          const tick = (now: number) => {
            const t = Math.min(1, (now - started) / RUN_MS);
            setTime(from + (event.at - from) * (1 - (1 - t) ** 3));
            if (t < 1) {
              run.current.frame = window.requestAnimationFrame(tick);
            } else {
              setShown(index + 1);
              if (index === EVENTS.length - 1) setDone(true);
            }
          };
          run.current.frame = window.requestAnimationFrame(tick);
        },
        400 + index * STEP_MS,
      );
      run.current.timers.push(timer);
    });
  }

  useEffect(() => {
    const node = section.current;
    if (!node) return;
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      setTime(END);
      return;
    }
    // Первый вызов наблюдателя приходит сразу: прячем журнал. Когда секция
    // видна на пятую часть — запускаем ночь.
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (!entry) return;
        if (entry.isIntersecting && entry.intersectionRatio >= 0.2) {
          observer.disconnect();
          play();
        } else {
          setShown((value) => value ?? 0);
          setTime(START);
        }
      },
      { threshold: [0, 0.2] },
    );
    observer.observe(node);
    return () => {
      observer.disconnect();
      stop();
    };
    // play и stop работают только с ref-ами и сеттерами состояния
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <section
      ref={section}
      id="night"
      className="relative scroll-mt-20 overflow-hidden [--dawn:1]"
      aria-label="Ночь магазина после автоматизации"
    >
      <div aria-hidden className="pointer-events-none absolute inset-0">
        <div className="absolute inset-x-0 bottom-0 h-[70%] bg-[linear-gradient(180deg,transparent,rgb(74_79_134/0.3)_40%,rgb(190_110_140/0.34)_70%,rgb(255_150_80/0.42))] opacity-[var(--dawn)]" />
        <div className="absolute bottom-[-26rem] left-1/2 size-[46rem] -translate-x-1/2 translate-y-[calc((1-var(--dawn))*9rem)] rounded-full bg-[radial-gradient(closest-side,rgb(255_222_140/0.95),rgb(255_170_80/0.42)_48%,transparent_74%)] opacity-[var(--dawn)]" />
      </div>

      <div className="relative mx-auto grid w-full max-w-6xl grid-cols-1 gap-12 px-4 py-24 sm:px-8 lg:grid-cols-[minmax(0,0.85fr)_minmax(0,1.15fr)] lg:py-32">
        <div className="lg:sticky lg:top-28 lg:self-start">
          <h2 className="text-[2rem] leading-tight text-paper sm:text-[3rem]">
            Пока магазин закрыт
          </h2>
          <p className="mt-4 text-lg text-paper/60">
            Покупатель пишет сразу в три магазина и покупает там, где ответили первым. Обычно это
            вечер, когда менеджер уже дома. А ночью можно сделать и остальную рутину.
          </p>
          <p
            ref={clock}
            aria-hidden
            className="display mt-10 text-[4.5rem] leading-none [color:color-mix(in_srgb,var(--glow),var(--sun)_calc(var(--dawn)*100%))] tnum sm:text-[6.5rem]"
          >
            07:00
          </p>
          <button
            type="button"
            onClick={play}
            className={cn(
              "mt-4 min-h-11 text-sm text-paper/60 underline underline-offset-4 hover:text-paper",
              !done && "invisible",
            )}
          >
            Показать ночь ещё раз
          </button>
        </div>

        <ol className="relative flex flex-col gap-4">
          <span
            aria-hidden
            className="absolute top-3 bottom-3 left-[1.15rem] w-px bg-gradient-to-b from-glow via-sky/40 to-sun/60"
          />
          {EVENTS.map((event, index) => {
            const morning = index === EVENTS.length - 1;
            return (
              <li
                key={event.at}
                className={cn(
                  "relative pl-12 transition-[opacity,transform] duration-500",
                  shown !== null && index >= shown && "translate-y-2 opacity-0",
                )}
              >
                <span
                  className={cn(
                    "absolute top-5 left-[0.65rem] size-4 rounded-full border-2 bg-night",
                    morning
                      ? "border-sun shadow-[0_0_16px_var(--sun)]"
                      : "border-glow shadow-[0_0_16px_var(--glow)]",
                  )}
                />
                <div className="rounded-xl border border-white/10 bg-night-2/70 p-5 backdrop-blur transition-colors hover:border-white/20">
                  <p className="flex items-baseline gap-3">
                    <span className="display text-2xl text-paper tnum">{clockText(event.at)}</span>
                    <span
                      className={cn(
                        "rounded-full px-2 py-0.5 text-xs font-medium",
                        morning ? "bg-sun/15 text-sun" : "bg-glow/10 text-glow",
                      )}
                    >
                      {event.channel}
                    </span>
                  </p>
                  <p className="mt-2 text-paper/70">{event.text}</p>
                </div>
              </li>
            );
          })}
        </ol>
      </div>
    </section>
  );
}
