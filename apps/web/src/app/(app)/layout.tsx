import { Suspense } from "react";

import { AppShell } from "@/components/shell/app-shell";
import { Loading } from "@/components/ui/page";

export default function AppLayout({ children }: { children: React.ReactNode }) {
  return (
    <AppShell>
      <Suspense fallback={<Loading className="px-4 sm:px-8" />}>{children}</Suspense>
    </AppShell>
  );
}
