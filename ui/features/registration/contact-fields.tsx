"use client";

import { useId, type ReactNode } from "react";
import { Controller, type Control } from "react-hook-form";

import { Field, FieldDescription, FieldError, FieldGroup, FieldLabel, FieldLegend, FieldSet } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";

import { TAX_ID_LABELS, TAX_ID_TYPES, type RegistrationValues } from "./schema";
import { CONTROL_CLASS, TextField } from "./text-field";

const NO_TAX_ID = "none";

type Props = {
  control: Control<RegistrationValues>;
  /** Check the address when the email field loses focus. */
  onEmailBlur: (email: string) => void;
  /** Called when the email is edited, so a stale check can be cleared. */
  onEmailChange: () => void;
  /** The result of the last email check, shown under the email field. */
  emailHint: ReactNode;
  emailHintIds: string[];
};

/** How to reach the person: the email at full width, then phone and tax ID as a pair. */
export function ContactFields({ control, onEmailBlur, onEmailChange, emailHint, emailHintIds }: Props) {
  return (
    <FieldSet>
      <FieldLegend>Contact</FieldLegend>
      <FieldGroup className="gap-6">
        <TextField
          control={control}
          name="email"
          label="Email"
          type="email"
          autoComplete="email"
          inputMode="email"
          onValueBlur={onEmailBlur}
          onValueChange={onEmailChange}
          below={emailHint}
          belowIds={emailHintIds}
        />
        <div className="grid gap-6 md:grid-cols-2">
          <TextField
            control={control}
            name="phone"
            label="Phone"
            optional
            type="tel"
            autoComplete="tel"
            inputMode="tel"
            description="Include the country code, such as +1."
          />
          <TaxIdField control={control} />
        </div>
      </FieldGroup>
    </FieldSet>
  );
}

/** A compact tax-ID type select joined to the tax-ID input. */
function TaxIdField({ control }: { control: Control<RegistrationValues> }) {
  const id = useId();
  const typeErrorId = `${id}-type-error`;
  const idErrorId = `${id}-error`;
  const descriptionId = `${id}-description`;
  return (
    <Controller
      control={control}
      name="tax_id"
      render={({ field: idField, fieldState: idState }) => (
        <Controller
          control={control}
          name="tax_id_type"
          render={({ field: typeField, fieldState: typeState }) => {
            const invalid = idState.invalid || typeState.invalid;
            const describedBy = [
              typeState.invalid ? typeErrorId : null,
              idState.invalid ? idErrorId : null,
              descriptionId,
            ]
              .filter(Boolean)
              .join(" ");
            return (
              <Field data-invalid={invalid}>
                <FieldLabel htmlFor={id}>
                  Tax ID{" "}
                  <span className="font-normal text-muted-foreground">(optional)</span>
                </FieldLabel>
                <div className="flex">
                  <Select
                    value={typeField.value === "" ? NO_TAX_ID : (typeField.value as string)}
                    onValueChange={(value) => typeField.onChange(value === NO_TAX_ID ? "" : value)}
                  >
                    <SelectTrigger
                      aria-label="Tax ID type"
                      aria-invalid={typeState.invalid}
                      aria-describedby={describedBy || undefined}
                      className={`${CONTROL_CLASS} w-32 shrink-0 rounded-r-none focus-visible:z-10`}
                    >
                      <SelectValue placeholder="Type" />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value={NO_TAX_ID}>None</SelectItem>
                      {TAX_ID_TYPES.map((type) => (
                        <SelectItem key={type} value={type}>
                          {TAX_ID_LABELS[type]}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  <Input
                    {...idField}
                    id={id}
                    value={idField.value as string}
                    className={`${CONTROL_CLASS} -ml-px rounded-l-none focus-visible:z-10`}
                    autoComplete="off"
                    aria-invalid={idState.invalid}
                    aria-describedby={describedBy || undefined}
                  />
                </div>
                {typeState.invalid && <FieldError id={typeErrorId} errors={[typeState.error]} />}
                {idState.invalid && <FieldError id={idErrorId} errors={[idState.error]} />}
                <FieldDescription id={descriptionId}>
                  Stored only as a keyed hash and its last four characters.
                </FieldDescription>
              </Field>
            );
          }}
        />
      )}
    />
  );
}
