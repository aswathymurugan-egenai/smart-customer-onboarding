"use client";

import { Bot, SendHorizontal } from "lucide-react";
import { useId, useState, type FormEvent } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

import { ConfirmRegistrationDialog } from "./confirm-registration-dialog";
import { MessageList } from "./message-list";
import type { ChatState, SuggestedAction } from "./use-chat";

type Props = {
  chat: ChatState;
  /** Applies the email correction the form last suggested. */
  onApplyEmailSuggestion: () => void;
  /** Moves focus to the first field with an error. */
  onReviewField: () => void;
};

const ACTION_LABELS: Record<SuggestedAction, string> = {
  apply_email_suggestion: "Use the suggested email",
  confirm_registration: "Confirm registration",
  review_field: "Review the fields",
};

/**
 * The assistant: a conversation, the buttons the latest answer suggests, and a message box.
 * It renders the same way beside the form on wide screens and inside the bottom drawer on
 * narrow ones.
 */
export function AssistantPanel({ chat, onApplyEmailSuggestion, onReviewField }: Props) {
  const inputId = useId();
  const [draft, setDraft] = useState("");
  const [confirming, setConfirming] = useState(false);

  const latest = [...chat.messages].reverse().find((message) => message.role === "assistant");
  const actions = latest?.role === "assistant" && !chat.isPending ? latest.actions : [];

  const submit = (event: FormEvent) => {
    event.preventDefault();
    const text = draft.trim();
    if (!text || chat.isPending) return;
    chat.send(text);
    setDraft("");
  };

  const run = (action: SuggestedAction) => {
    if (action === "apply_email_suggestion") onApplyEmailSuggestion();
    else if (action === "review_field") onReviewField();
    else setConfirming(true);
  };

  return (
    <section aria-labelledby={`${inputId}-title`} className="flex flex-col gap-4">
      <div className="flex items-center gap-2">
        <Bot aria-hidden="true" className="size-5" />
        <h2 id={`${inputId}-title`} className="font-heading text-base font-medium">
          Signup assistant
        </h2>
      </div>
      <p className="text-sm text-muted-foreground">
        Ask about an error or a warning, or ask for help finishing the form. The assistant can
        register you after you confirm.
      </p>

      <MessageList messages={chat.messages} isPending={chat.isPending} />

      {actions.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {actions.map((action) => (
            <Button
              key={action}
              type="button"
              variant={action === "confirm_registration" ? "default" : "outline"}
              className="h-10"
              onClick={() => run(action)}
            >
              {ACTION_LABELS[action]}
            </Button>
          ))}
        </div>
      )}

      <form onSubmit={submit} className="flex flex-col gap-2">
        <Label htmlFor={inputId} className="text-sm font-medium">
          Message the assistant
        </Label>
        <div className="flex gap-2">
          <Input
            id={inputId}
            className="h-10"
            value={draft}
            maxLength={2000}
            autoComplete="off"
            onChange={(event) => setDraft(event.target.value)}
          />
          <Button
            type="submit"
            className="h-10 shrink-0"
            disabled={chat.isPending || draft.trim() === ""}
          >
            <SendHorizontal aria-hidden="true" data-icon="inline-start" />
            Send
          </Button>
        </div>
      </form>

      <ConfirmRegistrationDialog
        open={confirming}
        onOpenChange={setConfirming}
        onConfirm={() => {
          setConfirming(false);
          chat.send("I confirm the registration.", "confirm_registration");
        }}
      />
    </section>
  );
}
