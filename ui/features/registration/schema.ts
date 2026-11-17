import { z } from "zod";

import type { CustomerDraft, CustomerInput } from "@/lib/api";

export const TAX_ID_TYPES = ["us_ein", "gb_vat", "in_pan", "other"] as const;
export type TaxIdType = (typeof TAX_ID_TYPES)[number];

export const TAX_ID_LABELS: Record<TaxIdType, string> = {
  us_ein: "US EIN",
  gb_vat: "UK VAT",
  in_pan: "India PAN",
  other: "Other",
};

const text = (max: number) => z.string().trim().max(max, `Use ${max} characters or fewer.`);

/**
 * The form's shape. It mirrors the server's required fields and lengths so a person sees
 * most problems before submitting, and the server stays authoritative for everything else.
 */
export const registrationSchema = z
  .object({
    customer_type: z.enum(["individual", "business"]),
    given_name: z
      .string()
      .trim()
      .min(1, "Enter a given name.")
      .max(100, "Use 100 characters or fewer."),
    family_name: text(100),
    company_name: text(200),
    email: z
      .string()
      .trim()
      .min(1, "Enter an email address.")
      .max(254, "Use 254 characters or fewer.")
      .regex(/^[^\s@]+@[^\s@]+$/, "Enter an email address such as name@example.com."),
    phone: text(32),
    tax_id_type: z.enum(["", ...TAX_ID_TYPES]),
    tax_id: text(40),
    address: z.object({
      line1: text(200),
      line2: text(200),
      city: text(100),
      region: text(100),
      postal_code: text(20),
      country_code: text(2),
    }),
  })
  .superRefine((values, ctx) => {
    if (values.customer_type === "business" && values.company_name === "") {
      ctx.addIssue({ code: "custom", path: ["company_name"], message: "Enter the company name." });
    }
    if (values.tax_id_type !== "" && values.tax_id === "") {
      ctx.addIssue({ code: "custom", path: ["tax_id"], message: "Enter the tax ID." });
    }
    if (values.tax_id_type === "" && values.tax_id !== "") {
      ctx.addIssue({
        code: "custom",
        path: ["tax_id_type"],
        message: "Choose the tax ID type.",
      });
    }
    const { line1, line2, city, region, postal_code, country_code } = values.address;
    const addressStarted = [line1, line2, city, region, postal_code, country_code].some(
      (part) => part !== "",
    );
    if (addressStarted) {
      if (line1 === "") {
        ctx.addIssue({ code: "custom", path: ["address", "line1"], message: "Enter address line 1." });
      }
      if (city === "") {
        ctx.addIssue({ code: "custom", path: ["address", "city"], message: "Enter the city." });
      }
      if (!/^[A-Za-z]{2}$/.test(country_code)) {
        ctx.addIssue({
          code: "custom",
          path: ["address", "country_code"],
          message: "Enter a two-letter country code, such as US.",
        });
      }
    }
  });

export type RegistrationValues = z.infer<typeof registrationSchema>;

export const EMPTY_VALUES: RegistrationValues = {
  customer_type: "individual",
  given_name: "",
  family_name: "",
  company_name: "",
  email: "",
  phone: "",
  tax_id_type: "",
  tax_id: "",
  address: { line1: "", line2: "", city: "", region: "", postal_code: "", country_code: "" },
};

/** Every field path the form can show an error under. */
export type FieldPath =
  | "customer_type"
  | "given_name"
  | "family_name"
  | "company_name"
  | "email"
  | "phone"
  | "tax_id_type"
  | "tax_id"
  | "address.line1"
  | "address.line2"
  | "address.city"
  | "address.region"
  | "address.postal_code"
  | "address.country_code";

export const FIELD_PATHS: readonly FieldPath[] = [
  "customer_type",
  "given_name",
  "family_name",
  "company_name",
  "email",
  "phone",
  "tax_id_type",
  "tax_id",
  "address.line1",
  "address.line2",
  "address.city",
  "address.region",
  "address.postal_code",
  "address.country_code",
];

type PartialDraft = Omit<CustomerDraft, "address"> & { address?: Record<string, string> };

/** Keep only the parts of the form that hold a value. */
function compact(values: RegistrationValues): PartialDraft {
  const draft: PartialDraft = { customer_type: values.customer_type };
  const optional: Array<[keyof CustomerDraft, string]> = [
    ["given_name", values.given_name],
    ["family_name", values.family_name],
    ["company_name", values.customer_type === "business" ? values.company_name : ""],
    ["email", values.email],
    ["phone", values.phone],
    ["tax_id_type", values.tax_id_type],
    ["tax_id", values.tax_id],
  ];
  for (const [key, value] of optional) {
    if (value !== "") (draft as Record<string, unknown>)[key] = value;
  }
  const address = Object.fromEntries(
    Object.entries(values.address)
      .filter(([, value]) => value !== "")
      .map(([key, value]) => [key, key === "country_code" ? value.toUpperCase() : value]),
  );
  if (Object.keys(address).length > 0) draft.address = address;
  return draft;
}

/** The register request body. Blank optional fields are left out. */
export function toRequestBody(values: RegistrationValues, botToken: string): CustomerInput {
  return { ...(compact(values) as unknown as CustomerInput), bot_token: botToken };
}

/** The form as it stands, in the shape the assistant receives with each turn. */
export function toDraft(values: RegistrationValues): CustomerDraft {
  return compact(values) as unknown as CustomerDraft;
}
