"use client";

import { Search } from "lucide-react";
import { useEffect, useState } from "react";
import useSWR from "swr";

import { CatalogImport } from "@/components/catalog/catalog-import";
import { Button } from "@/components/ui/button";
import { Empty, LoadError, Loading, Page, PageHeader } from "@/components/ui/page";
import { api, type Schemas } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";
import { count, money, plural } from "@/lib/format";

const PAGE_SIZE = 30;

function stockText(stock: number | null | undefined): string {
  if (stock === null || stock === undefined) return "Не указан";
  return stock > 0 ? count(stock) : "Нет в наличии";
}

function Row({ product }: { product: Schemas["CatalogProduct"] }) {
  return (
    <tr className="border-b border-line align-top max-md:block max-md:py-3">
      <th scope="row" className="py-3 pr-4 text-left font-medium max-md:block max-md:py-0">
        <span className="break-words">{product.name}</span>
        {!product.indexed && (
          <span className="mt-0.5 block text-xs font-normal text-steel">
            Бот скоро начнёт его находить
          </span>
        )}
      </th>
      <td className="py-3 pr-4 text-steel max-md:inline max-md:pr-3">{product.sku}</td>
      <td className="py-3 pr-4 text-steel max-md:inline">{product.category}</td>
      <td className="py-3 pr-4 text-right whitespace-nowrap tnum max-md:block max-md:py-0 max-md:text-left">
        {money(product.price)}
      </td>
      <td className="py-3 text-right whitespace-nowrap tnum max-md:block max-md:py-0 max-md:text-left max-md:text-steel">
        <span className="md:hidden">Остаток: </span>
        {stockText(product.stock)}
      </td>
    </tr>
  );
}

export function ProductsView() {
  const [input, setInput] = useState("");
  const [q, setQ] = useState("");
  const [offset, setOffset] = useState(0);
  const [importing, setImporting] = useState(false);

  useEffect(() => {
    const timer = setTimeout(() => {
      setQ(input.trim());
      setOffset(0);
    }, 300);
    return () => clearTimeout(timer);
  }, [input]);

  const { data, error, isLoading, mutate } = useSWR(`/products?q=${q}&offset=${offset}`, () =>
    unwrap(
      api.GET("/products", { params: { query: { q: q || undefined, offset, limit: PAGE_SIZE } } }),
    ),
  );
  const total = data?.total ?? 0;
  const noCatalog = data && total === 0 && !q;

  return (
    <Page>
      <PageHeader
        title="Товары"
        actions={
          <Button
            variant={importing ? "secondary" : "primary"}
            onClick={() => setImporting(!importing)}
          >
            {importing ? "Скрыть загрузку" : "Загрузить файл"}
          </Button>
        }
      >
        {data && total > 0
          ? `В каталоге ${count(total)} ${plural(total, "товар", "товара", "товаров")}. Бот отвечает только по ним.`
          : "Бот отвечает только по товарам из этого списка."}
      </PageHeader>
      {(importing || noCatalog) && (
        <section aria-label="Загрузка товаров" className="border-t border-line py-6">
          <CatalogImport onDone={() => void mutate()} />
        </section>
      )}
      {!noCatalog && (
        <div className="relative mb-2 max-w-md">
          <label htmlFor="product-search" className="sr-only">
            Поиск по названию или артикулу
          </label>
          <Search className="absolute top-3 left-3 size-4 text-steel" aria-hidden />
          <input
            id="product-search"
            type="search"
            value={input}
            onChange={(event) => setInput(event.target.value)}
            placeholder="Название или артикул"
            className="min-h-11 w-full rounded-md border border-control pr-3 pl-9 hover:border-ink sm:min-h-10"
          />
        </div>
      )}
      {isLoading && <Loading />}
      {error ? <LoadError error={error} retry={() => void mutate()} /> : null}
      {data && total === 0 && q && (
        <Empty title="Ничего не нашлось">Проверьте написание или поищите по артикулу.</Empty>
      )}
      {data && data.items.length > 0 && (
        <>
          <div className="overflow-hidden panel px-4 sm:px-5">
            <table className="w-full text-sm max-md:block">
              <caption className="sr-only">Товары каталога</caption>
              <thead className="text-left text-steel max-md:sr-only">
                <tr className="border-b border-line">
                  <th scope="col" className="py-2 pr-4 font-normal">
                    Название
                  </th>
                  <th scope="col" className="py-2 pr-4 font-normal">
                    Артикул
                  </th>
                  <th scope="col" className="py-2 pr-4 font-normal">
                    Категория
                  </th>
                  <th scope="col" className="py-2 pr-4 text-right font-normal">
                    Цена
                  </th>
                  <th scope="col" className="py-2 text-right font-normal">
                    Остаток
                  </th>
                </tr>
              </thead>
              <tbody className="max-md:block">
                {data.items.map((product) => (
                  <Row key={product.id} product={product} />
                ))}
              </tbody>
            </table>
          </div>
          {total > PAGE_SIZE && (
            <nav aria-label="Страницы каталога" className="mt-4 flex items-center gap-3">
              <Button
                variant="secondary"
                disabled={offset === 0}
                onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
              >
                Назад
              </Button>
              <p className="text-sm text-steel tnum">
                {count(offset + 1)}–{count(Math.min(offset + PAGE_SIZE, total))} из {count(total)}
              </p>
              <Button
                variant="secondary"
                disabled={offset + PAGE_SIZE >= total}
                onClick={() => setOffset(offset + PAGE_SIZE)}
              >
                Дальше
              </Button>
            </nav>
          )}
        </>
      )}
    </Page>
  );
}
