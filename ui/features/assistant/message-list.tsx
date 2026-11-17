"use client";

import { AlertCircle, CheckCircle2, Info, Loader2 } from "lucide-react";

import { cn } from "@/lib/utils";

import type { AssistantRegistration, ChatMessage } from "./use-chat";

/** Registration status from the register tool's result. The message text is never consulted. */
export function RegistrationStatus({ registration }: { registration: AssistantRegistration }) {
  const matched = (registration.matched_on ?? []).join(", ");
  const view = {
    created: {
      Icon: CheckCircle2,
      text: `Registered. Customer id ${registration.customer_id ?? "unknown"}.`,
    },
    duplicate: {
      Icon: AlertCircle,
      text: `Not registered: the ${matched || "details"} already belong to another customer.`,
    },
    needs_confirmation: {
      Icon: Info,
      text: "Not registered yet. Use the confirm button to continue.",
    },
    incomplete_form: { Icon: Info, text: "Not registered: the form is incomplete." },
    rejected: { Icon: AlertCircle, text: "Not registered: a value was rejected. Review the form." },
    busy: { Icon: AlertCircle, text: "Not registered: the service is busy. Try again shortly." },
  }[registration.status];
  return (
    <p
      className="mt-2 flex items-start gap-2 border-t border-border pt-2 text-sm font-medium"
    >
      <view.Icon aria-hidden="true" className="mt-0.5 size-4 shrink-0" />
      <span>{view.text}</span>
    </p>
  );
}

type Props = {
  messages: ChatMessage[];
  isPending: boolean;
};

/**
 * The conversation, inside a polite live region that is mounted empty so that screen readers
 * announce each message as it is added.
 */
export function MessageList({ messages, isPending }: Props) {
  return (
    <div
      role="log"
      aria-live="polite"
      aria-relevant="additions text"
      aria-label="Conversation with the assistant"
      tabIndex={0}
      className="flex max-h-80 min-h-12 flex-col gap-3 overflow-y-auto rounded-lg focus-visible:ring-3 focus-visible:ring-ring/50 focus-visible:outline-none"
    >
      {messages.map((message) => (
        <div
          key={message.id}
          className={cn(
            "max-w-[90%] rounded-lg px-3 py-2 text-sm",
            message.role === "user"
              ? "self-end bg-secondary text-secondary-foreground"
              : "self-start bg-muted text-foreground",
          )}
        >
          <p className="sr-only">{message.role === "user" ? "You said:" : "Assistant said:"}</p>
          <p className="whitespace-pre-wrap">{message.text}</p>
          {message.role === "assistant" && message.registration && (
            <RegistrationStatus registration={message.registration} />
          )}
        </div>
      ))}
      {isPending && (
        <p className="flex items-center gap-2 self-start text-sm text-muted-foreground">
          <Loader2 aria-hidden="true" className="size-4 animate-spin" />
          <span>The assistant is thinking</span>
        </p>
      )}
    </div>
  );
}
