import type { Metadata } from "next";

import { OverviewView } from "./view";

export const metadata: Metadata = { title: "Обзор" };

export default function Page() {
  return <OverviewView />;
}
