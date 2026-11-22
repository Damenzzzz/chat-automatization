"use client";

import { useId, useState } from "react";

import { Button } from "@/components/ui/button";
import { Notice } from "@/components/ui/notice";
import { api, type Schemas } from "@/lib/api/client";
import { errorText, unwrap } from "@/lib/api/errors";

type Product = Schemas["CatalogProduct"];

const field =
  "min-h-11 w-full min-w-0 rounded-md border border-control/70 bg-paper px-2.5 text-base text-ink tnum hover:border-ink focus-visible:border-sky-deep sm:min-h-10";

function toNumber(value: string): number | null {
  const digits = value.replace(/\s/g, "");
  return digits === "" ? null : Number(digits);
}

export function ProductEditor({
  product,
  onDone,
  onCancel,
}: {
  product: Product;
  onDone: () => void;
  onCancel: () => void;
}) {
  const id = useId();
  const [price, setPrice] = useState(product.price?.toString() ?? "");
  const [stock, setStock] = useState(product.stock?.toString() ?? "");
  const [busy, setBusy] = useState<"save" | "remove" | null>(null);
  const [error, setError] = useState<unknown>(null);

  async function send(body: Schemas["ProductPatch"], kind: "save" | "remove") {
    setBusy(kind);
    setError(null);
    try {
      await unwrap(
        api.PATCH("/products/{product_id}", {
          params: { path: { product_id: product.id } },
          body,
        }),
      );
      onDone();
    } catch (failure) {
      setError(failure);
      setBusy(null);
    }
  }

  return (
    <form
      onSubmit={(event) => {
        event.preventDefault();
        void send({ price: toNumber(price), stock: toNumber(stock) }, "save");
      }}
      className="flex flex-col gap-3 rounded-lg bg-mist p-3"
    >
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <label htmlFor={`${id}-price`} className="flex min-w-0 flex-col gap-1.5">
          <span className="text-sm font-medium">Цена, ₸</span>
          <input
            id={`${id}-price`}
            inputMode="numeric"
            pattern="[0-9 ]*"
            value={price}
            onChange={(event) => setPrice(event.target.value)}
            placeholder="Не указана"
            className={field}
          />
        </label>
        <label htmlFor={`${id}-stock`} className="flex min-w-0 flex-col gap-1.5">
          <span className="text-sm font-medium">Остаток, шт.</span>
          <input
            id={`${id}-stock`}
            inputMode="numeric"
            pattern="[0-9 ]*"
            value={stock}
            onChange={(event) => setStock(event.target.value)}
            placeholder="Не указан"
            className={field}
          />
        </label>
      </div>
      <p className="text-sm text-steel">
        Бот сразу начнёт называть новую цену и остаток. Пустое поле — «не указано».
      </p>
      {error ? <Notice kind="error">{errorText(error)}</Notice> : null}
      <div className="flex flex-wrap gap-2">
        <Button type="submit" loading={busy === "save"} disabled={busy !== null}>
          Сохранить
        </Button>
        <Button type="button" variant="ghost" disabled={busy !== null} onClick={onCancel}>
          Отмена
        </Button>
        <Button
          type="button"
          variant="danger"
          className="sm:ml-auto"
          loading={busy === "remove"}
          disabled={busy !== null}
          onClick={() => {
            if (
              window.confirm(
                `Снять «${product.name}» с продажи? Бот перестанет его предлагать. Вернуть товар можно новой загрузкой каталога.`,
              )
            ) {
              void send({ is_active: false }, "remove");
            }
          }}
        >
          Снять с продажи
        </Button>
      </div>
    </form>
  );
}
