import AxeBuilder from "@axe-core/playwright";

import { CREATED, chatReply, expect, problem, test } from "./fixtures";

const REGISTER = "/api/v1/customers/register";
const CHAT = "/api/v1/agent/chat";
const WIDE = { width: 1280, height: 900 };
const NARROW = { width: 390, height: 844 };

test.describe("registration journeys", () => {
  test.use({ viewport: WIDE });

  test("a 201 with a warning shows the customer id and offers the assistant", async ({
    page,
    api,
    registration,
    assistant,
  }) => {
    api.on("POST", REGISTER, {
      status: 201,
      body: {
        ...CREATED,
        warnings: [
          {
            code: "possible_duplicate",
            message: "A customer with similar details may already exist.",
            confidence: 0.8,
            reasons: ["name_variant"],
          },
        ],
      },
    });
    api.on("POST", CHAT, chatReply({ message: "That warning means a similar customer exists." }));
    await registration.goto();
    await registration.fillRequired();

    await registration.submit();

    await expect(registration.successHeading()).toBeVisible();
    await expect(page.getByText(CREATED.customer_id)).toBeVisible();
    await expect(page.getByText("A customer with similar details may already exist.")).toBeVisible();

    await page.getByRole("button", { name: "Ask the assistant" }).first().click();

    await expect(assistant.conversation()).toContainText("That warning means a similar customer exists.");
    expect(api.callsTo(CHAT)[0].body).toMatchObject({
      message: expect.stringContaining("similar details"),
    });
  });

  test("a 409 puts an error under each matched field", async ({ api, registration }) => {
    api.on("POST", REGISTER, problem(409, "customer-duplicate", { matched_on: ["email", "phone"] }));
    await registration.goto();
    await registration.fillRequired();
    await registration.phone.fill("+1 415 555 0100");

    await registration.submit();

    await expect(registration.email).toHaveAccessibleDescription(/Already registered to another customer/);
    await expect(registration.phone).toHaveAccessibleDescription(/Already registered to another customer/);
    await expect(registration.email).toBeFocused();
  });

  test("a 422 lands under the field it concerns", async ({ api, registration }) => {
    api.on(
      "POST",
      REGISTER,
      problem(422, "email-disposable", {
        errors: [
          {
            pointer: "/email",
            code: "email-disposable",
            message: "The email domain accepts disposable addresses.",
          },
        ],
      }),
    );
    await registration.goto();
    await registration.fillRequired("Jane", "jane@mailinator.test");

    await registration.submit();

    await expect(registration.email).toHaveAccessibleDescription(/disposable addresses/);
    await expect(registration.email).toHaveAttribute("aria-invalid", "true");
  });

  test("a 503 offers a retry that reuses the idempotency key and then succeeds", async ({
    page,
    api,
    registration,
  }) => {
    let attempts = 0;
    api.on("POST", REGISTER, () =>
      ++attempts === 1
        ? { ...problem(503, "registration-busy"), headers: { "retry-after": "60" } }
        : { status: 201, body: CREATED },
    );
    await registration.goto();
    await registration.fillRequired();
    await registration.submit();

    await expect(page.getByText("Registration is busy")).toBeVisible();
    await page.getByRole("button", { name: "Try again" }).click();

    await expect(registration.successHeading()).toBeVisible();
    expect(api.callsTo(REGISTER)).toHaveLength(2);
  });

  test("the assistant registers the person only after the explicit confirmation", async ({
    api,
    registration,
    assistant,
  }) => {
    api.on("POST", CHAT, (call) =>
      (call.body as { action?: string }).action === "confirm_registration"
        ? chatReply({
            message: "Done.",
            registration: { status: "created", customer_id: CREATED.customer_id, matched_on: [] },
          })
        : chatReply({ message: "Ready when you are.", suggested_actions: ["confirm_registration"] }),
    );
    await registration.goto();
    await registration.fillRequired();

    await assistant.say("Please register me");
    await expect(assistant.conversation()).toContainText("Ready when you are.");
    expect(api.callsTo(CHAT)).toHaveLength(1);
    expect(api.callsTo(CHAT)[0].body).not.toHaveProperty("action");

    await assistant.confirmRegistration();

    await expect(assistant.conversation()).toContainText(`Registered. Customer id ${CREATED.customer_id}.`);
    await expect(registration.successHeading()).toBeVisible();
    expect(api.callsTo(CHAT)[1].body).toMatchObject({ action: "confirm_registration" });
    expect(api.callsTo(REGISTER)).toHaveLength(0);
  });

  test("the form completes by keyboard alone", async ({ page, api, registration }) => {
    api.on("POST", REGISTER, { status: 201, body: CREATED });
    await registration.goto();
    await page.keyboard.press("Tab");
    await expect(page.getByRole("link", { name: "Skip to the signup form" })).toBeFocused();

    await registration.givenName.focus();
    await page.keyboard.type("Jane");
    await registration.email.focus();
    await page.keyboard.type("jane@example.test");
    await registration.registerButton.focus();
    await page.keyboard.press("Enter");

    await expect(registration.successHeading()).toBeVisible();
  });
});

test.describe("layout", () => {
  test("at 1280px pairs sit in two columns and the assistant sits beside the form", async ({
    page,
    registration,
  }) => {
    await page.setViewportSize(WIDE);
    await registration.goto();

    const [given, family] = await Promise.all([
      registration.givenName.boundingBox(),
      registration.familyName.boundingBox(),
    ]);
    const form = await page.getByRole("button", { name: "Register" }).boundingBox();
    const panel = await page.getByRole("complementary", { name: "Signup assistant" }).boundingBox();

    expect(Math.abs(given!.y - family!.y)).toBeLessThan(2);
    expect(family!.x).toBeGreaterThan(given!.x + given!.width);
    expect(panel).not.toBeNull();
    expect(panel!.x).toBeGreaterThan(form!.x + form!.width - 1);
    await expect(page.getByRole("button", { name: "Ask the assistant" })).toBeHidden();
  });

  test("at 390px fields stack in one column and the assistant opens in a drawer", async ({
    page,
    registration,
    assistant,
  }) => {
    await page.setViewportSize(NARROW);
    await registration.goto();

    const [given, family] = await Promise.all([
      registration.givenName.boundingBox(),
      registration.familyName.boundingBox(),
    ]);
    const submit = await registration.registerButton.boundingBox();

    expect(family!.y).toBeGreaterThan(given!.y + given!.height);
    expect(Math.abs(family!.x - given!.x)).toBeLessThan(2);
    expect(submit!.width).toBeGreaterThan(NARROW.width * 0.7);
    await expect(page.getByRole("complementary", { name: "Signup assistant" })).toBeHidden();

    const opener = assistant.openDrawerButton;
    const target = await opener.boundingBox();
    expect(target!.height).toBeGreaterThanOrEqual(44);
    await opener.click();
    await expect(page.getByRole("dialog", { name: "Assistant" })).toBeVisible();
  });
});

test.describe("accessibility", () => {
  for (const scheme of ["light", "dark"] as const) {
    test(`axe reports no violations in the ${scheme} theme`, async ({ page, registration }) => {
      await page.emulateMedia({ colorScheme: scheme });
      await registration.goto();
      await expect(page.locator("html")).toHaveClass(scheme === "dark" ? /dark/ : /^((?!dark).)*$/);

      const results = await new AxeBuilder({ page }).analyze();

      expect(results.violations).toEqual([]);
    });
  }
});
