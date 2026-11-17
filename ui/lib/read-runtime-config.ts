import type { RuntimeConfig } from "./runtime-config";

/**
 * Read the runtime configuration from the server environment.
 *
 * One build serves every environment, so the API origin is read per request and handed to the
 * browser through a context. Every value is public: nothing here may be a secret.
 */
export function readRuntimeConfig(
  env: Record<string, string | undefined> = process.env,
): RuntimeConfig {
  const apiBaseUrl = env.API_BASE_URL?.trim().replace(/\/+$/, "");
  if (!apiBaseUrl || !/^https?:\/\/[^\s/]+$/.test(apiBaseUrl)) {
    throw new Error(
      "API_BASE_URL must be set to the API origin, such as https://api.example.com.",
    );
  }
  return {
    apiBaseUrl,
    assistantEnabled: env.ASSISTANT_ENABLED !== "false",
    botCheckToken: env.BOT_CHECK_STUB_TOKEN ?? "",
  };
}
