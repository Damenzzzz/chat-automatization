import Link from "next/link";

import { Reveal, Starfield } from "@/components/landing/effects";
import { Wordmark } from "@/components/shell/wordmark";

const exchange = [
  { from: "customer", text: "Сәлеметсіз бе! Ақ пион бар ма? Ертеңге керек", time: "23:41" },
  {
    from: "bot",
    text: "Иә, бар. «Букет из 25 белых пионов» — 52 000 ₸, 3 дана қалды. Ертең қай уақытқа жеткізейік?",
    time: "23:41",
  },
  { from: "customer", text: "Күндіз, Абай 10 мекенжайына", time: "23:42" },
  {
    from: "bot",
    text: "Жақсы, заявканы менеджерге бердім. Ол таңертең сізге жазады.",
    time: "23:42",
  },
] as const;

export default function AuthLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="grid min-h-svh bg-paper lg:grid-cols-[minmax(0,5fr)_minmax(0,6fr)]">
      <main className="flex flex-col px-4 py-6 sm:px-10 sm:py-10">
        <Link href="/" aria-label="Satushy, на главную" className="self-start">
          <Wordmark />
        </Link>
        <div className="flex flex-1 items-center py-10">
          <div className="w-full max-w-sm">{children}</div>
        </div>
      </main>
      <aside
        aria-hidden
        className="relative m-3 hidden flex-col justify-center overflow-hidden rounded-2xl bg-night px-14 lg:flex"
      >
        <div className="absolute inset-0 grid-lines" />
        <div className="aurora top-[-10rem] left-[-8rem] h-[28rem] w-[28rem] animate-aurora-a bg-sky/40" />
        <div className="aurora right-[-10rem] bottom-[-8rem] h-[26rem] w-[30rem] animate-aurora-b bg-sun/25" />
        <Starfield className="absolute inset-0 h-full w-full" />
        <div className="grain absolute inset-0" />
        <div className="relative flex max-w-md flex-col gap-3">
          {exchange.map((message, index) => (
            <Reveal
              key={message.text}
              delay={200 + index * 450}
              className={
                message.from === "customer"
                  ? "max-w-[85%] self-start rounded-xl rounded-bl-sm border border-white/10 bg-white/[0.08] px-4 py-2.5 text-paper backdrop-blur"
                  : "max-w-[85%] self-end rounded-xl rounded-br-sm bg-gradient-to-br from-glow to-sky px-4 py-2.5 text-ink"
              }
            >
              {message.text}
              <span className="ml-2 align-bottom text-xs tnum opacity-60">{message.time}</span>
            </Reveal>
          ))}
          <p className="display mt-10 text-2xl leading-snug text-paper">
            Ночью вы спите. Бот отвечает покупателям на их языке и оставляет вам заявки к утру.
          </p>
        </div>
      </aside>
    </div>
  );
}
