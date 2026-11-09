import { Globe, MessageCircle, Send, type LucideIcon } from "lucide-react";
import type { Metadata } from "next";
import Link from "next/link";

import { DemoButton } from "@/components/auth/demo-button";
import { Bento } from "@/components/landing/bento";
import { ConnectCode } from "@/components/landing/connect-code";
import { Reveal, RotatingWords, Starfield, StickyNav, Tilt } from "@/components/landing/effects";
import { LiveChat } from "@/components/landing/live-chat";
import { Wordmark } from "@/components/shell/wordmark";
import { buttonVariants } from "@/components/ui/button";
import { cn } from "@/lib/utils";

export const metadata: Metadata = {
  title: { absolute: "Satushy — бот-продавец для магазинов Казахстана" },
};

const QUESTIONS_A = [
  "Ақ пион бар ма?",
  "Сколько стоит доставка по Алматы?",
  "51 раушан қанша тұрады?",
  "Есть розовые пионы до 35 000?",
  "Kaspi Red арқылы бола ма?",
  "Можно забрать самовывозом?",
  "Ертеңге жеткізесіздер ме?",
  "Что подарить маме до 25 тысяч?",
];

const QUESTIONS_B = [
  "Салем, керек букет невесты",
  "Есть в наличии размер 42?",
  "Масло 5W-30 на Camry бар ма?",
  "Сегодня до 20:00 успеете?",
  "Қай уақытқа дейін жұмыс істейсіздер?",
  "Можно оплатить при получении?",
  "Гортензия бар ма?",
  "Скиньте фото, пожалуйста",
];

const CHANNELS: [LucideIcon, string][] = [
  [MessageCircle, "WhatsApp"],
  [Send, "Telegram"],
  [MessageCircle, "Instagram"],
  [Globe, "на сайте"],
];

const NIGHT = [
  {
    time: "23:41",
    channel: "Instagram",
    text: "Покупательница спрашивает белые пионы на завтра. Бот находит букет, называет цену и остаток, присылает карточку.",
  },
  {
    time: "00:15",
    channel: "WhatsApp",
    text: "Голосовое на казахском: «51 раушан қанша?» Бот расшифровывает и отвечает на казахском.",
  },
  {
    time: "01:30",
    channel: "Telegram",
    text: "Вопрос про доставку в Каскелен. Ответа в базе нет — бот не выдумывает, обещает уточнить и записывает вопрос.",
  },
  {
    time: "07:00",
    channel: "Кабинет",
    text: "Утром у вас две заявки с адресом и временем, один покупатель ждёт менеджера и один новый вопрос для базы знаний.",
  },
];

const STEPS = [
  ["Загрузите каталог", "Excel, CSV или Google Таблица — колонки бот найдёт сам."],
  ["Расскажите о магазине", "Доставка, оплата, часы работы и тон общения."],
  ["Проверьте в песочнице", "Автотест задаст 20 вопросов по вашему каталогу."],
  ["Подключите каналы", "Telegram, WhatsApp или окно чата на сайте."],
  ["Пополните баланс", "Счёт для ТОО и ИП прямо из кабинета."],
];

const PRICE = [
  ["Ответ бота", "несколько тенге, цена видна у каждого сообщения"],
  ["Песочница и автотест", "бесплатно"],
  ["Ответы менеджера", "бесплатно"],
  ["Пополнение", "по счёту для ТОО и ИП"],
  ["Предупреждения", "когда остаётся 20% и 5% баланса"],
];

const FAQ = [
  {
    q: "Бот может ошибиться в цене?",
    a: "Цены и остатки бот берёт только из вашего каталога. Каждую сумму в ответе Satushy сверяет с каталогом перед отправкой. Не совпала — ответ не уйдёт: бот переформулирует его или передаст диалог менеджеру.",
  },
  {
    q: "Что будет, если бот не знает ответа?",
    a: "Он честно скажет, что уточнит, и позовёт менеджера. Вопрос появится на странице «Обзор» — ответите один раз, и в следующий раз бот ответит сам.",
  },
  {
    q: "Нужен программист?",
    a: "Нет. Нужна таблица с товарами и доступ к каналу: токен Telegram-бота или номер WhatsApp Business. Мастер настройки проведёт по шагам.",
  },
  {
    q: "Можно вмешаться в разговор?",
    a: "Да. В «Диалогах» видно все переписки в реальном времени. Кнопка «Перехватить» останавливает бота, вы пишете сами и затем возвращаете диалог боту.",
  },
  {
    q: "Как устроена оплата?",
    a: "Абонентской платы нет. Вы пополняете баланс, с него списывается каждый ответ бота — обычно несколько тенге. Песочница и шаблонные ответы бесплатны.",
  },
  {
    q: "Кто видит переписки моих покупателей?",
    a: "Только сотрудники вашего магазина. Данные каждого магазина изолированы на уровне базы данных, ключи каналов хранятся в зашифрованном виде.",
  },
];

function Nav() {
  return (
    <StickyNav>
      <header className="mx-auto flex w-full max-w-6xl items-center justify-between gap-4 px-4 py-3 sm:px-8">
        <Link href="/" aria-label="Satushy, на главную">
          <Wordmark tone="paper" />
        </Link>
        <nav
          aria-label="Разделы страницы"
          className="hidden items-center gap-1 rounded-full border border-white/10 bg-white/[0.04] p-1 text-sm text-paper/70 backdrop-blur md:flex"
        >
          {[
            ["#night", "Как работает"],
            ["#skills", "Возможности"],
            ["#start", "Подключение"],
            ["#price", "Оплата"],
          ].map(([href, label]) => (
            <a
              key={href}
              href={href}
              className="rounded-full px-3.5 py-1.5 transition-colors hover:bg-white/10 hover:text-paper"
            >
              {label}
            </a>
          ))}
        </nav>
        <div className="flex items-center gap-2">
          <Link
            href="/login"
            className="flex min-h-11 items-center rounded-md px-3 text-sm font-semibold text-paper/80 hover:text-paper"
          >
            Войти
          </Link>
          <Link href="/signup" className={cn(buttonVariants({ variant: "glow" }), "max-sm:hidden")}>
            Подключить магазин
          </Link>
        </div>
      </header>
    </StickyNav>
  );
}

function Sky() {
  return (
    <div aria-hidden className="pointer-events-none absolute inset-0 overflow-hidden">
      <div className="absolute inset-0 grid-lines" />
      <div className="aurora top-[-20%] left-[-10%] h-[38rem] w-[38rem] animate-aurora-a bg-sky/40" />
      <div className="aurora top-[5%] right-[-15%] h-[34rem] w-[40rem] animate-aurora-b bg-teal/25" />
      <div className="aurora bottom-[-35%] left-[30%] h-[30rem] w-[44rem] animate-aurora-a bg-[#3b5bff]/25 [animation-delay:-8s]" />
      <Starfield className="absolute inset-0 h-full w-full" />
      <div className="absolute bottom-[-26rem] left-1/2 h-[40rem] w-[70rem] animate-[sunrise_9s_ease-in-out_infinite] rounded-full bg-[radial-gradient(closest-side,rgb(255_198_41/0.5),rgb(255_159_67/0.18)_45%,transparent_70%)] blur-2xl" />
      <div className="grain absolute inset-0" />
    </div>
  );
}

function Hero() {
  return (
    <div className="relative overflow-hidden">
      <Sky />
      <div className="relative mx-auto grid w-full max-w-6xl grid-cols-1 items-center gap-12 px-4 pt-32 pb-20 sm:px-8 lg:grid-cols-[minmax(0,1.1fr)_minmax(0,0.9fr)] lg:pt-40 lg:pb-28">
        <div className="max-w-xl">
          <a
            href="#night"
            className="inline-flex items-center gap-2 rounded-full border border-white/15 bg-white/[0.06] py-1 pr-3.5 pl-1 text-sm text-paper/80 backdrop-blur transition-colors hover:border-glow/50"
          >
            <span className="rounded-full bg-gradient-to-r from-glow to-sky px-2 py-0.5 text-xs font-semibold text-ink">
              ru + kk
            </span>
            Отвечает на языке покупателя
          </a>
          <h1 className="mt-6 text-[2.75rem] leading-[1] text-paper sm:text-[4.25rem] lg:text-[4.75rem]">
            <span className="text-shine">Сатушы, который</span>
            <br />
            <RotatingWords
              words={["не спит", "знает весь каталог", "говорит по-казахски", "не врёт о ценах"]}
              className="text-sky-gradient pb-2"
              boxClassName="block min-h-[2em]"
            />
          </h1>
          <p className="mt-6 max-w-lg text-lg text-paper/65">
            AI-продавец знает каждый товар вашего магазина и отвечает покупателям в WhatsApp,
            Instagram, Telegram и на сайте. Цены и остатки — только из вашей таблицы.
          </p>
          <div className="mt-9 flex flex-wrap items-start gap-3">
            <DemoButton variant="glow" className="min-h-12 px-6 text-base" hideWhenOff={false}>
              Открыть демо-кабинет
            </DemoButton>
            <Link
              href="/signup"
              className={cn(buttonVariants({ variant: "glass" }), "min-h-12 px-6 text-base")}
            >
              Подключить свой магазин
            </Link>
          </div>
          <div className="mt-10 flex flex-wrap items-center gap-x-6 gap-y-3 text-sm text-paper/45">
            <span>Работает в</span>
            {CHANNELS.map(([Icon, name]) => (
              <span key={name} className="flex items-center gap-1.5 text-paper/70">
                <Icon className="size-4" aria-hidden />
                {name}
              </span>
            ))}
          </div>
        </div>
        <div className="relative">
          <p className="mb-4 flex items-center justify-center gap-2 text-sm text-paper/60 lg:justify-end">
            <span className="relative flex size-2">
              <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-teal opacity-75" />
              <span className="relative inline-flex size-2 rounded-full bg-teal" />
            </span>
            Это настоящий бот демо-магазина — спросите его
          </p>
          <Tilt className="lg:ml-auto lg:max-w-md">
            <LiveChat className="w-full" />
          </Tilt>
        </div>
      </div>
    </div>
  );
}

function Ticker({ items, reverse }: { items: string[]; reverse?: boolean }) {
  return (
    <div className="flex overflow-hidden [mask-image:linear-gradient(90deg,transparent,#000_10%,#000_90%,transparent)]">
      <ul
        className={cn(
          "flex shrink-0 animate-marquee gap-3 pr-3",
          reverse && "[animation-direction:reverse]",
        )}
      >
        {[...items, ...items].map((item, index) => (
          <li
            key={index}
            aria-hidden={index >= items.length || undefined}
            className="shrink-0 rounded-full border border-white/10 bg-white/[0.04] px-4 py-2 text-sm whitespace-nowrap text-paper/75"
          >
            {item}
          </li>
        ))}
      </ul>
    </div>
  );
}

function Questions() {
  return (
    <section aria-label="Вопросы покупателей" className="border-y border-white/[0.06] py-10">
      <p className="mb-6 px-4 text-center text-sm text-paper/45">
        Так пишут покупатели. Бот понимает всё — с ошибками, сокращениями и на двух языках.
      </p>
      <div className="flex flex-col gap-3">
        <Ticker items={QUESTIONS_A} />
        <Ticker items={QUESTIONS_B} reverse />
      </div>
    </section>
  );
}

function SectionTitle({ title, text }: { title: string; text?: string }) {
  return (
    <Reveal className="max-w-2xl">
      <h2 className="text-[2rem] leading-tight text-paper sm:text-[3rem]">{title}</h2>
      {text && <p className="mt-4 text-lg text-paper/60">{text}</p>}
    </Reveal>
  );
}

function Night() {
  return (
    <section
      id="night"
      className="mx-auto w-full max-w-6xl scroll-mt-20 px-4 py-24 sm:px-8 lg:py-32"
    >
      <div className="grid grid-cols-1 gap-14 lg:grid-cols-[minmax(0,0.85fr)_minmax(0,1.15fr)]">
        <div className="lg:sticky lg:top-28 lg:self-start">
          <SectionTitle
            title="Пока магазин закрыт"
            text="Покупатель пишет сразу в три магазина и покупает там, где ответили первым. Обычно это вечер, когда менеджер уже дома."
          />
        </div>
        <ol className="relative flex flex-col gap-4">
          <span
            aria-hidden
            className="absolute top-3 bottom-3 left-[1.15rem] w-px bg-gradient-to-b from-glow via-sky/40 to-sun/60"
          />
          {NIGHT.map((item, index) => (
            <Reveal as="li" key={item.time} delay={index * 120} className="relative pl-12">
              <span className="absolute top-5 left-[0.65rem] size-4 rounded-full border-2 border-glow bg-night shadow-[0_0_16px_var(--glow)]" />
              <div className="rounded-xl border border-white/10 bg-white/[0.03] p-5 transition-colors hover:border-white/20 hover:bg-white/[0.05]">
                <p className="flex items-baseline gap-3">
                  <span className="display text-2xl text-paper tnum">{item.time}</span>
                  <span className="rounded-full bg-glow/10 px-2 py-0.5 text-xs font-medium text-glow">
                    {item.channel}
                  </span>
                </p>
                <p className="mt-2 text-paper/65">{item.text}</p>
              </div>
            </Reveal>
          ))}
        </ol>
      </div>
    </section>
  );
}

function Skills() {
  return (
    <section id="skills" className="relative scroll-mt-20 overflow-hidden py-24 lg:py-32">
      <div
        aria-hidden
        className="aurora top-40 left-1/2 h-[30rem] w-[50rem] -translate-x-1/2 bg-sky/15"
      />
      <div className="relative mx-auto w-full max-w-6xl px-4 sm:px-8">
        <SectionTitle
          title="Продавец, которого не нужно учить дважды"
          text="Наведите курсор на карточки — каждая показывает, как это работает."
        />
        <div className="mt-14">
          <Bento />
        </div>
      </div>
    </section>
  );
}

function Start() {
  return (
    <section
      id="start"
      className="mx-auto w-full max-w-6xl scroll-mt-20 px-4 py-24 sm:px-8 lg:py-32"
    >
      <div className="grid grid-cols-1 items-start gap-14 lg:grid-cols-2">
        <div>
          <SectionTitle
            title="Подключение за один день"
            text="Без программиста. Мастер проведёт по пяти шагам, прерваться можно в любой момент."
          />
          <ol className="mt-10 flex flex-col gap-6">
            {STEPS.map(([title, text], index) => (
              <Reveal as="li" key={title} delay={index * 90} className="flex gap-4">
                <span className="display flex size-11 shrink-0 items-center justify-center rounded-lg border border-glow/30 bg-glow/10 text-lg text-glow tnum shadow-[0_0_24px_-6px_var(--glow)]">
                  {index + 1}
                </span>
                <div>
                  <h3 className="text-lg text-paper">{title}</h3>
                  <p className="mt-1 text-paper/60">{text}</p>
                </div>
              </Reveal>
            ))}
          </ol>
        </div>
        <Reveal delay={150} className="min-w-0 lg:sticky lg:top-28">
          <ConnectCode />
          <p className="mt-4 text-sm text-paper/50">
            Для сайта — одна строка кода, для Telegram — токен бота. Остальное Satushy настроит сам.
          </p>
        </Reveal>
      </div>
    </section>
  );
}

function Price() {
  return (
    <section
      id="price"
      className="mx-auto w-full max-w-6xl scroll-mt-20 px-4 py-24 sm:px-8 lg:py-32"
    >
      <div className="grid grid-cols-1 items-center gap-12 lg:grid-cols-2">
        <SectionTitle
          title="Платите за ответы, а не за подписку"
          text="Пополняете баланс в тенге — с него списываются только ответы бота покупателям."
        />
        <Reveal delay={120}>
          <div className="glow-border rounded-xl">
            <div className="rounded-xl bg-night-2 p-6 sm:p-8">
              <p className="text-paper/60">Абонентская плата</p>
              <p className="display mt-1 text-[4rem] leading-none text-paper">
                0&nbsp;<span className="text-sky-gradient">₸</span>
              </p>
              <ul className="mt-8 divide-y divide-white/10">
                {PRICE.map(([name, value]) => (
                  <li key={name} className="flex flex-wrap justify-between gap-x-6 gap-y-1 py-3">
                    <span className="font-medium text-paper">{name}</span>
                    <span className="text-paper/60">{value}</span>
                  </li>
                ))}
              </ul>
            </div>
          </div>
        </Reveal>
      </div>
    </section>
  );
}

function Faq() {
  return (
    <section className="mx-auto grid w-full max-w-6xl grid-cols-1 gap-10 px-4 py-24 sm:px-8 lg:grid-cols-[minmax(0,0.7fr)_minmax(0,1.3fr)] lg:py-32">
      <SectionTitle title="Частые вопросы" />
      <Reveal className="flex flex-col gap-3">
        {FAQ.map((item) => (
          <details
            key={item.q}
            className="group rounded-xl border border-white/10 bg-white/[0.03] px-5 transition-colors open:border-glow/40 open:bg-white/[0.05]"
          >
            <summary className="flex min-h-16 list-none items-center justify-between gap-4 text-lg font-medium text-paper [&::-webkit-details-marker]:hidden">
              {item.q}
              <span
                aria-hidden
                className="flex size-8 shrink-0 items-center justify-center rounded-full border border-white/15 text-xl text-glow transition-transform duration-300 group-open:rotate-45"
              >
                +
              </span>
            </summary>
            <p className="max-w-2xl pb-5 text-paper/65">{item.a}</p>
          </details>
        ))}
      </Reveal>
    </section>
  );
}

function Final() {
  return (
    <section className="px-4 pb-16 sm:px-8">
      <div className="relative mx-auto max-w-6xl overflow-hidden rounded-2xl border border-white/10 bg-night-2 px-6 py-20 text-center sm:px-14 sm:py-28">
        <div
          aria-hidden
          className="absolute inset-0 grid-lines [mask-image:radial-gradient(ellipse_at_50%_100%,#000,transparent_70%)]"
        />
        <div
          aria-hidden
          className="absolute bottom-[-18rem] left-1/2 h-[28rem] w-[50rem] animate-[sunrise_7s_ease-in-out_infinite] rounded-full bg-[radial-gradient(closest-side,rgb(255_198_41/0.7),rgb(255_159_67/0.25)_45%,transparent_70%)] blur-xl"
        />
        <div aria-hidden className="grain absolute inset-0" />
        <Reveal className="relative mx-auto max-w-2xl">
          <h2 className="text-[2.25rem] leading-tight text-paper sm:text-[3.5rem]">
            Пусть первым ответит ваш магазин
          </h2>
          <p className="mt-4 text-lg text-paper/65">
            В демо-кабинете уже есть две недели диалогов, заявки и аналитика. Перехватите диалог,
            поговорите с ботом в песочнице, загляните в баланс.
          </p>
          <div className="mt-9 flex flex-wrap items-start justify-center gap-3">
            <DemoButton variant="glow" className="min-h-12 px-6 text-base" hideWhenOff={false}>
              Открыть демо-кабинет
            </DemoButton>
            <Link
              href="/signup"
              className={cn(buttonVariants({ variant: "glass" }), "min-h-12 px-6 text-base")}
            >
              Зарегистрировать магазин
            </Link>
          </div>
        </Reveal>
      </div>
    </section>
  );
}

export default function Landing() {
  return (
    <div className="on-ink min-h-svh overflow-x-clip bg-night text-paper">
      <a
        href="#main"
        className="absolute top-2 left-2 z-50 -translate-y-20 rounded-md bg-paper px-3 py-2 text-sm text-ink focus:translate-y-0"
      >
        Перейти к содержимому
      </a>
      <Nav />
      <Hero />
      <main id="main">
        <Questions />
        <Night />
        <Skills />
        <Start />
        <Price />
        <Faq />
        <Final />
      </main>
      <footer className="mx-auto flex w-full max-w-6xl flex-wrap items-center justify-between gap-4 border-t border-white/[0.06] px-4 pt-8 pb-10 text-sm text-paper/50 sm:px-8">
        <Wordmark tone="paper" className="text-lg" />
        <p>Бот-продавец для магазинов Казахстана. © 2026 Satushy</p>
        <Link href="/login" className="font-medium text-paper underline underline-offset-2">
          Войти в кабинет
        </Link>
      </footer>
    </div>
  );
}
