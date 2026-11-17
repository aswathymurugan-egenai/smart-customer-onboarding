import type { Locator, Page } from "@playwright/test";

/** The assistant, whether it sits beside the form or inside the bottom drawer. */
export class AssistantPanelPage {
  readonly openDrawerButton: Locator;

  constructor(readonly page: Page) {
    this.openDrawerButton = page.getByRole("button", { name: "Ask the assistant" });
  }

  /** The panel's region: the side column on wide screens, the dialog on narrow ones. */
  region(): Locator {
    return this.page
      .getByRole("complementary", { name: "Signup assistant" })
      .or(this.page.getByRole("dialog", { name: "Assistant" }));
  }

  conversation(): Locator {
    return this.page.getByRole("log", { name: /conversation/i });
  }

  async say(text: string) {
    const region = this.region();
    await region.getByLabel("Message the assistant").fill(text);
    await region.getByRole("button", { name: "Send" }).click();
  }

  async confirmRegistration() {
    await this.region().getByRole("button", { name: "Confirm registration" }).click();
    await this.page
      .getByRole("dialog", { name: "Register this customer?" })
      .getByRole("button", { name: "Confirm registration" })
      .click();
  }
}
