const MESSAGES: Record<string, string> = {
  wrong_code: "Код неверный. Проверьте цифры или запросите новый.",
  code_expired: "Код устарел. Запросите новый.",
  too_many_requests: "Слишком много запросов. Подождите минуту и попробуйте снова.",
  too_many_attempts: "Слишком много попыток. Запросите новый код через несколько минут.",
  channel_unavailable: "Не удалось отправить код. Войдите по почте или попробуйте позже.",
  already_registered: "Такой номер или почта уже зарегистрированы. Войдите в кабинет.",
  user_disabled: "Доступ отключён. Обратитесь к владельцу магазина.",
  forbidden: "Этот раздел доступен только владельцу магазина.",
  telegram_token_invalid: "Telegram не принял токен. Скопируйте его из @BotFather целиком.",
  public_url_not_https:
    "У сервера нет HTTPS-адреса, а без него Telegram не подключается. Укажите PUBLIC_API_URL.",
  encryption_not_configured:
    "На сервере не задан ключ шифрования FERNET_KEY, ключи канала сохранить нельзя.",
  domain_invalid: "Адрес сайта указан неверно. Пример: pion.kz",
  channel_in_use: "Этот бот или номер уже подключён к другому магазину.",
  channel_not_found: "Канал не найден. Обновите страницу.",
  channel_missing: "Этот диалог не связан с каналом, ответить в него нельзя.",
  conversation_not_found: "Диалог не найден.",
  billing_requisites_not_configured:
    "Реквизиты Satushy ещё не заполнены, счёт выставить нельзя. Напишите в поддержку.",
  llm_unavailable: "Модель сейчас недоступна. На сервере не задан ключ GEMINI_API_KEY.",
  llm_failed: "Модель не ответила. Попробуйте ещё раз через минуту.",
  file_too_large: "Файл больше 20 МБ. Разделите его на части или удалите лишние колонки.",
  only_xlsx_or_csv: "Подойдёт только файл .xlsx или .csv.",
  empty_file: "Файл пустой. Проверьте, что в нём есть строки с товарами.",
  sheet_download_failed:
    "Не удалось открыть таблицу. Откройте доступ по ссылке и попробуйте снова.",
  job_in_progress: "Этот файл уже загружается. Дождитесь окончания.",
  answer_empty: "Напишите ответ.",
  already_resolved: "На этот вопрос уже ответили.",
  no_previous_version: "Предыдущей версии нет.",
  telegram_not_connected: "Сначала подключите Telegram-бота на странице «Каналы».",
  cannot_remove_self: "Нельзя удалить самого себя.",
  nothing_to_answer: "В диалоге пока нет вопроса покупателя, на который можно ответить.",
  demo_read_only:
    "В демо-магазине это отключено. Подключите свой магазин, чтобы настроить всё под себя.",
  demo_disabled: "Демо-режим выключен на этом сервере. Зарегистрируйте свой магазин.",
};

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string | null,
    message: string,
  ) {
    super(message);
  }
}

function readDetail(error: unknown): { code: string | null; message: string | null } {
  const detail = (error as { detail?: unknown } | undefined)?.detail;
  if (typeof detail === "string") return { code: detail, message: MESSAGES[detail] ?? null };
  if (Array.isArray(detail)) {
    const lines = detail.map((item) => (typeof item === "string" ? item : null)).filter(Boolean);
    return { code: null, message: lines.length ? lines.join(". ") : "Проверьте заполненные поля." };
  }
  return { code: null, message: null };
}

export async function unwrap<T>(
  call: Promise<{ data?: T; error?: unknown; response: Response }>,
): Promise<T> {
  const { data, error, response } = await call;
  if (response.ok) return data as T;
  const { code, message } = readDetail(error);
  const fallback =
    response.status >= 500
      ? "Сервер не ответил. Попробуйте ещё раз через минуту."
      : "Запрос не выполнен. Проверьте данные и попробуйте снова.";
  throw new ApiError(response.status, code, message ?? fallback);
}

export function errorText(error: unknown): string | null {
  if (!error) return null;
  if (error instanceof ApiError) return error.message;
  return "Нет связи с сервером. Проверьте интернет и попробуйте снова.";
}
