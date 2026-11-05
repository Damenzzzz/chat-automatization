"use client";

import { createContext, useContext, type ReactNode } from "react";
import useSWR from "swr";

import { api, type Schemas } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";

type Session = {
  me: Schemas["MeOut"] | undefined;
  shop: Schemas["ShopOut"] | undefined;
  isOwner: boolean;
  error: unknown;
  retry: () => void;
};

const SessionContext = createContext<Session | null>(null);

export function SessionProvider({ children }: { children: ReactNode }) {
  const me = useSWR("/me", () => unwrap(api.GET("/me")));
  const shop = useSWR("/shop", () => unwrap(api.GET("/shop")));
  return (
    <SessionContext.Provider
      value={{
        me: me.data,
        shop: shop.data,
        isOwner: me.data?.role === "owner" || me.data?.role === "admin",
        error: me.error ?? shop.error,
        retry: () => {
          void me.mutate();
          void shop.mutate();
        },
      }}
    >
      {children}
    </SessionContext.Provider>
  );
}

export function useSession(): Session {
  const session = useContext(SessionContext);
  if (!session) throw new Error("useSession вне SessionProvider");
  return session;
}
