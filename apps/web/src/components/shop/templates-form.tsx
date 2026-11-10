"use client";

import { Plus, Trash2 } from "lucide-react";
import { useState, type FormEvent } from "react";

import { Button } from "@/components/ui/button";
import { TextArea, TextField } from "@/components/ui/field";
import { FormError } from "@/components/ui/page";
import { api, type Schemas } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";

type Template = Schemas["ReplyTemplate"];

const MAX_TEMPLATES = 20;

export function TemplatesForm({
  templates,
  onDone,
}: {
  templates: Template[];
  onDone: (shop: Schemas["ShopOut"]) => void;
}) {
  const [items, setItems] = useState<Template[]>(templates);
  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<unknown>(null);

  function change(index: number, patch: Partial<Template>) {
    setSaved(false);
    setItems(items.map((item, at) => (at === index ? { ...item, ...patch } : item)));
  }

  async function save(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const filled = items
        .map((item) => ({ title: item.title.trim(), text: item.text.trim() }))
        .filter((item) => item.title && item.text);
      const shop = await unwrap(api.PATCH("/shop", { body: { reply_templates: filled } }));
      setItems(shop.reply_templates);
      setSaved(true);
      onDone(shop);
    } catch (failure) {
      setError(failure);
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={save} className="flex max-w-2xl flex-col gap-4">
      {items.length === 0 && (
        <p className="text-sm text-steel">
          Шаблонов пока нет. Добавьте реквизиты, адрес или условия доставки, чтобы менеджер вставлял
          их одним нажатием.
        </p>
      )}
      {items.map((item, index) => (
        <fieldset key={index} className="flex flex-col gap-3 rounded-md border border-line p-4">
          <legend className="sr-only">Шаблон {index + 1}</legend>
          <div className="flex items-end gap-2">
            <TextField
              id={`template-title-${index}`}
              label="Название кнопки"
              maxLength={60}
              value={item.title}
              onChange={(event) => change(index, { title: event.target.value })}
              className="flex-1"
            />
            <Button
              variant="ghost"
              aria-label={`Удалить шаблон ${index + 1}`}
              onClick={() => {
                setSaved(false);
                setItems(items.filter((_, at) => at !== index));
              }}
            >
              <Trash2 aria-hidden />
            </Button>
          </div>
          <TextArea
            id={`template-text-${index}`}
            label="Текст ответа"
            rows={3}
            maxLength={1000}
            value={item.text}
            onChange={(event) => change(index, { text: event.target.value })}
          />
        </fieldset>
      ))}
      <FormError error={error} />
      <div className="flex flex-wrap items-center gap-3">
        <Button
          variant="secondary"
          disabled={items.length >= MAX_TEMPLATES}
          onClick={() => {
            setSaved(false);
            setItems([...items, { title: "", text: "" }]);
          }}
        >
          <Plus aria-hidden />
          Добавить шаблон
        </Button>
        <Button type="submit" loading={busy}>
          Сохранить
        </Button>
        {saved && (
          <span role="status" className="text-sm text-steel">
            Сохранено
          </span>
        )}
      </div>
    </form>
  );
}
