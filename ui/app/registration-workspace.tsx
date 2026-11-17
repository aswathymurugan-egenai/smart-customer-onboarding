"use client";

import { useCallback, useRef, useState } from "react";

import { Card, CardContent, CardDescription, CardHeader } from "@/components/ui/card";
import { AssistantDrawer } from "@/features/assistant/assistant-drawer";
import { AssistantPanel } from "@/features/assistant/assistant-panel";
import { useChat } from "@/features/assistant/use-chat";
import {
  RegistrationForm,
  type RegistrationFormApi,
} from "@/features/registration/registration-form";
import type { LastResult } from "@/lib/api";
import { useRuntimeConfig } from "@/lib/runtime-config";

const WIDE_SCREEN = "(min-width: 1024px)";
const CARD_SPACING = "[--card-spacing:--spacing(4)] md:[--card-spacing:--spacing(6)]";

/**
 * The form and the assistant side by side. This client component holds what they share: the
 * form's current values, the last answer the form received, and the conversation.
 */
export function RegistrationWorkspace() {
  const { assistantEnabled } = useRuntimeConfig();
  const formApi = useRef<RegistrationFormApi | null>(null);
  const lastResult = useRef<LastResult | null>(null);
  const [registeredId, setRegisteredId] = useState<string | null>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);

  const chat = useChat({
    getSnapshot: () => formApi.current?.getSnapshot() ?? {},
    getLastResult: () => lastResult.current,
    onRegistered: setRegisteredId,
  });

  const askAssistant = useCallback(
    (prompt: string) => {
      if (!window.matchMedia(WIDE_SCREEN).matches) setDrawerOpen(true);
      chat.send(prompt);
    },
    [chat],
  );

  const panel = (
    <AssistantPanel
      chat={chat}
      onApplyEmailSuggestion={() => {
        const suggestion = formApi.current?.getEmailSuggestion();
        if (suggestion) formApi.current?.applyEmail(suggestion);
        setDrawerOpen(false);
      }}
      onReviewField={() => {
        setDrawerOpen(false);
        formApi.current?.focusFirstError();
      }}
    />
  );

  return (
    <>
      <div className="grid items-start gap-8 lg:grid-cols-[minmax(0,1fr)_24rem]">
        <Card className={CARD_SPACING}>
          <CardHeader>
            <h2 className="font-heading text-lg font-medium">Your details</h2>
            <CardDescription>
              Fields marked optional can be left blank. We check your email as you leave the field.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <RegistrationForm
              apiRef={formApi}
              registeredElsewhere={registeredId}
              onResult={(result) => {
                lastResult.current = result;
                if (result === null) setRegisteredId(null);
              }}
              onAskAssistant={assistantEnabled ? askAssistant : undefined}
            />
          </CardContent>
        </Card>

        {assistantEnabled && (
          <aside aria-label="Signup assistant" className="hidden lg:sticky lg:top-6 lg:block">
            <Card className={CARD_SPACING}>
              <CardContent>{panel}</CardContent>
            </Card>
          </aside>
        )}
      </div>

      {assistantEnabled && (
        <AssistantDrawer open={drawerOpen} onOpenChange={setDrawerOpen}>
          {panel}
        </AssistantDrawer>
      )}
    </>
  );
}
