// Главная отдельного лендинга (сборка LANDING_ONLY=1): без входа, кабинета и API.
import type { Metadata } from "next";

import { LandingPage } from "@/components/landing/landing-page";

export const metadata: Metadata = {
  title: { absolute: "Satushy — чат-боты и автоматизация для бизнеса в Казахстане" },
  description:
    "Satushy — IT-команда из Казахстана. Бот-продавец отвечает покупателям в WhatsApp, Instagram и Telegram, а остальную рутину — заявки, отчёты, документы — автоматизируем под вашу задачу.",
};

export default function Landing() {
  return <LandingPage standalone />;
}
