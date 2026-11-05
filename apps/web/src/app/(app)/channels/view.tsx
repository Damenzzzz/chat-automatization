"use client";

import { ChannelsPanel } from "@/components/channels/channels-panel";
import { Page, PageHeader } from "@/components/ui/page";

export function ChannelsView() {
  return (
    <Page>
      <PageHeader title="Каналы">
        Где бот отвечает покупателям. Все диалоги приходят в один кабинет.
      </PageHeader>
      <ChannelsPanel />
    </Page>
  );
}
