import type { Metadata } from "next";
import { Commissioner, Golos_Text } from "next/font/google";

import { cn } from "@/lib/utils";

import "./globals.css";

const golos = Golos_Text({
  subsets: ["latin", "latin-ext", "cyrillic", "cyrillic-ext"],
  variable: "--font-golos",
  display: "swap",
});

const commissioner = Commissioner({
  subsets: ["latin", "latin-ext", "cyrillic", "cyrillic-ext"],
  axes: ["FLAR", "VOLM"],
  variable: "--font-commissioner",
  display: "swap",
});

export const metadata: Metadata = {
  title: { default: "Satushy", template: "%s | Satushy" },
  description:
    "AI-консультант, который знает весь каталог магазина и отвечает покупателям в WhatsApp, Instagram, Telegram и на сайте.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="ru" className={cn(golos.variable, commissioner.variable)}>
      <body>{children}</body>
    </html>
  );
}
