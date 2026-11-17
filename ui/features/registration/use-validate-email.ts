"use client";

import { useMutation } from "@tanstack/react-query";
import { useMemo } from "react";

import { createApiClient, type EmailValidationResult } from "@/lib/api";
import { useRuntimeConfig } from "@/lib/runtime-config";

/** Check an email address when its field loses focus. */
export function useValidateEmail() {
  const { apiBaseUrl } = useRuntimeConfig();
  const client = useMemo(() => createApiClient(apiBaseUrl), [apiBaseUrl]);

  return useMutation({
    mutationFn: async (email: string): Promise<EmailValidationResult | null> => {
      const { data } = await client.POST("/api/v1/customers/validate", { body: { email } });
      return data ?? null;
    },
  });
}
