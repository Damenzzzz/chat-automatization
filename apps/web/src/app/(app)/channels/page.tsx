import type { Metadata } from "next";

import { ChannelsView } from "./view";

export const metadata: Metadata = { title: "Каналы" };

export default function Page() {
  return <ChannelsView />;
}
