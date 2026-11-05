"use client";

import { CircleCheck, FileSpreadsheet, TriangleAlert, Upload } from "lucide-react";
import { useEffect, useMemo, useRef, useState, type DragEvent, type FormEvent } from "react";
import useSWR from "swr";

import { Button } from "@/components/ui/button";
import { TextField } from "@/components/ui/field";
import { Notice } from "@/components/ui/notice";
import { FormError } from "@/components/ui/page";
import { api, apiFetch, type Schemas } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";
import { count, money, plural } from "@/lib/format";
import { cn } from "@/lib/utils";

const FIELDS: { value: string; label: string }[] = [
  { value: "name", label: "Название" },
  { value: "sku", label: "Артикул" },
  { value: "price", label: "Цена" },
  { value: "stock", label: "Остаток" },
  { value: "category", label: "Категория" },
  { value: "description", label: "Описание" },
  { value: "image_url", label: "Ссылка на фото" },
];
const IGNORE = "";
const ATTRIBUTE = "attributes.";
const SURE = 0.8;

type Job = { id: string; fileName: string | null };
type Column = Schemas["ColumnMapping"];

async function uploadFile(file: File): Promise<Schemas["UploadOut"]> {
  const body = new FormData();
  body.append("file", file);
  const response = await apiFetch(new Request("/api/catalog/uploads", { method: "POST", body }));
  const json: unknown = await response.json().catch(() => ({}));
  return unwrap(
    Promise.resolve(
      response.ok ? { data: json as Schemas["UploadOut"], response } : { error: json, response },
    ),
  );
}

function PickSource({ onPicked }: { onPicked: (job: Job) => void }) {
  const input = useRef<HTMLInputElement>(null);
  const [over, setOver] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [sheet, setSheet] = useState("");

  async function send(file: File) {
    setBusy(true);
    setError(null);
    try {
      const job = await uploadFile(file);
      onPicked({ id: job.id, fileName: job.file_name });
    } catch (failure) {
      setError(failure);
    } finally {
      setBusy(false);
    }
  }

  async function sendSheet(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const job = await unwrap(
        api.POST("/catalog/uploads/gsheet", { body: { url: sheet.trim() } }),
      );
      onPicked({ id: job.id, fileName: job.file_name });
    } catch (failure) {
      setError(failure);
    } finally {
      setBusy(false);
    }
  }

  function drop(event: DragEvent) {
    event.preventDefault();
    setOver(false);
    const file = event.dataTransfer.files[0];
    if (file) void send(file);
  }

  return (
    <div className="flex flex-col gap-5">
      <div
        onDragOver={(event) => {
          event.preventDefault();
          setOver(true);
        }}
        onDragLeave={() => setOver(false)}
        onDrop={drop}
        className={cn(
          "flex flex-col items-start gap-3 rounded-md border border-dashed border-control px-5 py-6 sm:flex-row sm:items-center sm:justify-between",
          over && "border-ink bg-mist",
        )}
      >
        <div className="flex items-start gap-3">
          <FileSpreadsheet className="mt-0.5 size-5 shrink-0" aria-hidden />
          <div>
            <p className="font-medium">Файл Excel или CSV</p>
            <p className="text-sm text-steel">
              До 20 МБ. Перетащите сюда или выберите на устройстве.
            </p>
          </div>
        </div>
        <input
          ref={input}
          type="file"
          accept=".xlsx,.csv"
          className="sr-only"
          id="catalog-file"
          onChange={(event) => {
            const file = event.target.files?.[0];
            event.target.value = "";
            if (file) void send(file);
          }}
        />
        <Button variant="secondary" loading={busy} onClick={() => input.current?.click()}>
          <Upload aria-hidden />
          Выбрать файл
        </Button>
      </div>
      <form onSubmit={sendSheet} className="flex flex-col gap-2 sm:flex-row sm:items-end">
        <TextField
          className="flex-1"
          label="Или ссылка на Google Таблицу"
          type="url"
          placeholder="https://docs.google.com/spreadsheets/..."
          hint="Откройте доступ «Все, у кого есть ссылка»."
          value={sheet}
          onChange={(event) => setSheet(event.target.value)}
        />
        <Button
          type="submit"
          variant="secondary"
          disabled={!sheet.trim() || busy}
          className="sm:mb-6"
        >
          Загрузить таблицу
        </Button>
      </form>
      <FormError error={error} />
    </div>
  );
}

function fieldOf(value: string | null | undefined): string {
  return value ?? IGNORE;
}

function BotPreview({ columns, mapping }: { columns: Column[]; mapping: Record<string, string> }) {
  const rows = Math.max(0, ...columns.map((c) => c.samples?.length ?? 0));
  const [index, setIndex] = useState(0);
  const value = (field: string) => {
    const column = columns.find((c) => mapping[c.column] === field);
    return column?.samples?.[index] ?? null;
  };
  const attributes = columns
    .filter((c) => mapping[c.column]?.startsWith(ATTRIBUTE))
    .map((c) => ({ name: mapping[c.column].slice(ATTRIBUTE.length), value: c.samples?.[index] }))
    .filter((a) => a.value);
  const price = Number(
    String(value("price") ?? "")
      .replace(/[^\d.,]/g, "")
      .replace(",", "."),
  );
  const name = value("name");

  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center justify-between gap-2">
        <h4 className="text-sm font-medium">Так бот увидит товар</h4>
        {rows > 1 && (
          <Button
            variant="ghost"
            className="-mr-2 min-h-9 px-2"
            onClick={() => setIndex((index + 1) % rows)}
          >
            Другой товар
          </Button>
        )}
      </div>
      <div className="rounded-lg bg-haze px-4 py-3 text-sm">
        {name ? (
          <>
            <p className="font-medium">{name}</p>
            {value("category") && <p>Категория: {value("category")}</p>}
            {value("description") && <p className="line-clamp-3">{value("description")}</p>}
            {attributes.length > 0 && (
              <p>{attributes.map((a) => `${a.name}: ${a.value}`).join("; ")}</p>
            )}
            <p className="mt-2 border-t border-control/40 pt-2 text-steel">
              {value("sku") && <>Артикул {value("sku")}. </>}
              {price ? money(Math.round(price)) : "Цена не указана"}
              {value("stock") ? `, в наличии: ${value("stock")}` : ""}
            </p>
          </>
        ) : (
          <p className="text-steel">
            Выберите колонку с названием товара, и здесь появится пример.
          </p>
        )}
      </div>
      <p className="text-xs text-steel">
        Цену и остаток бот каждый раз берёт из каталога, поэтому они всегда актуальны и не попадают
        в обучение поиска.
      </p>
    </div>
  );
}

function MappingStep({
  job,
  onConfirmed,
  onBack,
}: {
  job: Job;
  onConfirmed: () => void;
  onBack: () => void;
}) {
  const { data, error, isLoading } = useSWR(
    `/catalog/uploads/${job.id}/mapping`,
    () =>
      unwrap(
        api.GET("/catalog/uploads/{job_id}/mapping", {
          params: { path: { job_id: job.id } },
        }),
      ),
    { revalidateOnFocus: false, revalidateIfStale: false },
  );
  const [changes, setChanges] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<unknown>(null);

  const mapping = useMemo(() => {
    const result: Record<string, string> = {};
    for (const column of data?.columns ?? []) {
      result[column.column] = changes[column.column] ?? fieldOf(column.field);
    }
    return result;
  }, [data, changes]);

  const duplicates = useMemo(() => {
    const used = Object.values(mapping).filter((f) => f && !f.startsWith(ATTRIBUTE));
    return new Set(used.filter((f, i) => used.indexOf(f) !== i));
  }, [mapping]);
  const hasName = Object.values(mapping).includes("name");

  async function confirm() {
    setBusy(true);
    setFailure(null);
    const body: Record<string, string | null> = {};
    for (const [column, field] of Object.entries(mapping)) body[column] = field || null;
    try {
      await unwrap(
        api.POST("/catalog/uploads/{job_id}/confirm", {
          params: { path: { job_id: job.id } },
          body: { mapping: body },
        }),
      );
      onConfirmed();
    } catch (problem) {
      setFailure(problem);
      setBusy(false);
    }
  }

  if (isLoading) {
    return (
      <p role="status" className="py-6 text-sm text-steel">
        ИИ читает колонки файла, это занимает до 20 секунд.
      </p>
    );
  }
  if (error || !data) return <FormError error={error} />;

  return (
    <div className="flex flex-col gap-5">
      <p className="text-sm text-steel">
        {data.method === "llm" &&
          "ИИ предложил сопоставление. Проверьте колонки, которые отмечены как сомнительные."}
        {data.method === "heuristic" &&
          "Сопоставили колонки по названиям. Проверьте, всё ли верно."}
        {data.method === "saved" && "Взяли сопоставление из прошлой загрузки этого источника."}
      </p>
      <div className="grid gap-6 lg:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
        <div className="min-w-0">
          <table className="w-full text-sm max-sm:block">
            <thead className="text-left text-steel max-sm:sr-only">
              <tr className="border-b border-line">
                <th scope="col" className="py-2 pr-3 font-normal">
                  Колонка в файле
                </th>
                <th scope="col" className="py-2 font-normal">
                  Что в ней
                </th>
              </tr>
            </thead>
            <tbody className="max-sm:block">
              {data.columns.map((column) => {
                const field = mapping[column.column];
                const isAttribute = field.startsWith(ATTRIBUTE);
                const conflict = duplicates.has(field);
                const unsure = !changes[column.column] && column.field && column.confidence < SURE;
                return (
                  <tr
                    key={column.column}
                    className="border-b border-line align-top max-sm:block max-sm:py-3"
                  >
                    <th
                      scope="row"
                      className="py-3 pr-3 text-left font-medium max-sm:block max-sm:py-0"
                    >
                      <span className="break-words">{column.column}</span>
                      {column.samples?.[0] && (
                        <span className="mt-0.5 line-clamp-1 block font-normal text-steel">
                          например, {column.samples[0]}
                        </span>
                      )}
                    </th>
                    <td className="py-3 max-sm:block max-sm:pt-2 max-sm:pb-0 sm:w-56">
                      <select
                        aria-label={`Что в колонке ${column.column}`}
                        aria-invalid={conflict || undefined}
                        value={isAttribute ? "attribute" : field}
                        onChange={(event) => {
                          const next = event.target.value;
                          setChanges({
                            ...changes,
                            [column.column]:
                              next === "attribute" ? `${ATTRIBUTE}${column.column}` : next,
                          });
                        }}
                        className="min-h-11 w-full rounded-md border border-control bg-paper px-2 text-base hover:border-ink aria-invalid:border-alert sm:min-h-10 sm:text-sm"
                      >
                        <option value={IGNORE}>Не загружать</option>
                        {FIELDS.map((option) => (
                          <option key={option.value} value={option.value}>
                            {option.label}
                          </option>
                        ))}
                        <option value="attribute">Характеристика</option>
                      </select>
                      {conflict && (
                        <p className="mt-1 text-xs font-medium text-alert">
                          Выбрано для нескольких колонок
                        </p>
                      )}
                      {!conflict && unsure && (
                        <p className="mt-1 flex items-center gap-1 text-xs text-steel">
                          <TriangleAlert className="size-3.5" aria-hidden />
                          ИИ не уверен, проверьте
                        </p>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        <BotPreview columns={data.columns} mapping={mapping} />
      </div>
      {!hasName && (
        <Notice kind="error">
          Укажите, в какой колонке название товара, без него загрузить нельзя.
        </Notice>
      )}
      <FormError error={failure} />
      <div className="flex flex-wrap gap-2">
        <Button
          loading={busy}
          disabled={!hasName || duplicates.size > 0}
          onClick={() => void confirm()}
        >
          Загрузить товары
        </Button>
        <Button variant="ghost" onClick={onBack}>
          Выбрать другой файл
        </Button>
      </div>
    </div>
  );
}

function ProgressStep({
  job,
  onReset,
  onDone,
}: {
  job: Job;
  onReset: () => void;
  onDone?: () => void;
}) {
  const { data, error } = useSWR(
    `/ingest-jobs/${job.id}`,
    () => unwrap(api.GET("/ingest-jobs/{job_id}", { params: { path: { job_id: job.id } } })),
    {
      refreshInterval: (latest) =>
        latest && ["done", "failed"].includes(latest.status) ? 0 : 1000,
    },
  );
  const finished = data?.status === "done";
  const notified = useRef(false);
  useEffect(() => {
    if (finished && !notified.current) {
      notified.current = true;
      onDone?.();
    }
  }, [finished, onDone]);

  if (error) return <FormError error={error} />;
  const percent = Math.round((data?.progress ?? 0) * 100);
  const stats = (data?.stats ?? {}) as Record<string, number>;
  const errors = data?.errors ?? [];

  return (
    <div className="flex flex-col gap-4">
      {data?.status === "failed" ? (
        <Notice kind="error">
          Файл не загрузился. Проверьте его содержимое и попробуйте снова.
        </Notice>
      ) : finished ? (
        <p className="flex items-center gap-2 font-medium">
          <CircleCheck className="size-5" aria-hidden />
          Товары загружены
        </p>
      ) : (
        <div>
          <div className="mb-1.5 flex justify-between text-sm">
            <span>Загружаем {job.fileName ?? "файл"}</span>
            <span className="tnum">
              {data?.rows_total ? `${count(data.rows_done)} из ${count(data.rows_total)}` : ""}
            </span>
          </div>
          <div
            role="progressbar"
            aria-label="Загрузка товаров"
            aria-valuenow={percent}
            aria-valuemin={0}
            aria-valuemax={100}
            className="h-2 overflow-hidden rounded-sm bg-haze"
          >
            <div
              className="h-full bg-ink transition-[width] duration-300"
              style={{ width: `${percent}%` }}
            />
          </div>
        </div>
      )}
      {finished && (
        <dl className="flex flex-wrap gap-x-8 gap-y-2 text-sm tnum">
          {[
            ["Новых", stats.created],
            ["Обновлено", stats.updated],
            ["Без изменений", stats.unchanged],
            ["Пустых строк", stats.skipped_empty],
          ]
            .filter(([, value]) => typeof value === "number")
            .map(([label, value]) => (
              <div key={label as string}>
                <dt className="text-steel">{label}</dt>
                <dd className="display text-lg">{count(value as number)}</dd>
              </div>
            ))}
        </dl>
      )}
      {errors.length > 0 && (
        <details className="text-sm">
          <summary className="font-medium">
            {count(errors.length)} {plural(errors.length, "строка", "строки", "строк")} с ошибками
          </summary>
          <ul className="mt-2 flex flex-col gap-1 text-steel">
            {errors.slice(0, 20).map((item, index) => (
              <li key={index}>
                {item.row ? `Строка ${item.row}: ` : ""}
                {item.reason}
              </li>
            ))}
          </ul>
        </details>
      )}
      {(finished || data?.status === "failed") && (
        <div>
          <Button variant="secondary" onClick={onReset}>
            Загрузить ещё файл
          </Button>
        </div>
      )}
    </div>
  );
}

export function CatalogImport({ onDone }: { onDone?: () => void }) {
  const [job, setJob] = useState<Job | null>(null);
  const [stage, setStage] = useState<"pick" | "map" | "run">("pick");

  if (stage === "pick" || !job) {
    return (
      <PickSource
        onPicked={(picked) => {
          setJob(picked);
          setStage("map");
        }}
      />
    );
  }
  if (stage === "map") {
    return (
      <MappingStep job={job} onConfirmed={() => setStage("run")} onBack={() => setStage("pick")} />
    );
  }
  return <ProgressStep job={job} onDone={onDone} onReset={() => setStage("pick")} />;
}
