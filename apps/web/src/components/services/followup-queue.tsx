"use client";

import Link from "next/link";
import { useState } from "react";
import useSWR, { useSWRConfig } from "swr";

import { Button } from "@/components/ui/button";
import { TextArea } from "@/components/ui/field";
import { Notice } from "@/components/ui/notice";
import { FormError, LoadError } from "@/components/ui/page";
import { api, type Schemas } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";
import { whenShort } from "@/lib/format";

import { CHANNEL_NAMES } from "@/components/dialogs/labels";

export const FOLLOWUPS_KEY = "/followups?status=pending";

type Followup = Schemas["FollowupOut"];

const RESULT: Record<string, string> = {
  sent: "Отправлено покупателю.",
  rejected: "Отклонено, покупателю ничего не ушло.",
  expired: "Не отправлено: покупатель уже написал сам, диалог у менеджера или прошли сутки.",
  failed: "Канал не принял сообщение. Проверьте подключение на странице «Каналы».",
};

function Item({ item, onDone }: { item: Followup; onDone: (status: string) => void }) {
  const [text, setText] = useState(item.text);
  const [busy, setBusy] = useState<"send" | "reject" | null>(null);
  const [error, setError] = useState<unknown>(null);
  const path = { params: { path: { followup_id: item.id } } };

  async function decide(action: "send" | "reject") {
    setBusy(action);
    setError(null);
    try {
      const saved =
        action === "send"
          ? await unwrap(
              api.POST("/followups/{followup_id}/send", { ...path, body: { text: text.trim() } }),
            )
          : await unwrap(api.POST("/followups/{followup_id}/reject", path));
      onDone(saved.status);
    } catch (failure) {
      setError(failure);
    } finally {
      setBusy(null);
    }
  }

  return (
    <li className="rounded-lg border border-line p-4">
      <p className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 text-sm">
        <span className="font-medium">
          {item.customer_name ?? "Покупатель без имени"}
          <span className="font-normal text-steel">
            {item.channel ? `, ${CHANNEL_NAMES[item.channel] ?? item.channel}` : ""}
          </span>
        </span>
        <Link
          href={`/dialogs?id=${item.conversation_id}`}
          className="text-sky-deep underline underline-offset-4"
        >
          Открыть диалог
        </Link>
      </p>
      <TextArea
        className="mt-3"
        label="Сообщение покупателю"
        rows={3}
        maxLength={500}
        value={text}
        onChange={(event) => setText(event.target.value)}
        hint={`Создано ${whenShort(item.created_at)}`}
      />
      <FormError error={error} />
      <div className="mt-3 flex flex-wrap gap-2">
        <Button
          loading={busy === "send"}
          disabled={busy !== null || text.trim().length < 10}
          onClick={() => void decide("send")}
        >
          Отправить
        </Button>
        <Button
          variant="secondary"
          loading={busy === "reject"}
          disabled={busy !== null}
          onClick={() => void decide("reject")}
        >
          Не отправлять
        </Button>
      </div>
    </li>
  );
}

export function FollowupQueue() {
  const { mutate: mutateGlobal } = useSWRConfig();
  const { data, error, mutate } = useSWR(FOLLOWUPS_KEY, () =>
    unwrap(api.GET("/followups", { params: { query: { status: "pending" } } })),
  );
  const [result, setResult] = useState<string | null>(null);

  if (error) return <LoadError error={error} retry={() => void mutate()} />;
  if (!data) return <p className="text-sm text-steel">Загружаем очередь…</p>;
  return (
    <>
      {result && (
        <Notice kind={result === "sent" ? "success" : "info"} className="mb-3">
          {RESULT[result] ?? result}
        </Notice>
      )}
      {data.length === 0 ? (
        <p className="text-sm text-steel">
          Очередь пуста. Когда сервис найдёт затихший диалог, сообщение появится здесь и будет ждать
          вашего решения.
        </p>
      ) : (
        <ul className="flex flex-col gap-3">
          {data.map((item) => (
            <Item
              key={item.id}
              item={item}
              onDone={(status) => {
                setResult(status);
                void mutate();
                void mutateGlobal("/automations");
              }}
            />
          ))}
        </ul>
      )}
    </>
  );
}
