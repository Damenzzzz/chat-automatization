import type { Metadata } from "next";

import { DialogsView } from "./view";

export const metadata: Metadata = { title: "Диалоги" };

export default function DialogsPage() {
  return <DialogsView />;
}
