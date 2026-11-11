import type { Metadata } from "next";
import { Suspense } from "react";

import { AuthFlow } from "@/components/auth/auth-flow";
import { ResumeSession } from "@/components/auth/resume-session";

export const metadata: Metadata = { title: "Вход" };

export default function LoginPage() {
  return (
    <Suspense>
      <ResumeSession />
      <AuthFlow mode="login" />
    </Suspense>
  );
}
