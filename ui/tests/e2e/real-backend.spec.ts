import { expect, test } from "./fixtures";

// Runs against the API on the in-memory store: E2E_REAL_BACKEND=1 npm run e2e.
// The address uses a real mail domain because the API checks MX records.
test.describe("real backend", () => {
  test.skip(process.env.E2E_REAL_BACKEND !== "1", "Needs the API running on port 8000.");

  test("registers once, then refuses the same email with a 409 under the field", async ({
    page,
    registration,
  }) => {
    const email = `e2e-${Date.now()}@gmail.com`;
    await registration.goto();
    await registration.fillRequired("Casey", email);

    await registration.submit();
    await expect(registration.successHeading()).toBeVisible();

    await page.getByRole("button", { name: "Register another customer" }).click();
    await registration.fillRequired("Casey", email);
    await registration.submit();

    await expect(registration.email).toHaveAccessibleDescription(/Already registered to another customer/);
  });
});
