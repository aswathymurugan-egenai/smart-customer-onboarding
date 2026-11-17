import createClient from "openapi-fetch";

import type { components, paths } from "./api-schema";

export type ApiSchemas = components["schemas"];
export type CustomerInput = ApiSchemas["CustomerInput"];
export type CustomerDraft = ApiSchemas["CustomerDraft"];
export type RegistrationCreated = ApiSchemas["RegistrationCreated"];
export type EmailValidationResult = ApiSchemas["EmailValidationResult"];
export type ProblemDetails = ApiSchemas["ProblemDetails"];
export type TypoWarning = ApiSchemas["TypoWarning"];
export type DuplicateWarning = ApiSchemas["DuplicateWarning"];
export type ChatRequest = ApiSchemas["ChatRequest"];
export type AssistantReply = ApiSchemas["AssistantReply"];
export type LastResult = ApiSchemas["LastResult"];
export type AdvisoryWarning = TypoWarning | DuplicateWarning;

/** A typed client for the registration API at `baseUrl`, built from the committed spec. */
export function createApiClient(baseUrl: string) {
  return createClient<paths>({ baseUrl });
}

export type ApiClient = ReturnType<typeof createApiClient>;
