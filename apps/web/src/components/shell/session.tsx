"use client";

import { createContext, useContext, useSyncExternalStore, type ReactNode } from "react";
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

const noop = () => () => {};

export function SessionProvider({ children }: { children: ReactNode }) {
  const hydrated = useSyncExternalStore(
    noop,
    () => true,
    () => false,
  );
  const me = useSWR("/me", () => unwrap(api.GET("/me")));
  const shop = useSWR("/shop", () => unwrap(api.GET("/shop")));
  const meData = hydrated ? me.data : undefined;
  return (
    <SessionContext.Provider
      value={{
        me: meData,
        shop: hydrated ? shop.data : undefined,
        isOwner: meData?.role === "owner" || meData?.role === "admin",
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
