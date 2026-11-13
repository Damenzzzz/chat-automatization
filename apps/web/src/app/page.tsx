import type { Metadata } from "next";

import { DemoButton } from "@/components/auth/demo-button";
import { LandingPage } from "@/components/landing/landing-page";

export const metadata: Metadata = {
  title: { absolute: "Satushy — бот-продавец для магазинов Казахстана" },
};

export default function Landing() {
  return (
    <LandingPage
      demo={
        <DemoButton variant="glow" className="min-h-12 px-6 text-base" hideWhenOff={false}>
          Открыть демо-кабинет
        </DemoButton>
      }
    />
  );
}
