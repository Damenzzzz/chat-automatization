import { Wordmark } from "@/components/shell/wordmark";

const exchange = [
  { from: "customer", text: "Сәлеметсіз бе! Ақ пион бар ма? Ертеңге керек" },
  { from: "bot", text: "Иә, бар. Ақ пион, 9 дана, 15 000 ₸. Ертең қай уақытқа жеткізейік?" },
  { from: "customer", text: "Күндіз, Абай 10 мекенжайына" },
  { from: "bot", text: "Жақсы, заявканы менеджерге бердім. Ол сізге жазады." },
] as const;

export default function AuthLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="grid min-h-svh lg:grid-cols-[minmax(0,5fr)_minmax(0,6fr)]">
      <main className="flex flex-col px-4 py-6 sm:px-10 sm:py-10">
        <Wordmark />
        <div className="flex flex-1 items-center py-10">
          <div className="w-full max-w-sm">{children}</div>
        </div>
      </main>
      <aside aria-hidden className="hidden flex-col justify-center bg-mist px-14 lg:flex">
        <div className="flex max-w-md flex-col gap-3">
          {exchange.map((message) => (
            <p
              key={message.text}
              className={
                message.from === "customer"
                  ? "max-w-[85%] self-start rounded-lg border border-line bg-paper px-4 py-2.5"
                  : "max-w-[85%] self-end rounded-lg bg-haze px-4 py-2.5"
              }
            >
              {message.text}
            </p>
          ))}
          <p className="display mt-8 text-xl text-steel">
            Пока вы заняты магазином, бот отвечает покупателям на их языке и зовёт вас, когда нужен
            человек.
          </p>
        </div>
      </aside>
    </div>
  );
}
