"use client";

import { CheckCircle2, MessageCircle, RotateCcw } from "lucide-react";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import type { AdvisoryWarning } from "@/lib/api";

type Props = {
  customerId: string;
  warnings: AdvisoryWarning[];
  /** Offered only when the assistant is available. */
  onAskAssistant?: (prompt: string) => void;
  onRegisterAnother: () => void;
};

function describe(warning: AdvisoryWarning): string {
  return warning.message;
}

/** The success state: the customer id and any warnings that came with the 201. */
export function ResultCard({ customerId, warnings, onAskAssistant, onRegisterAnother }: Props) {
  return (
    <section aria-labelledby="result-title" className="flex flex-col gap-6">
      <div className="flex items-start gap-3">
        <CheckCircle2 aria-hidden="true" className="mt-0.5 size-6 shrink-0 text-primary" />
        <div className="flex flex-col gap-1">
          <h2 id="result-title" className="text-lg font-medium">
            You are registered
          </h2>
          <p className="text-sm text-muted-foreground">
            Customer id <code className="rounded bg-muted px-1.5 py-0.5 font-mono text-foreground">{customerId}</code>
          </p>
        </div>
      </div>

      {warnings.length > 0 && (
        <div className="flex flex-col gap-4">
          <h3 className="text-sm font-medium">Worth a look</h3>
          <ul className="flex flex-col gap-4">
            {warnings.map((warning) => (
              <li key={`${warning.code}-${warning.message}`}>
                <Alert>
                  <AlertTitle>
                    {warning.code === "possible_typo" ? "Possible typo" : "Possible duplicate"}
                  </AlertTitle>
                  <AlertDescription className="flex flex-col items-start gap-3">
                    <span>{describe(warning)}</span>
                    {onAskAssistant && (
                      <Button
                        type="button"
                        variant="outline"
                        className="h-10"
                        onClick={() =>
                          onAskAssistant(`Please explain this warning: ${describe(warning)}`)
                        }
                      >
                        <MessageCircle aria-hidden="true" data-icon="inline-start" />
                        Ask the assistant
                      </Button>
                    )}
                  </AlertDescription>
                </Alert>
              </li>
            ))}
          </ul>
        </div>
      )}

      <div>
        <Button type="button" variant="outline" className="h-10" onClick={onRegisterAnother}>
          <RotateCcw aria-hidden="true" data-icon="inline-start" />
          Register another customer
        </Button>
      </div>
    </section>
  );
}
