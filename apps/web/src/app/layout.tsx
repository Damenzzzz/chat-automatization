import type { Metadata } from "next";
import { Geist } from "next/font/google";

import { cn } from "@/lib/utils";

import "./globals.css";

// cyrillic-ext нужен для казахских букв (ә, ғ, қ, ң, ө, ұ, ү, һ, і).
const geist = Geist({
  subsets: ["latin", "cyrillic", "cyrillic-ext"],
  variable: "--font-sans",
});

export const metadata: Metadata = {
  title: "Satushy — AI-консультант для магазина",
  description:
    "AI-консультант, который знает весь каталог магазина и отвечает покупателям в WhatsApp, Instagram, Telegram и на сайте.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="ru" className={cn("font-sans", geist.variable)}>
      <body>{children}</body>
    </html>
  );
}
