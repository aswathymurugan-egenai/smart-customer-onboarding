"use client";

import { useId, type ReactNode } from "react";
import { Controller, type Control } from "react-hook-form";

import { Field, FieldDescription, FieldError, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";

import type { FieldPath, RegistrationValues } from "./schema";

/** Touch-friendly control height shared by every input in the form. */
export const CONTROL_CLASS = "h-10";

type TextFieldProps = {
  control: Control<RegistrationValues>;
  name: FieldPath;
  label: string;
  optional?: boolean;
  description?: string;
  type?: string;
  autoComplete?: string;
  inputMode?: "text" | "email" | "tel" | "numeric";
  maxLength?: number;
  /** Rewrites the value as the person types, such as upper-casing a country code. */
  transform?: (value: string) => string;
  /** Called with the value when the field loses focus. */
  onValueBlur?: (value: string) => void;
  /** Called when the person edits the value. */
  onValueChange?: (value: string) => void;
  /** Content shown directly under the control and its error, such as a suggestion. */
  below?: ReactNode;
  /** Ids of elements inside `below` that describe the control. */
  belowIds?: string[];
};

/**
 * A labeled text input wired to react-hook-form.
 *
 * The label sits above the control, the error directly under it, and help text under the
 * error. The control carries `aria-invalid` and `aria-describedby` so assistive technology
 * announces the error with the field.
 */
export function TextField({
  control,
  name,
  label,
  optional = false,
  description,
  type = "text",
  autoComplete,
  inputMode,
  maxLength,
  transform,
  onValueBlur,
  onValueChange,
  below,
  belowIds = [],
}: TextFieldProps) {
  const id = useId();
  const errorId = `${id}-error`;
  const descriptionId = `${id}-description`;
  return (
    <Controller
      control={control}
      name={name}
      render={({ field, fieldState }) => {
        const describedBy = [
          fieldState.invalid ? errorId : null,
          ...belowIds,
          description ? descriptionId : null,
        ]
          .filter(Boolean)
          .join(" ");
        return (
          <Field data-invalid={fieldState.invalid}>
            <FieldLabel htmlFor={id}>
              {label}
              {optional && (
                <>
                  {" "}
                  <span className="font-normal text-muted-foreground">(optional)</span>
                </>
              )}
            </FieldLabel>
            <Input
              {...field}
              id={id}
              type={type}
              className={CONTROL_CLASS}
              autoComplete={autoComplete}
              inputMode={inputMode}
              maxLength={maxLength}
              aria-invalid={fieldState.invalid}
              aria-describedby={describedBy || undefined}
              value={field.value as string}
              onChange={(event) => {
                const next = transform ? transform(event.target.value) : event.target.value;
                field.onChange(next);
                onValueChange?.(next);
              }}
              onBlur={() => {
                field.onBlur();
                onValueBlur?.(field.value as string);
              }}
            />
            {fieldState.invalid && <FieldError id={errorId} errors={[fieldState.error]} />}
            {below}
            {description && <FieldDescription id={descriptionId}>{description}</FieldDescription>}
          </Field>
        );
      }}
    />
  );
}
