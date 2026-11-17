"use client";

import type { Control } from "react-hook-form";

import { FieldGroup, FieldLegend, FieldSet } from "@/components/ui/field";

import type { RegistrationValues } from "./schema";
import { TextField } from "./text-field";

/** An optional postal address. It improves likely-duplicate matching. */
export function AddressFields({ control }: { control: Control<RegistrationValues> }) {
  return (
    <FieldSet>
      <FieldLegend>Address (optional)</FieldLegend>
      <FieldGroup className="gap-6">
        <TextField
          control={control}
          name="address.line1"
          label="Address line 1"
          autoComplete="address-line1"
        />
        <TextField
          control={control}
          name="address.line2"
          label="Address line 2"
          optional
          autoComplete="address-line2"
        />
        <div className="grid gap-6 md:grid-cols-2">
          <TextField control={control} name="address.city" label="City" autoComplete="address-level2" />
          <TextField
            control={control}
            name="address.region"
            label="State or region"
            optional
            autoComplete="address-level1"
          />
        </div>
        <div className="grid gap-6 md:grid-cols-2">
          <TextField
            control={control}
            name="address.postal_code"
            label="Postal code"
            optional
            autoComplete="postal-code"
          />
          <TextField
            control={control}
            name="address.country_code"
            label="Country code"
            autoComplete="country"
            maxLength={2}
            transform={(value) => value.toUpperCase()}
            description="Two letters, such as US."
          />
        </div>
      </FieldGroup>
    </FieldSet>
  );
}
