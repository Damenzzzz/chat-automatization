import type { Metadata } from "next";

import { LeadsView } from "./view";

export const metadata: Metadata = { title: "Заявки" };

export default function LeadsPage() {
  return <LeadsView />;
}
