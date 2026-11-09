import {
  BookOpenCheck,
  ClipboardList,
  Globe,
  Headset,
  Languages,
  MessageCircle,
  Mic,
  Send,
  ShieldCheck,
} from "lucide-react";
import type { Metadata } from "next";
import Link from "next/link";

import { DemoButton } from "@/components/auth/demo-button";
import { LiveChat } from "@/components/landing/live-chat";
import { Wordmark } from "@/components/shell/wordmark";
import { buttonVariants } from "@/components/ui/button";
import { cn } from "@/lib/utils";

export const metadata: Metadata = {
  title: { absolute: "Satushy — бот-продавец для магазинов Казахстана" },
};

const NIGHT = [
  {
    time: "23:41",
    channel: "Instagram",
    text: "Покупательница спрашивает белые пионы на завтра. Бот находит букет в каталоге, называет цену и остаток, присылает карточку.",
  },
  {
    time: "00:15",
    channel: "WhatsApp",
    text: "Голосовое на казахском: «51 раушан қанша?» Бот расшифровывает и отвечает на казахском.",
  },
  {
    time: "01:30",
    channel: "Telegram",
    text: "Вопрос про доставку в Каскелен. В базе знаний ответа нет, поэтому бот не выдумывает, а обещает уточнить и записывает вопрос.",
  },
  {
    time: "07:00",
    channel: "Кабинет",
    text: "Вы открываете телефон: две заявки с адресом и временем, один покупатель ждёт менеджера, один вопрос, на который стоит ответить один раз.",
  },
];

const SKILLS = [
  {
    icon: Languages,
    title: "Говорит как ваш покупатель",
    text: "Казахский, русский и их смесь в одном сообщении. Отвечает на языке, на котором спросили.",
  },
  {
    icon: Mic,
    title: "Слушает голосовые",
    text: "Расшифровывает голосовые сообщения, в том числе на казахском, и отвечает текстом.",
  },
  {
    icon: ClipboardList,
    title: "Собирает заявку",
    text: "Товар, адрес, время и телефон — заявка сразу появляется в кабинете и приходит менеджеру в Telegram.",
  },
  {
    icon: Headset,
    title: "Зовёт человека вовремя",
    text: "Индивидуальный заказ, жалоба или просьба позвать менеджера — диалог переходит к вам, бот молчит.",
  },
  {
    icon: BookOpenCheck,
    title: "Учится на пропущенных вопросах",
    text: "Всё, на что бот не ответил, собирается в одном списке. Ответили один раз — бот запомнил.",
  },
];

const CHANNELS = [
  { icon: MessageCircle, name: "WhatsApp", note: "через WhatsApp Business" },
  { icon: Send, name: "Telegram", note: "ваш бот из @BotFather" },
  { icon: Globe, name: "Сайт", note: "окно чата одной строкой кода" },
  { icon: MessageCircle, name: "Instagram", note: "после проверки Meta" },
];

const STEPS = [
  {
    title: "Загрузите каталог",
    text: "Excel, CSV или ссылка на Google Таблицу. Колонки с ценой, остатком и названием бот найдёт сам.",
  },
  {
    title: "Расскажите о магазине",
    text: "Доставка, оплата, часы работы и тон общения: на «вы», тепло, коротко.",
  },
  {
    title: "Проверьте в песочнице",
    text: "Поговорите с ботом сами или запустите автотест: он задаст 20 вопросов по вашему каталогу.",
  },
  {
    title: "Подключите каналы",
    text: "Telegram, WhatsApp или окно чата на сайте. Покупателям ничего устанавливать не нужно.",
  },
  {
    title: "Пополните баланс",
    text: "Счёт на оплату для ТОО и ИП прямо из кабинета. Бот начинает отвечать.",
  },
];

const FAQ = [
  {
    q: "Бот может ошибиться в цене?",
    a: "Цены и остатки бот берёт только из вашего каталога. Каждую сумму в ответе Satushy сверяет с каталогом перед отправкой. Если сумма не совпала, ответ не уйдёт: бот переформулирует его или передаст диалог менеджеру.",
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
    a: "Да. В разделе «Диалоги» видно все переписки в реальном времени. Кнопка «Перехватить» останавливает бота, вы пишете сами, затем возвращаете диалог боту.",
  },
  {
    q: "Как устроена оплата?",
    a: "Абонентской платы нет. Вы пополняете баланс, и с него списывается каждый ответ бота — обычно несколько тенге. Цена каждого ответа видна в диалоге. Песочница и шаблонные ответы бесплатны.",
  },
  {
    q: "Кто видит переписки моих покупателей?",
    a: "Только сотрудники вашего магазина. Данные каждого магазина изолированы на уровне базы данных, ключи каналов хранятся в зашифрованном виде.",
  },
];

function Nav() {
  return (
    <header className="relative z-10 mx-auto flex w-full max-w-6xl items-center justify-between gap-4 px-4 py-4 sm:px-8">
      <Link href="/" aria-label="Satushy, на главную">
        <Wordmark />
      </Link>
      <nav aria-label="Разделы страницы" className="hidden items-center gap-7 text-sm md:flex">
        <a href="#night" className="hover:underline hover:underline-offset-4">
          Как работает
        </a>
        <a href="#skills" className="hover:underline hover:underline-offset-4">
          Возможности
        </a>
        <a href="#start" className="hover:underline hover:underline-offset-4">
          Подключение
        </a>
        <a href="#price" className="hover:underline hover:underline-offset-4">
          Оплата
        </a>
      </nav>
      <div className="flex items-center gap-2">
        <Link
          href="/login"
          className="flex min-h-11 items-center rounded-md px-3 text-sm font-semibold hover:bg-ink/10"
        >
          Войти
        </Link>
        <Link href="/signup" className={cn(buttonVariants({ variant: "dark" }), "max-sm:hidden")}>
          Подключить магазин
        </Link>
      </div>
    </header>
  );
}

function Hero() {
  return (
    <div className="relative overflow-hidden rounded-b-2xl bg-sky">
      <div className="pointer-events-none absolute inset-0 ornament opacity-55" />
      <Nav />
      <div className="relative mx-auto grid w-full max-w-6xl items-center gap-10 px-4 pt-6 pb-14 sm:px-8 lg:grid-cols-[minmax(0,1.1fr)_minmax(0,0.9fr)] lg:pt-10 lg:pb-20">
        <div className="max-w-xl">
          <h1 className="text-[2.75rem] leading-[0.95] sm:text-[4.25rem] lg:text-[5rem]">
            Сатушы, который не&nbsp;спит
          </h1>
          <p className="mt-6 max-w-lg text-lg text-ink/85">
            Бот знает весь каталог вашего магазина и отвечает покупателям в WhatsApp, Instagram,
            Telegram и на сайте — по-казахски, по-русски и вперемешку. Цены и остатки берёт только
            из вашей таблицы.
          </p>
          <div className="mt-8 flex flex-wrap items-start gap-3">
            <DemoButton variant="dark" className="min-h-12 px-6 text-base" hideWhenOff={false}>
              Открыть демо-кабинет
            </DemoButton>
            <Link
              href="/signup"
              className={cn(
                buttonVariants({ variant: "secondary" }),
                "min-h-12 border-ink/20 bg-paper/70 px-6 text-base hover:bg-paper",
              )}
            >
              Подключить свой магазин
            </Link>
          </div>
          <p className="mt-6 max-w-md text-sm text-ink/75">
            <span className="lg:hidden">Ниже</span>
            <span className="max-lg:hidden">Справа</span> — настоящий бот демо-магазина «Цветы
            Пион». Спросите его о букете, как спросил бы покупатель.
          </p>
        </div>
        <LiveChat className="w-full lg:max-w-md lg:justify-self-end" />
      </div>
    </div>
  );
}

function Night() {
  return (
    <section
      id="night"
      className="mx-auto w-full max-w-6xl scroll-mt-6 px-4 py-20 sm:px-8 lg:py-28"
    >
      <div className="grid gap-12 lg:grid-cols-[minmax(0,0.8fr)_minmax(0,1.2fr)]">
        <div className="lg:sticky lg:top-10 lg:self-start">
          <h2 className="text-[2rem] leading-tight sm:text-[2.75rem]">Пока магазин закрыт</h2>
          <p className="mt-4 max-w-md text-lg text-steel">
            Покупатель пишет сразу в три магазина и покупает там, где ответили первым. Обычно это
            вечер, когда менеджер уже дома.
          </p>
        </div>
        <ol className="relative flex flex-col gap-0 border-l-2 border-sky pl-8">
          {NIGHT.map((item) => (
            <li key={item.time} className="relative pb-10 last:pb-0">
              <span className="absolute top-1.5 -left-[2.4rem] size-4 rounded-full border-2 border-sky bg-canvas" />
              <p className="flex items-baseline gap-3">
                <span className="display text-2xl tnum">{item.time}</span>
                <span className="text-sm font-medium text-sky-deep">{item.channel}</span>
              </p>
              <p className="mt-2 max-w-xl text-steel">{item.text}</p>
            </li>
          ))}
        </ol>
      </div>
    </section>
  );
}

function PriceCheck() {
  return (
    <div className="relative overflow-hidden rounded-xl bg-ink p-6 text-paper sm:p-8">
      <div className="pointer-events-none absolute inset-0 ornament opacity-50" />
      <div className="relative">
        <ShieldCheck className="size-8 text-sun" aria-hidden />
        <h3 className="mt-4 text-2xl sm:text-[2rem] sm:leading-tight">Не придумывает цены</h3>
        <p className="mt-3 max-w-md text-paper/80">
          Каждую сумму и артикул в ответе Satushy сверяет с каталогом до отправки. Не совпало —
          покупатель этот ответ не увидит.
        </p>
        <div className="mt-8 flex max-w-sm flex-col gap-2" aria-hidden>
          <p className="self-start rounded-xl rounded-bl-sm bg-paper px-4 py-2.5 text-ink">
            «Букет из 15 розовых пионов» — 32 000 ₸, в наличии 6 шт.
          </p>
          <p className="flex items-center gap-2 self-start rounded-full bg-sun px-3 py-1 text-sm font-medium text-ink">
            <ShieldCheck className="size-4" />
            32 000 ₸ совпадает с каталогом
          </p>
        </div>
      </div>
    </div>
  );
}

function Skills() {
  return (
    <section id="skills" className="bg-paper py-20 lg:py-28">
      <div className="mx-auto w-full max-w-6xl px-4 sm:px-8">
        <h2 className="max-w-2xl text-[2rem] leading-tight sm:text-[2.75rem]">
          Работает как лучший продавец, которого не нужно учить дважды
        </h2>
        <div className="mt-12 grid gap-10 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)] lg:gap-16">
          <PriceCheck />
          <ul className="flex flex-col divide-y divide-line">
            {SKILLS.map(({ icon: Icon, title, text }) => (
              <li key={title} className="flex gap-4 py-5 first:pt-0 last:pb-0">
                <Icon className="mt-0.5 size-6 shrink-0 text-sky-deep" aria-hidden />
                <div>
                  <h3 className="text-lg">{title}</h3>
                  <p className="mt-1 text-steel">{text}</p>
                </div>
              </li>
            ))}
          </ul>
        </div>
      </div>
    </section>
  );
}

function Channels() {
  return (
    <section className="mx-auto w-full max-w-6xl px-4 py-20 sm:px-8">
      <div className="flex flex-wrap items-end justify-between gap-6">
        <h2 className="max-w-lg text-[2rem] leading-tight sm:text-[2.75rem]">
          Там, где вам уже пишут
        </h2>
        <p className="max-w-sm text-steel">
          Все переписки из всех каналов — в одном окне кабинета, с пометкой, кто сейчас отвечает:
          бот или человек.
        </p>
      </div>
      <ul className="mt-10 grid grid-cols-2 gap-px overflow-hidden rounded-lg border border-line bg-line lg:grid-cols-4">
        {CHANNELS.map(({ icon: Icon, name, note }) => (
          <li key={name} className="flex flex-col gap-3 bg-paper p-5 sm:p-6">
            <Icon className="size-6 text-sky-deep" aria-hidden />
            <span className="display text-xl">{name}</span>
            <span className="text-sm text-steel">{note}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}

function Start() {
  return (
    <section id="start" className="scroll-mt-6 bg-ink py-20 text-paper lg:py-28">
      <div className="on-ink mx-auto w-full max-w-6xl px-4 sm:px-8">
        <div className="flex flex-wrap items-end justify-between gap-6">
          <h2 className="max-w-xl text-[2rem] leading-tight sm:text-[2.75rem]">
            Подключение за один день, без программиста
          </h2>
          <Link href="/signup" className={buttonVariants({ variant: "onInk" })}>
            Начать настройку
          </Link>
        </div>
        <ol className="mt-12 grid gap-8 sm:grid-cols-2 lg:grid-cols-5 lg:gap-6">
          {STEPS.map((step, index) => (
            <li key={step.title} className="border-t-2 border-sky pt-4">
              <span className="display text-4xl text-sky tnum">{index + 1}</span>
              <h3 className="mt-3 text-lg">{step.title}</h3>
              <p className="mt-2 text-sm text-paper/75">{step.text}</p>
            </li>
          ))}
        </ol>
      </div>
    </section>
  );
}

function Price() {
  return (
    <section
      id="price"
      className="mx-auto w-full max-w-6xl scroll-mt-6 px-4 py-20 sm:px-8 lg:py-28"
    >
      <div className="grid gap-10 lg:grid-cols-2 lg:gap-16">
        <div>
          <h2 className="text-[2rem] leading-tight sm:text-[2.75rem]">
            Платите за ответы, а не за подписку
          </h2>
          <p className="mt-4 max-w-md text-lg text-steel">
            Нет абонентской платы и тарифов. Пополняете баланс в тенге — с него списываются только
            ответы бота покупателям.
          </p>
        </div>
        <ul className="flex flex-col divide-y divide-line panel p-0">
          {[
            ["Ответ бота", "несколько тенге, цена видна у каждого сообщения"],
            ["Песочница и автотест", "бесплатно"],
            ["Ответы менеджера", "бесплатно"],
            ["Пополнение", "по счёту для ТОО и ИП"],
            ["Предупреждения", "когда на балансе остаётся 20% и 5%"],
          ].map(([name, value]) => (
            <li
              key={name}
              className="flex flex-wrap justify-between gap-x-6 gap-y-1 px-5 py-4 sm:px-6"
            >
              <span className="font-medium">{name}</span>
              <span className="text-steel">{value}</span>
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}

function Questions() {
  return (
    <section className="bg-paper py-20 lg:py-28">
      <div className="mx-auto grid w-full max-w-6xl gap-10 px-4 sm:px-8 lg:grid-cols-[minmax(0,0.7fr)_minmax(0,1.3fr)]">
        <h2 className="text-[2rem] leading-tight sm:text-[2.75rem]">Частые вопросы</h2>
        <div className="divide-y divide-line border-y border-line">
          {FAQ.map((item) => (
            <details key={item.q} className="group py-1">
              <summary className="flex min-h-14 list-none items-center justify-between gap-4 text-lg font-medium [&::-webkit-details-marker]:hidden">
                {item.q}
                <span
                  aria-hidden
                  className="flex size-8 shrink-0 items-center justify-center rounded-full bg-sky-soft text-xl text-sky-deep transition-transform group-open:rotate-45"
                >
                  +
                </span>
              </summary>
              <p className="max-w-2xl pb-5 text-steel">{item.a}</p>
            </details>
          ))}
        </div>
      </div>
    </section>
  );
}

function Final() {
  return (
    <section className="px-4 py-16 sm:px-8">
      <div className="relative mx-auto max-w-6xl overflow-hidden rounded-2xl bg-sky px-6 py-14 sm:px-14 sm:py-20">
        <div className="pointer-events-none absolute inset-0 ornament opacity-55" />
        <div className="relative max-w-2xl">
          <h2 className="text-[2.25rem] leading-tight sm:text-[3.25rem]">
            Посмотрите кабинет изнутри
          </h2>
          <p className="mt-4 text-lg text-ink/85">
            В демо-магазине уже есть неделя диалогов, заявки и аналитика. Перехватите диалог,
            поговорите с ботом в песочнице, загляните в баланс.
          </p>
          <div className="mt-8 flex flex-wrap items-start gap-3">
            <DemoButton variant="dark" className="min-h-12 px-6 text-base" hideWhenOff={false}>
              Открыть демо-кабинет
            </DemoButton>
            <Link
              href="/signup"
              className={cn(
                buttonVariants({ variant: "secondary" }),
                "min-h-12 border-ink/20 bg-paper/70 px-6 text-base hover:bg-paper",
              )}
            >
              Зарегистрировать магазин
            </Link>
          </div>
        </div>
      </div>
    </section>
  );
}

export default function Landing() {
  return (
    <div className="min-h-svh bg-canvas">
      <a
        href="#main"
        className="absolute top-2 left-2 z-50 -translate-y-20 rounded-md bg-ink px-3 py-2 text-sm text-paper focus:translate-y-0"
      >
        Перейти к содержимому
      </a>
      <Hero />
      <main id="main">
        <Night />
        <Skills />
        <Channels />
        <Start />
        <Price />
        <Questions />
        <Final />
      </main>
      <footer className="mx-auto flex w-full max-w-6xl flex-wrap items-center justify-between gap-4 px-4 pt-4 pb-10 text-sm text-steel sm:px-8">
        <Wordmark className="text-lg" />
        <p>Бот-продавец для магазинов Казахстана. © 2026 Satushy</p>
        <Link href="/login" className="font-medium text-ink underline underline-offset-2">
          Войти в кабинет
        </Link>
      </footer>
    </div>
  );
}
