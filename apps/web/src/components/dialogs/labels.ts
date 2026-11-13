export const CHANNEL_NAMES: Record<string, string> = {
  telegram: "Telegram",
  whatsapp: "WhatsApp",
  instagram: "Instagram",
  web: "Сайт",
};

export const LEAD_STATUS: Record<string, string> = {
  new: "Новая",
  in_progress: "В работе",
  done: "Выполнена",
  cancelled: "Отменена",
};

export const CANCEL_REASONS: Record<string, string> = {
  price: "Дорого",
  no_stock: "Нет в наличии",
  no_answer: "Не отвечает",
  changed_mind: "Передумал",
  duplicate: "Дубль",
  other: "Другое",
};

export const PAUSED: Record<string, string> = {
  no_balance:
    "Баланс закончился, поэтому бот не отвечает. Пополните баланс, и диалог вернётся к нему сам.",
  rate_limit: "Покупатель написал слишком много за час, поэтому диалог передан менеджеру.",
};

export function customerName(row: {
  customer_name?: string | null;
  customer_phone?: string | null;
}): string {
  return row.customer_name || row.customer_phone || "Покупатель";
}
