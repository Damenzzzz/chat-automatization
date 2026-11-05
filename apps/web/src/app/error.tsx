"use client";

import { Button } from "@/components/ui/button";

export default function ErrorPage({ reset }: { reset: () => void }) {
  return (
    <div className="flex min-h-[60svh] flex-col justify-center px-4 py-10 sm:px-8">
      <h1 className="text-2xl">Страница не открылась</h1>
      <p className="mt-1.5 mb-5 max-w-md text-steel">
        Ваши данные в порядке. Попробуйте открыть страницу ещё раз.
      </p>
      <div>
        <Button onClick={reset}>Попробовать снова</Button>
      </div>
    </div>
  );
}
