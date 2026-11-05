import type { Metadata } from "next";

import { SetupWizard } from "./wizard";

export const metadata: Metadata = { title: "Настройка магазина" };

export default function SetupPage() {
  return <SetupWizard />;
}
