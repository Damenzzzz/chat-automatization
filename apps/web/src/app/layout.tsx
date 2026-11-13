import type { Metadata } from "next";
import { Geologica, Golos_Text } from "next/font/google";

import { cn } from "@/lib/utils";

import "./globals.css";

const golos = Golos_Text({
  subsets: ["latin", "latin-ext", "cyrillic", "cyrillic-ext"],
  variable: "--font-golos",
  display: "swap",
});

const geologica = Geologica({
  subsets: ["latin", "latin-ext", "cyrillic", "cyrillic-ext"],
  axes: ["SHRP"],
  variable: "--font-geologica",
  display: "swap",
});

export const metadata: Metadata = {
  title: { default: "Satushy", template: "%s | Satushy" },
  description:
    "Бот-продавец для магазинов Казахстана: знает весь каталог и отвечает покупателям в WhatsApp, Instagram, Telegram и на сайте на казахском и русском.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    // data-scroll-behavior: переходы между страницами остаются мгновенными,
    // плавная прокрутка действует только для ссылок-якорей лендинга.
    <html
      lang="ru"
      data-scroll-behavior="smooth"
      className={cn(golos.variable, geologica.variable)}
    >
      <body>{children}</body>
    </html>
  );
}
