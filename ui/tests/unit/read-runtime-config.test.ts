import { describe, expect, it } from "vitest";

import { readRuntimeConfig } from "@/lib/read-runtime-config";

describe("readRuntimeConfig", () => {
  it("reads the API origin and drops a trailing slash", () => {
    expect(readRuntimeConfig({ API_BASE_URL: "https://api.example.com/" }).apiBaseUrl).toBe(
      "https://api.example.com",
    );
  });

  it.each([undefined, "", "api.example.com", "ftp://api.example.com", "https://api.example.com/v1"])(
    "refuses %s",
    (value) => {
      expect(() => readRuntimeConfig({ API_BASE_URL: value })).toThrow(/API_BASE_URL/);
    },
  );

  it("keeps the assistant on unless it is switched off", () => {
    const base = { API_BASE_URL: "http://localhost:8000" };

    expect(readRuntimeConfig(base).assistantEnabled).toBe(true);
    expect(readRuntimeConfig({ ...base, ASSISTANT_ENABLED: "false" }).assistantEnabled).toBe(false);
  });

  it("passes the bot-check token through and defaults it to empty", () => {
    const base = { API_BASE_URL: "http://localhost:8000" };

    expect(readRuntimeConfig(base).botCheckToken).toBe("");
    expect(readRuntimeConfig({ ...base, BOT_CHECK_STUB_TOKEN: "local" }).botCheckToken).toBe("local");
  });
});
