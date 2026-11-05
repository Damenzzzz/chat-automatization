import type { Metadata } from "next";

import { BotView } from "./view";

export const metadata: Metadata = { title: "Бот и песочница" };

export default function Page() {
  return <BotView />;
}
