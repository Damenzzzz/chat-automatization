import type { Metadata } from "next";

import { BalanceView } from "./view";

export const metadata: Metadata = { title: "Баланс" };

export default function Page() {
  return <BalanceView />;
}
