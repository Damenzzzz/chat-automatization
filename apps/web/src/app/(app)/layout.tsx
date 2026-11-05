import { Suspense } from "react";

import { AppShell } from "@/components/shell/app-shell";

export default function AppLayout({ children }: { children: React.ReactNode }) {
  return (
    <AppShell>
      <Suspense>{children}</Suspense>
    </AppShell>
  );
}
