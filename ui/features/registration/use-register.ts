"use client";

import { useMutation } from "@tanstack/react-query";
import { useMemo, useRef } from "react";

import { createApiClient, type CustomerInput, type ProblemDetails, type RegistrationCreated } from "@/lib/api";
import { useRuntimeConfig } from "@/lib/runtime-config";

export type RegisterResult =
  | { ok: true; created: RegistrationCreated; replayed: boolean }
  | { ok: false; status: number; problem?: ProblemDetails; retryAfter: string | null };

/**
 * Submit a registration. One `Idempotency-Key` is generated per form session and reused for
 * every attempt, so a retry after a timeout cannot register the person twice. A completed
 * registration starts a new session.
 */
export function useRegister() {
  const { apiBaseUrl } = useRuntimeConfig();
  const client = useMemo(() => createApiClient(apiBaseUrl), [apiBaseUrl]);
  const keyRef = useRef<string | null>(null);

  const mutation = useMutation({
    mutationFn: async (body: CustomerInput): Promise<RegisterResult> => {
      keyRef.current ??= crypto.randomUUID();
      const { data, error, response } = await client.POST("/api/v1/customers/register", {
        body,
        params: { header: { "Idempotency-Key": keyRef.current } },
      });
      if (data) {
        keyRef.current = null;
        return {
          ok: true,
          created: data,
          replayed: response.headers.get("Idempotent-Replayed") === "true",
        };
      }
      return {
        ok: false,
        status: response.status,
        problem: error as ProblemDetails | undefined,
        retryAfter: response.headers.get("Retry-After"),
      };
    },
  });

  return mutation;
}
