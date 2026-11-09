import { BookOpenCheck, ClipboardList, Headset, Languages, Mic, ShieldCheck } from "lucide-react";
import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

import { Reveal, RotatingWords, SpotlightGroup } from "./effects";

function Tile({
  icon: Icon,
  title,
  text,
  className,
  delay,
  children,
}: {
  icon: typeof ShieldCheck;
  title: string;
  text: string;
  className?: string;
  delay: number;
  children: ReactNode;
}) {
  return (
    <Reveal delay={delay} className={cn("flex", className)}>
      <article
        data-spotlight
        className="spotlight flex w-full min-w-0 flex-col overflow-hidden rounded-xl border border-white/10 bg-white/[0.03]"
      >
        <div
          aria-hidden
          className="relative flex min-h-44 flex-1 items-center justify-center overflow-hidden border-b border-white/[0.06] p-6"
        >
          {children}
        </div>
        <div className="p-6">
          <h3 className="flex items-center gap-2 text-lg text-paper">
            <Icon className="size-5 text-glow" aria-hidden />
            {title}
          </h3>
          <p className="mt-2 text-paper/60">{text}</p>
        </div>
      </article>
    </Reveal>
  );
}

function PriceDemo() {
  return (
    <div className="flex w-full max-w-md flex-col gap-3">
      <div className="relative overflow-hidden rounded-xl rounded-bl-sm border border-white/10 bg-white/[0.07] px-4 py-3 text-paper">
        «Букет из 15 розовых пионов» —{" "}
        <span className="rounded bg-glow/15 px-1 font-semibold text-glow">32&nbsp;000&nbsp;₸</span>,
        в наличии 6 шт.
        <span className="absolute inset-y-0 left-0 w-1/3 animate-[scan_3.2s_ease-in-out_infinite] bg-gradient-to-r from-transparent via-glow/25 to-transparent" />
      </div>
      <div className="flex flex-wrap gap-2">
        <span className="flex animate-[pop_3.2s_ease-out_infinite] items-center gap-1.5 rounded-full bg-teal/15 px-3 py-1 text-sm text-teal">
          <ShieldCheck className="size-4" />
          совпадает с каталогом
        </span>
        <span className="flex animate-[pop_3.2s_ease-out_infinite] items-center gap-1.5 rounded-full bg-sun/15 px-3 py-1 text-sm text-sun [animation-delay:200ms]">
          артикул PN-001 найден
        </span>
      </div>
    </div>
  );
}

function VoiceDemo() {
  return (
    <div className="flex flex-col items-center gap-4">
      <div className="flex h-12 items-center gap-1">
        {Array.from({ length: 22 }, (_, index) => (
          <span
            key={index}
            className="w-1 animate-[wave_1.1s_ease-in-out_infinite] rounded-full bg-gradient-to-t from-sky to-glow"
            style={{ height: `${30 + ((index * 37) % 70)}%`, animationDelay: `${index * 60}ms` }}
          />
        ))}
      </div>
      <p className="rounded-full border border-white/10 bg-white/5 px-3 py-1 text-sm text-paper/80">
        «51 раушан қанша?»
      </p>
    </div>
  );
}

function LeadDemo() {
  return (
    <div className="w-full max-w-xs animate-[slide-in_4s_ease-out_infinite] rounded-lg border border-white/10 bg-night-2 p-3 shadow-[0_20px_40px_-10px_rgb(0_0_0/0.6)]">
      <p className="flex items-center justify-between text-xs text-paper/50">
        <span className="flex items-center gap-1.5">
          <span className="size-1.5 rounded-full bg-sun shadow-[0_0_8px_var(--sun)]" />
          Новая заявка
        </span>
        <span>сейчас</span>
      </p>
      <p className="mt-2 font-medium text-paper">Пионы в шляпной коробке</p>
      <p className="mt-1 flex justify-between text-sm text-paper/60">
        <span>Мадина, Достык 5, к 19:00</span>
        <span className="text-sky-gradient font-semibold">45&nbsp;000&nbsp;₸</span>
      </p>
    </div>
  );
}

function HandoffDemo() {
  return (
    <div className="flex w-full max-w-xs flex-col gap-3">
      <p className="self-start rounded-xl rounded-bl-sm border border-white/10 bg-white/[0.07] px-3 py-2 text-sm text-paper">
        Нужно 40 букетов на свадьбу
      </p>
      <div className="flex items-center justify-between rounded-full border border-white/10 bg-white/5 p-1 text-sm">
        <span className="px-3 text-paper/50">Бот</span>
        <span className="rounded-full bg-sun px-3 py-1 font-semibold text-ink shadow-[0_0_20px_rgb(255_198_41/0.5)]">
          Менеджер
        </span>
      </div>
    </div>
  );
}

function LearnDemo() {
  const bars = [38, 52, 64, 47, 72, 58, 88, 66, 94, 80];
  return (
    <div className="flex w-full items-end gap-6">
      <div className="flex h-28 flex-1 items-end gap-1.5">
        {bars.map((height, index) => (
          <span
            key={index}
            className="flex-1 origin-bottom animate-[grow_1.4s_cubic-bezier(0.2,0.8,0.2,1)_both] rounded-t-sm bg-gradient-to-t from-sky/30 to-glow"
            style={{ height: `${height}%`, animationDelay: `${index * 70}ms` }}
          />
        ))}
      </div>
      <div className="hidden w-56 shrink-0 rounded-lg border border-white/10 bg-night-2 p-3 text-sm sm:block">
        <p className="text-paper/50">Бот не знал ответа</p>
        <p className="mt-1 text-paper">Доставка в Каскелен?</p>
        <p className="mt-2 flex items-center gap-1.5 text-teal">
          <BookOpenCheck className="size-4" />
          Ответили, бот запомнил
        </p>
      </div>
    </div>
  );
}

export function Bento() {
  return (
    <SpotlightGroup className="grid grid-cols-1 gap-4 lg:grid-cols-6">
      <Tile
        icon={ShieldCheck}
        title="Не придумывает цены"
        text="Каждую сумму и артикул в ответе Satushy сверяет с каталогом до отправки. Не совпало — покупатель ответ не увидит."
        className="lg:col-span-4"
        delay={0}
      >
        <PriceDemo />
      </Tile>
      <Tile
        icon={Languages}
        title="Говорит как покупатель"
        text="Казахский, русский и их смесь в одном сообщении."
        className="lg:col-span-2"
        delay={100}
      >
        <RotatingWords
          words={["Сәлеметсіз бе!", "Здравствуйте!", "Салем, привет!", "Қош келдіңіз!"]}
          className="display text-center text-[2rem] leading-tight text-paper"
        />
      </Tile>
      <Tile
        icon={Mic}
        title="Слушает голосовые"
        text="Расшифровывает голосовые, в том числе на казахском, и отвечает текстом."
        className="lg:col-span-2"
        delay={0}
      >
        <VoiceDemo />
      </Tile>
      <Tile
        icon={ClipboardList}
        title="Собирает заявку"
        text="Товар, адрес, время и телефон — в кабинете и у менеджера в Telegram."
        className="lg:col-span-2"
        delay={100}
      >
        <LeadDemo />
      </Tile>
      <Tile
        icon={Headset}
        title="Зовёт человека вовремя"
        text="Особый заказ или просьба позвать менеджера — диалог переходит к вам."
        className="lg:col-span-2"
        delay={200}
      >
        <HandoffDemo />
      </Tile>
      <Tile
        icon={BookOpenCheck}
        title="Учится на пропущенных вопросах"
        text="Всё, на что бот не ответил, — в одном списке. Ответили один раз, и бот запомнил. Аналитика по дням, запросам и заявкам."
        className="lg:col-span-6"
        delay={0}
      >
        <LearnDemo />
      </Tile>
    </SpotlightGroup>
  );
}
