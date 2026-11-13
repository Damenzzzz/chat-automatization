"use client";

import { Search } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useRef, useState, type KeyboardEvent } from "react";
import useSWR from "swr";

import { customerName } from "@/components/dialogs/labels";
import { api } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";
import { money } from "@/lib/format";
import { cn } from "@/lib/utils";

import { useSession } from "./session";

const EVENT = "satushy:palette";
const MIN_QUERY = 2;

type Entry = { group: string; label: string; hint?: string; href: string };

const PAGES: (Entry & { ownerOnly?: boolean })[] = [
  { group: "Разделы", label: "Сегодня", href: "/overview" },
  { group: "Разделы", label: "Диалоги", href: "/dialogs" },
  { group: "Разделы", label: "Заявки", href: "/leads" },
  { group: "Разделы", label: "Товары", href: "/products" },
  { group: "Разделы", label: "Бот и песочница", href: "/bot" },
  { group: "Разделы", label: "Сервисы", href: "/services" },
  { group: "Разделы", label: "Каналы", href: "/channels", ownerOnly: true },
  { group: "Разделы", label: "Настройки", href: "/settings" },
  { group: "Действия", label: "Пополнить баланс", href: "/balance", ownerOnly: true },
  { group: "Действия", label: "Загрузить новый прайс", href: "/products?import=1" },
  { group: "Действия", label: "Диалоги, которые ждут ответа", href: "/dialogs?filter=human" },
  { group: "Действия", label: "Новые заявки", href: "/leads?status=new" },
  { group: "Действия", label: "Заявки, по которым пора напомнить", href: "/leads?due=1" },
  {
    group: "Действия",
    label: "Напоминания покупателям на одобрение",
    href: "/services?service=followup",
  },
];

export function openPalette() {
  window.dispatchEvent(new Event(EVENT));
}

export function CommandPalette() {
  const dialog = useRef<HTMLDialogElement>(null);
  const router = useRouter();
  const { isOwner } = useSession();
  const [open, setOpen] = useState(false);
  const [input, setInput] = useState("");
  const [q, setQ] = useState("");
  const [active, setActive] = useState(0);

  useEffect(() => {
    const show = () => {
      setInput("");
      setQ("");
      setActive(0);
      setOpen(true);
      if (!dialog.current?.open) dialog.current?.showModal();
    };
    const hotkey = (event: globalThis.KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        show();
      }
    };
    window.addEventListener(EVENT, show);
    window.addEventListener("keydown", hotkey);
    return () => {
      window.removeEventListener(EVENT, show);
      window.removeEventListener("keydown", hotkey);
    };
  }, []);

  useEffect(() => {
    const timer = setTimeout(() => {
      setQ(input.trim());
      setActive(0);
    }, 200);
    return () => clearTimeout(timer);
  }, [input]);

  const searching = open && q.length >= MIN_QUERY;
  const products = useSWR(
    searching ? `/products?palette=${q}` : null,
    () => unwrap(api.GET("/products", { params: { query: { q, limit: 5 } } })),
    { keepPreviousData: true },
  );
  const dialogs = useSWR(
    searching ? `/conversations?palette=${q}` : null,
    () => unwrap(api.GET("/conversations", { params: { query: { q, limit: 5 } } })),
    { keepPreviousData: true },
  );

  const entries = useMemo(() => {
    const needle = q.toLowerCase();
    const pages = PAGES.filter(
      (page) => (!page.ownerOnly || isOwner) && page.label.toLowerCase().includes(needle),
    );
    if (!searching) return pages;
    const found: Entry[] = [
      ...(products.data?.items ?? []).map((item) => ({
        group: "Товары",
        label: item.name,
        hint: [money(item.price), item.sku].filter(Boolean).join(" · "),
        href: `/products?q=${encodeURIComponent(item.sku ?? item.name)}`,
      })),
      ...(dialogs.data?.items ?? []).map((row) => ({
        group: "Диалоги",
        label: customerName(row),
        hint: row.preview ?? undefined,
        href: `/dialogs?id=${row.id}`,
      })),
    ];
    return [...found, ...pages];
  }, [q, searching, isOwner, products.data, dialogs.data]);

  function close() {
    dialog.current?.close();
  }

  function go(entry: Entry | undefined) {
    if (!entry) return;
    close();
    router.push(entry.href);
  }

  function keydown(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      const step = event.key === "ArrowDown" ? 1 : -1;
      setActive((value) => (value + step + entries.length) % Math.max(entries.length, 1));
    } else if (event.key === "Enter") {
      event.preventDefault();
      go(entries[active]);
    }
  }

  return (
    <dialog
      ref={dialog}
      aria-label="Поиск по кабинету"
      onClose={() => setOpen(false)}
      onClick={(event) => {
        if (event.target === dialog.current) close();
      }}
      className="m-auto mt-[10vh] w-[min(36rem,calc(100vw-2rem))] max-w-none overflow-hidden panel p-0 text-ink"
    >
      <div className="flex items-center gap-3 border-b border-line px-4">
        <Search className="size-4 shrink-0 text-steel" aria-hidden />
        <label htmlFor="palette-search" className="sr-only">
          Что найти
        </label>
        <input
          id="palette-search"
          autoFocus
          value={input}
          onChange={(event) => setInput(event.target.value)}
          onKeyDown={keydown}
          placeholder="Товар, покупатель, текст сообщения или раздел"
          className="min-h-12 min-w-0 flex-1 bg-transparent outline-none"
          role="combobox"
          aria-expanded="true"
          aria-controls="palette-results"
          aria-activedescendant={entries[active] ? `palette-${active}` : undefined}
        />
        <kbd className="rounded border border-line px-1.5 text-[11px] text-steel">Esc</kbd>
      </div>
      <ul id="palette-results" role="listbox" className="max-h-[55vh] overflow-y-auto py-2">
        {entries.length === 0 && (
          <li className="px-4 py-6 text-sm text-steel">
            Ничего не нашлось. Попробуйте артикул, имя или слово из переписки.
          </li>
        )}
        {entries.map((entry, index) => (
          <li key={`${entry.group}-${entry.href}-${index}`} role="presentation">
            {entry.group !== entries[index - 1]?.group && (
              <p className="px-4 pt-2 pb-1 text-[11px] font-medium tracking-wide text-steel uppercase">
                {entry.group}
              </p>
            )}
            <button
              type="button"
              id={`palette-${index}`}
              role="option"
              aria-selected={index === active}
              onMouseEnter={() => setActive(index)}
              onClick={() => go(entry)}
              className={cn(
                "flex min-h-10 w-full items-baseline justify-between gap-4 px-4 py-2 text-left text-sm",
                index === active && "bg-sky-soft",
              )}
            >
              <span className="min-w-0 truncate">{entry.label}</span>
              {entry.hint && (
                <span className="max-w-[50%] shrink-0 truncate text-xs text-steel tnum">
                  {entry.hint}
                </span>
              )}
            </button>
          </li>
        ))}
      </ul>
    </dialog>
  );
}
