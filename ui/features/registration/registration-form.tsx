"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { AlertCircle, Loader2, Lightbulb } from "lucide-react";
import { useCallback, useEffect, useRef, useState, type MutableRefObject } from "react";
import { useForm, useWatch } from "react-hook-form";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { FieldError } from "@/components/ui/field";
import type { CustomerDraft, EmailValidationResult, LastResult } from "@/lib/api";
import { useRuntimeConfig } from "@/lib/runtime-config";

import { AddressFields } from "./address-fields";
import { ContactFields } from "./contact-fields";
import { CustomerFields } from "./customer-fields";
import { interpretProblem, type ProblemBanner } from "./map-problem";
import { ResultCard } from "./result-card";
import {
  EMPTY_VALUES,
  registrationSchema,
  toDraft,
  toRequestBody,
  type RegistrationValues,
} from "./schema";
import { useRegister, type RegisterResult } from "./use-register";
import { useValidateEmail } from "./use-validate-email";

/** What the page can ask of the form. */
export type RegistrationFormApi = {
  getSnapshot: () => CustomerDraft;
  applyEmail: (email: string) => void;
  focusFirstError: () => void;
  getEmailSuggestion: () => string | null;
};

type Props = {
  /** Reports the last answer the form received, for the assistant's context. */
  onResult: (result: LastResult | null) => void;
  apiRef: MutableRefObject<RegistrationFormApi | null>;
  /** Set when the assistant registered the person, so the form shows the success state. */
  registeredElsewhere?: string | null;
  onAskAssistant?: (prompt: string) => void;
};

const EMAIL_SHAPE = /^[^\s@]+@[^\s@]+$/;
const EMAIL_HINT_ID = "email-check-hint";

/**
 * The registration form. This container owns react-hook-form and the two mutations. The
 * field-group components below it are presentational.
 */
export function RegistrationForm({ onResult, apiRef, registeredElsewhere, onAskAssistant }: Props) {
  const { botCheckToken } = useRuntimeConfig();
  const form = useForm<RegistrationValues>({
    resolver: zodResolver(registrationSchema),
    defaultValues: EMPTY_VALUES,
    mode: "onBlur",
    reValidateMode: "onChange",
  });
  const register = useRegister();
  const validateEmail = useValidateEmail();
  const customerType = useWatch({ control: form.control, name: "customer_type" });

  const [created, setCreated] = useState<Extract<RegisterResult, { ok: true }> | null>(null);
  const [banner, setBanner] = useState<ProblemBanner | null>(null);
  const [emailCheck, setEmailCheck] = useState<EmailValidationResult | null>(null);
  const latestCheck = useRef<EmailValidationResult | null>(null);
  latestCheck.current = emailCheck;

  useEffect(() => {
    apiRef.current = {
      getSnapshot: () => toDraft(form.getValues()),
      applyEmail: (email) => {
        form.setValue("email", email, { shouldDirty: true, shouldValidate: true });
        setEmailCheck(null);
      },
      focusFirstError: () => {
        const first = Object.keys(form.formState.errors)[0] as keyof RegistrationValues | undefined;
        if (first) form.setFocus(first);
      },
      getEmailSuggestion: () => latestCheck.current?.suggestion?.suggested_email ?? null,
    };
    return () => {
      apiRef.current = null;
    };
  }, [apiRef, form]);

  const checkEmail = useCallback(
    (email: string) => {
      const trimmed = email.trim();
      if (!EMAIL_SHAPE.test(trimmed)) return;
      validateEmail.mutate(trimmed, {
        onSuccess: (result) => setEmailCheck(result),
      });
    },
    [validateEmail],
  );

  const submit = form.handleSubmit(async (values) => {
    setBanner(null);
    let result: RegisterResult;
    try {
      result = await register.mutateAsync(toRequestBody(values, botCheckToken));
    } catch {
      setBanner({
        title: "Could not reach the server",
        detail: "Check your connection and try again.",
        retryable: true,
      });
      return;
    }
    if (result.ok) {
      setCreated(result);
      onResult({ status: 201, matched_on: [], warnings: result.created.warnings });
      return;
    }
    const outcome = interpretProblem(result.status, result.problem, result.retryAfter);
    for (const problem of outcome.fieldErrors) {
      form.setError(problem.field, { type: "server", message: problem.message });
    }
    setBanner(outcome.banner);
    onResult({
      status: result.status,
      problem_type: result.problem?.type,
      matched_on: result.problem?.matched_on ?? [],
      warnings: [],
    });
    if (outcome.fieldErrors[0]) form.setFocus(outcome.fieldErrors[0].field);
  });

  const registerAnother = () => {
    form.reset(EMPTY_VALUES);
    setCreated(null);
    setBanner(null);
    setEmailCheck(null);
    onResult(null);
  };

  const customerId = created?.created.customer_id ?? registeredElsewhere ?? null;
  if (customerId) {
    return (
      <ResultCard
        customerId={customerId}
        warnings={created?.created.warnings ?? []}
        onAskAssistant={onAskAssistant}
        onRegisterAnother={registerAnother}
      />
    );
  }

  const emailHintIds = emailCheck && (emailCheck.problems.length > 0 || emailCheck.suggestion)
    ? [EMAIL_HINT_ID]
    : [];

  return (
    <form
      noValidate
      onSubmit={submit}
      aria-busy={register.isPending}
      className="flex flex-col gap-8"
    >
      <CustomerFields control={form.control} customerType={customerType} />
      <ContactFields
        control={form.control}
        onEmailBlur={checkEmail}
        onEmailChange={() => setEmailCheck(null)}
        emailHintIds={emailHintIds}
        emailHint={
          emailCheck && (
            <div id={EMAIL_HINT_ID} className="flex flex-col gap-2">
              {emailCheck.problems.map((problem) => (
                <FieldError key={problem.code}>{problem.message}</FieldError>
              ))}
              {emailCheck.suggestion && (
                <div className="flex flex-wrap items-center gap-3 text-sm">
                  <Lightbulb aria-hidden="true" className="size-4 shrink-0 text-muted-foreground" />
                  <span>Did you mean {emailCheck.suggestion.suggested_email}?</span>
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    className="h-8"
                    aria-label={`Use ${emailCheck.suggestion.suggested_email}`}
                    onClick={() => {
                      const suggested = emailCheck.suggestion?.suggested_email;
                      if (suggested) apiRef.current?.applyEmail(suggested);
                    }}
                  >
                    Use
                  </Button>
                </div>
              )}
            </div>
          )
        }
      />
      <AddressFields control={form.control} />

      {banner && (
        <Alert variant="destructive">
          <AlertCircle aria-hidden="true" />
          <AlertTitle>{banner.title}</AlertTitle>
          <AlertDescription className="flex flex-col items-start gap-3">
            <span>{banner.detail}</span>
            {banner.retryable && (
              <Button type="button" variant="outline" className="h-10" onClick={() => void submit()}>
                Try again
              </Button>
            )}
          </AlertDescription>
        </Alert>
      )}

      <p className="text-sm text-muted-foreground">
        We store the details you enter in BigQuery for customer reporting. Gemini on Google Cloud
        checks your email for typos and your details for possible duplicates. OpenAI is used only
        when the fallback model is switched on.
      </p>

      <div className="flex flex-col sm:flex-row sm:justify-end">
        <Button type="submit" className="h-10 w-full sm:w-auto sm:px-6" disabled={register.isPending}>
          {register.isPending && <Loader2 aria-hidden="true" className="animate-spin" data-icon="inline-start" />}
          {register.isPending ? "Registering" : "Register"}
        </Button>
      </div>
    </form>
  );
}
