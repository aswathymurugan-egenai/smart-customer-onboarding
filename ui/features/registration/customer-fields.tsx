"use client";

import { useId } from "react";
import { Controller, type Control } from "react-hook-form";

import { Field, FieldGroup, FieldLabel, FieldLegend, FieldSet } from "@/components/ui/field";
import { Label } from "@/components/ui/label";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";

import type { RegistrationValues } from "./schema";
import { TextField } from "./text-field";

type Props = {
  control: Control<RegistrationValues>;
  customerType: RegistrationValues["customer_type"];
};

/** Who is registering: the type, the name, and for a business the company name. */
export function CustomerFields({ control, customerType }: Props) {
  const typeLabelId = useId();
  return (
    <FieldSet>
      <FieldLegend>Customer</FieldLegend>
      <FieldGroup className="gap-6">
        <Controller
          control={control}
          name="customer_type"
          render={({ field }) => (
            <Field>
              <FieldLabel id={typeLabelId}>Registering as</FieldLabel>
              <RadioGroup
                aria-labelledby={typeLabelId}
                value={field.value as string}
                onValueChange={field.onChange}
                className="flex flex-row gap-6"
              >
                {(["individual", "business"] as const).map((value) => (
                  <div key={value} className="flex items-center gap-2">
                    <RadioGroupItem id={`customer-type-${value}`} value={value} />
                    <Label htmlFor={`customer-type-${value}`} className="text-sm">
                      {value === "individual" ? "Individual" : "Business"}
                    </Label>
                  </div>
                ))}
              </RadioGroup>
            </Field>
          )}
        />
        <div className="grid gap-6 md:grid-cols-2">
          <TextField control={control} name="given_name" label="Given name" autoComplete="given-name" />
          <TextField
            control={control}
            name="family_name"
            label="Family name"
            optional
            autoComplete="family-name"
          />
        </div>
        {customerType === "business" && (
          <TextField
            control={control}
            name="company_name"
            label="Company name"
            autoComplete="organization"
          />
        )}
      </FieldGroup>
    </FieldSet>
  );
}
