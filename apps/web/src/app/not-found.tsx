import Link from "next/link";

import { Wordmark } from "@/components/shell/wordmark";
import { buttonVariants } from "@/components/ui/button";

export default function NotFound() {
  return (
    <main className="flex min-h-svh flex-col px-4 py-6 sm:px-10 sm:py-10">
      <Wordmark />
      <div className="my-auto max-w-md py-10">
        <h1 className="text-2xl">Такой страницы нет</h1>
        <p className="mt-1.5 mb-5 text-steel">
          Возможно, ссылка устарела. Откройте кабинет и найдите нужный раздел в меню.
        </p>
        <Link href="/overview" className={buttonVariants()}>
          Открыть кабинет
        </Link>
      </div>
    </main>
  );
}
