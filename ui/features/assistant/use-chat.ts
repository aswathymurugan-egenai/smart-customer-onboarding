"use client";

import { useMutation } from "@tanstack/react-query";
import { useCallback, useId, useMemo, useState } from "react";

import {
  createApiClient,
  type AssistantReply,
  type CustomerDraft,
  type LastResult,
  type ProblemDetails,
} from "@/lib/api";
import { useRuntimeConfig } from "@/lib/runtime-config";

export type AssistantRegistration = NonNullable<AssistantReply["registration"]>;
export type SuggestedAction = AssistantReply["suggested_actions"][number];

export type ChatMessage =
  | { id: string; role: "user"; text: string }
  | {
      id: string;
      role: "assistant";
      text: string;
      registration: AssistantRegistration | null;
      actions: SuggestedAction[];
    };

type NewMessage = ChatMessage extends infer M ? (M extends unknown ? Omit<M, "id"> : never) : never;

export type ChatState = {
  messages: ChatMessage[];
  isPending: boolean;
  send: (message: string, action?: "confirm_registration") => void;
};

type Options = {
  getSnapshot: () => CustomerDraft;
  getLastResult: () => LastResult | null;
  /** Called with the customer id when the assistant's register tool created a customer. */
  onRegistered?: (customerId: string) => void;
};

const SESSION_KEY = "signup-assistant-session";
const UNAVAILABLE_TEXT =
  "The assistant is unavailable right now. You can still complete the form yourself.";

/** The conversation id lives in sessionStorage. This runs only in event handlers, never during render. */
function conversationId(): string {
  let id = window.sessionStorage.getItem(SESSION_KEY);
  if (!id) {
    id = crypto.randomUUID();
    window.sessionStorage.setItem(SESSION_KEY, id);
  }
  return id;
}

function failureText(status: number, problem: ProblemDetails | undefined, retryAfter: string | null): string {
  if (status === 429) {
    return retryAfter && /^\d+$/.test(retryAfter)
      ? `You are sending messages too quickly. Try again in ${retryAfter} seconds.`
      : "You are sending messages too quickly. Wait a moment and try again.";
  }
  if (status === 422) return problem?.detail ?? "That message could not be sent.";
  return UNAVAILABLE_TEXT;
}

/**
 * Chat with the assistant. Each turn sends the form as it stands and the last answer the form
 * received. The registration status shown with a reply comes from the reply's `registration`
 * field, which the API copies from the register tool, and never from the message text.
 */
export function useChat({ getSnapshot, getLastResult, onRegistered }: Options): ChatState {
  const { apiBaseUrl } = useRuntimeConfig();
  const client = useMemo(() => createApiClient(apiBaseUrl), [apiBaseUrl]);
  const idPrefix = useId();
  const [messages, setMessages] = useState<ChatMessage[]>([]);

  const append = useCallback(
    (message: NewMessage) =>
      setMessages((current) => [...current, { ...message, id: `${idPrefix}-${current.length}` } as ChatMessage]),
    [idPrefix],
  );

  const mutation = useMutation({
    mutationFn: async ({ message, action }: { message: string; action?: "confirm_registration" }) => {
      const lastResult = getLastResult();
      const { data, error, response } = await client.POST("/api/v1/agent/chat", {
        body: {
          session_id: conversationId(),
          message,
          form_snapshot: getSnapshot(),
          ...(lastResult ? { last_result: lastResult } : {}),
          ...(action ? { action } : {}),
        },
      });
      return { data, problem: error as ProblemDetails | undefined, response };
    },
    onSuccess: ({ data, problem, response }) => {
      if (data) {
        append({
          role: "assistant",
          text: data.message,
          registration: data.registration ?? null,
          actions: data.suggested_actions,
        });
        if (data.registration?.status === "created" && data.registration.customer_id) {
          onRegistered?.(data.registration.customer_id);
        }
        return;
      }
      append({
        role: "assistant",
        text: failureText(response.status, problem, response.headers.get("Retry-After")),
        registration: null,
        actions: [],
      });
    },
    onError: () =>
      append({ role: "assistant", text: UNAVAILABLE_TEXT, registration: null, actions: [] }),
  });

  const send = useCallback(
    (message: string, action?: "confirm_registration") => {
      append({ role: "user", text: message });
      mutation.mutate({ message, action });
    },
    [append, mutation],
  );

  return { messages, isPending: mutation.isPending, send };
}
