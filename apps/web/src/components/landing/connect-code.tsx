"use client";

import { Check, Copy } from "lucide-react";
import { useState } from "react";

import { cn } from "@/lib/utils";

const TABS = [
  {
    id: "site",
    label: "Сайт",
    file: "index.html",
    lines: [
      [["c", "<!-- перед </body> -->"]],
      [
        ["t", "<script "],
        ["a", "src"],
        ["t", "="],
        ["s", '"https://satushy.kz/widget.js"'],
      ],
      [
        ["t", "        "],
        ["a", "data-key"],
        ["t", "="],
        ["s", '"pk_9f3c…"'],
        ["t", " async></script>"],
      ],
    ],
  },
  {
    id: "telegram",
    label: "Telegram",
    file: "@BotFather",
    lines: [
      [["c", "1. /newbot — придумайте имя"]],
      [["c", "2. скопируйте токен"]],
      [
        ["a", "token"],
        ["t", " = "],
        ["s", '"123456789:AAE…"'],
      ],
      [["c", "3. вставьте в кабинет — вебхук настроим сами"]],
    ],
  },
  {
    id: "whatsapp",
    label: "WhatsApp",
    file: "Meta Business",
    lines: [
      [["c", "1. номер WhatsApp Business"]],
      [
        ["a", "phone_number_id"],
        ["t", " = "],
        ["s", '"1098…"'],
      ],
      [
        ["a", "access_token"],
        ["t", " = "],
        ["s", '"EAAG…"'],
      ],
      [["c", "2. подпись вебхука проверяем по app secret"]],
    ],
  },
] as const;

const COLORS = { c: "text-paper/40", t: "text-paper/85", a: "text-glow", s: "text-sun" };

export function ConnectCode() {
  const [tab, setTab] = useState<(typeof TABS)[number]["id"]>("site");
  const [copied, setCopied] = useState(false);
  const current = TABS.find((item) => item.id === tab) ?? TABS[0];
  const text = current.lines.map((line) => line.map(([, value]) => value).join("")).join("\n");
  return (
    <div className="glow-border rounded-xl">
      <div className="rounded-xl bg-night-2">
        <div className="flex flex-wrap items-center justify-between gap-2 rounded-t-xl border-b border-white/10 px-3 py-2">
          <div role="tablist" aria-label="Канал" className="flex gap-1">
            {TABS.map((item) => (
              <button
                key={item.id}
                type="button"
                role="tab"
                aria-selected={item.id === tab}
                onClick={() => {
                  setTab(item.id);
                  setCopied(false);
                }}
                className={cn(
                  "min-h-9 rounded-md px-3 text-sm transition-colors",
                  item.id === tab
                    ? "bg-white/10 font-medium text-paper"
                    : "text-paper/55 hover:text-paper",
                )}
              >
                {item.label}
              </button>
            ))}
          </div>
          <button
            type="button"
            onClick={async () => {
              try {
                await navigator.clipboard.writeText(text);
                setCopied(true);
              } catch {
                setCopied(false);
              }
            }}
            className="flex min-h-9 items-center gap-1.5 rounded-md px-2 text-sm text-paper/60 hover:text-paper"
          >
            {copied ? <Check className="size-4 text-teal" /> : <Copy className="size-4" />}
            {copied ? "Скопировано" : "Копировать"}
          </button>
        </div>
        <div
          role="tabpanel"
          className="overflow-x-auto rounded-b-xl p-5 font-mono text-sm leading-7"
        >
          <p className="mb-2 text-xs text-paper/35">{current.file}</p>
          {current.lines.map((line, index) => (
            <div key={index} className="flex gap-4 whitespace-pre">
              <span className="w-4 shrink-0 text-right text-paper/25 select-none">{index + 1}</span>
              <span>
                {line.map(([kind, value], part) => (
                  <span key={part} className={COLORS[kind]}>
                    {value}
                  </span>
                ))}
              </span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
