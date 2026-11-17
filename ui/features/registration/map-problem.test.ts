import { describe, expect, it } from "vitest";

import type { ProblemDetails } from "@/lib/api";

import { DUPLICATE_MESSAGE, interpretProblem, pointerToField } from "./map-problem";

function problem(overrides: Partial<ProblemDetails>): ProblemDetails {
  return {
    type: "urn:p:x",
    title: "Title",
    status: 422,
    detail: "Detail",
    instance: "/x",
    request_id: "r",
    errors: [],
    ...overrides,
  };
}

describe("pointerToField", () => {
  it.each([
    ["/email", "email"],
    ["/tax_id", "tax_id"],
    ["/address/city", "address.city"],
    ["/address/country_code", "address.country_code"],
  ])("maps %s to %s", (pointer, field) => {
    expect(pointerToField(pointer)).toBe(field);
  });

  it.each(["/headers/Idempotency-Key", "/bot_token", "", "/address"])(
    "has no field for %s",
    (pointer) => {
      expect(pointerToField(pointer)).toBeNull();
    },
  );
});

describe("interpretProblem", () => {
  it("names every matched key on a 409", () => {
    const outcome = interpretProblem(409, problem({ status: 409, matched_on: ["phone", "tax_id"] }), null);

    expect(outcome.fieldErrors).toEqual([
      { field: "phone", message: DUPLICATE_MESSAGE },
      { field: "tax_id", message: DUPLICATE_MESSAGE },
    ]);
    expect(outcome.banner).toBeNull();
  });

  it("puts a 422 pointer under its field and shows no banner", () => {
    const outcome = interpretProblem(
      422,
      problem({ errors: [{ pointer: "/email", code: "email-disposable", message: "Disposable." }] }),
      null,
    );

    expect(outcome.fieldErrors).toEqual([{ field: "email", message: "Disposable." }]);
    expect(outcome.banner).toBeNull();
  });

  it("falls back to a banner when a 422 pointer has no field", () => {
    const outcome = interpretProblem(
      422,
      problem({ errors: [{ pointer: "/headers/Idempotency-Key", code: "x", message: "Bad key." }] }),
      null,
    );

    expect(outcome.fieldErrors).toEqual([]);
    expect(outcome.banner).toMatchObject({ detail: "Bad key.", retryable: false });
  });

  it.each([
    [429, "42", "Try again in 42 seconds.", false],
    [429, null, "Wait a moment and try again.", false],
    [429, "300", "Try again in about 5 minutes.", false],
    [503, "60", "Try again in 60 seconds.", true],
    [500, null, "Try again in a moment.", true],
  ])("describes a %i with Retry-After %s", (status, retryAfter, text, retryable) => {
    const outcome = interpretProblem(status, undefined, retryAfter);

    expect(outcome.banner?.detail).toContain(text);
    expect(outcome.banner?.retryable).toBe(retryable);
  });
});
