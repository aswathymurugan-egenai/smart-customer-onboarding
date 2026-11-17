"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";

import { ThemeProvider } from "@/components/theme-provider";
import { RuntimeConfigProvider, type RuntimeConfig } from "@/lib/runtime-config";

export function Providers({
  config,
  children,
}: {
  config: RuntimeConfig;
  children: ReactNode;
}) {
  const [queryClient] = useState(
    () => new QueryClient({ defaultOptions: { mutations: { retry: false } } }),
  );
  return (
    <RuntimeConfigProvider value={config}>
      <ThemeProvider>
        <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
      </ThemeProvider>
    </RuntimeConfigProvider>
  );
}
