"use client";

import { useState, type FormEvent } from "react";
import useSWR from "swr";

import { Button } from "@/components/ui/button";
import { TextArea } from "@/components/ui/field";
import { Notice } from "@/components/ui/notice";
import { Empty, FormError, LoadError, Loading } from "@/components/ui/page";
import { api, type Schemas } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";
import { count, plural, whenShort } from "@/lib/format";

type Group = Schemas["UnansweredGroupOut"];
type Range = { date_from: string; date_to: string };

function Row({ group, onAnswered }: { group: Group; onAnswered: (question: string) => void }) {
  const [open, setOpen] = useState(false);
  const [answer, setAnswer] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await unwrap(
        api.POST("/unanswered/{unanswered_id}/answer", {
          params: { path: { unanswered_id: group.ids[0] } },
          body: { answer: answer.trim(), also_resolve: group.ids.slice(1) },
        }),
      );
      onAnswered(group.question);
    } catch (failure) {
      setError(failure);
      setBusy(false);
    }
  }

  return (
    <li className="py-3">
      <div className="flex flex-wrap items-start justify-between gap-x-4 gap-y-2">
        <div className="min-w-0 flex-1 basis-56">
          <p className="break-words">{group.question}</p>
          <p className="mt-0.5 text-xs text-steel tnum">
            {count(group.count)} {plural(group.count, "раз", "раза", "раз")}
            {group.last_asked_at ? `, последний ${whenShort(group.last_asked_at)}` : ""}
          </p>
        </div>
        {!open && (
          <Button variant="secondary" onClick={() => setOpen(true)}>
            Ответить
          </Button>
        )}
      </div>
      {group.examples.length > 1 && (
        <p className="mt-1 text-xs text-steel">Похожие: {group.examples.slice(1, 3).join("; ")}</p>
      )}
      {open && (
        <form onSubmit={submit} className="mt-3 flex flex-col gap-3">
          <TextArea
            label="Ответ для бота"
            hint="Бот запомнит его и сам ответит покупателям, которые спросят то же самое."
            autoFocus
            required
            maxLength={4000}
            value={answer}
            onChange={(event) => setAnswer(event.target.value)}
          />
          <FormError error={error} />
          <div className="flex flex-wrap gap-2">
            <Button type="submit" loading={busy} disabled={!answer.trim()}>
              Научить бота
            </Button>
            <Button variant="ghost" onClick={() => setOpen(false)}>
              Отмена
            </Button>
          </div>
        </form>
      )}
    </li>
  );
}

export function Unanswered({ range }: { range: Range }) {
  const { data, error, isLoading, mutate } = useSWR(
    `/analytics/unanswered?${range.date_from}&${range.date_to}`,
    () => unwrap(api.GET("/analytics/unanswered", { params: { query: range } })),
  );
  const [learned, setLearned] = useState<string | null>(null);

  if (isLoading) return <Loading />;
  if (error || !data) return <LoadError error={error} retry={() => void mutate()} />;

  return (
    <>
      {learned && (
        <Notice kind="success" className="mb-3">
          Бот запомнил ответ на вопрос «{learned}». Начнёт отвечать через минуту.
        </Notice>
      )}
      {data.groups.length === 0 ? (
        <Empty title="Бот справился со всеми вопросами">
          Если он чего-то не узнает, вопрос появится здесь.
        </Empty>
      ) : (
        <ul className="divide-y divide-line">
          {data.groups.slice(0, 8).map((group) => (
            <Row
              key={group.ids[0]}
              group={group}
              onAnswered={(question) => {
                setLearned(question);
                void mutate();
              }}
            />
          ))}
        </ul>
      )}
    </>
  );
}
