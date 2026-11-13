import type { Metadata } from "next";

import { ServicesView } from "./view";

export const metadata: Metadata = { title: "Сервисы" };

export default function Page() {
  return <ServicesView />;
}
