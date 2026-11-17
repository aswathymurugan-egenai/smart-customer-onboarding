import type { Locator, Page } from "@playwright/test";

/** The signup form. Locators use roles and labels only. */
export class RegistrationPage {
  readonly givenName: Locator;
  readonly familyName: Locator;
  readonly email: Locator;
  readonly phone: Locator;
  readonly taxId: Locator;
  readonly addressLine1: Locator;
  readonly city: Locator;
  readonly region: Locator;
  readonly postalCode: Locator;
  readonly countryCode: Locator;
  readonly registerButton: Locator;
  readonly business: Locator;

  constructor(readonly page: Page) {
    this.givenName = page.getByLabel(/^given name/i);
    this.familyName = page.getByLabel(/^family name/i);
    this.email = page.getByLabel(/^email/i);
    this.phone = page.getByLabel(/^phone/i);
    this.taxId = page.getByLabel(/^tax id \(optional\)/i);
    this.addressLine1 = page.getByLabel(/^address line 1/i);
    this.city = page.getByLabel(/^city/i);
    this.region = page.getByLabel(/^state or region/i);
    this.postalCode = page.getByLabel(/^postal code/i);
    this.countryCode = page.getByLabel(/^country code/i);
    this.registerButton = page.getByRole("button", { name: "Register" });
    this.business = page.getByRole("radio", { name: "Business" });
  }

  async goto() {
    await this.page.goto("/");
  }

  async fillRequired(given = "Jane", email = "jane@example.test") {
    await this.givenName.fill(given);
    await this.email.fill(email);
  }

  async submit() {
    await this.registerButton.click();
  }

  successHeading(): Locator {
    return this.page.getByRole("heading", { name: "You are registered" });
  }
}
