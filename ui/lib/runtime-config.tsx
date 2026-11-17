"use client";

import { createContext, useContext, type ReactNode } from "react";

/** Public values the server reads from its own environment on every request. */
export type RuntimeConfig = {
  /** Origin of the registration API, without a trailing slash. */
  apiBaseUrl: string;
  /** False hides the assistant panel. */
  assistantEnabled: boolean;
  /** Token sent as `bot_token` on register and check-duplicate. Empty when no check is set up. */
  botCheckToken: string;
};

const RuntimeConfigContext = createContext<RuntimeConfig | null>(null);

export function RuntimeConfigProvider({
  value,
  children,
}: {
  value: RuntimeConfig;
  children: ReactNode;
}) {
  return (
    <RuntimeConfigContext.Provider value={value}>
      {children}
    </RuntimeConfigContext.Provider>
  );
}

export function useRuntimeConfig(): RuntimeConfig {
  const config = useContext(RuntimeConfigContext);
  if (config === null) {
    throw new Error("useRuntimeConfig must be used inside RuntimeConfigProvider.");
  }
  return config;
}
