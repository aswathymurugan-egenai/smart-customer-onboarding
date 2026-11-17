import { test as base, type Page, type Route } from "@playwright/test";

import { AssistantPanelPage } from "./pages/assistant-panel";
import { RegistrationPage } from "./pages/registration-page";

const API = "http://localhost:8000";

export type ApiCall = { method: string; path: string; body: unknown };

type Reply = { status: number; body: unknown; headers?: Record<string, string> };
type Handler = (call: ApiCall) => Reply | Promise<Reply>;

/** Intercept calls to the API at the route layer and record each one. */
export class ApiMock {
  readonly calls: ApiCall[] = [];
  private readonly handlers = new Map<string, Handler>();

  constructor(page: Page) {
    void page.route(`${API}/**`, (route) => this.handle(route));
  }

  on(method: string, path: string, handler: Handler | Reply) {
    this.handlers.set(`${method} ${path}`, typeof handler === "function" ? handler : () => handler);
  }

  private async handle(route: Route) {
    const request = route.request();
    const url = new URL(request.url());
    const cors = {
      "access-control-allow-origin": "*",
      "access-control-allow-headers": "*",
      "access-control-expose-headers": "*",
    };
    if (request.method() === "OPTIONS") {
      await route.fulfill({ status: 204, headers: cors });
      return;
    }
    const call: ApiCall = {
      method: request.method(),
      path: url.pathname,
      body: request.postDataJSON() ?? undefined,
    };
    this.calls.push(call);
    const handler = this.handlers.get(`${call.method} ${call.path}`);
    if (!handler) {
      await route.fulfill({ status: 500, headers: cors, body: "unmocked" });
      return;
    }
    const reply = await handler(call);
    await route.fulfill({
      status: reply.status,
      headers: {
        ...cors,
        "content-type": reply.status >= 400 ? "application/problem+json" : "application/json",
        ...reply.headers,
      },
      body: JSON.stringify(reply.body),
    });
  }

  callsTo(path: string): ApiCall[] {
    return this.calls.filter((call) => call.path === path);
  }
}

type Fixtures = {
  api: ApiMock;
  registration: RegistrationPage;
  assistant: AssistantPanelPage;
};

export const test = base.extend<Fixtures>({
  api: async ({ page }, provide) => {
    const mock = new ApiMock(page);
    mock.on("POST", "/api/v1/customers/validate", ({ body }) => ({
      status: 200,
      body: {
        email_as_entered: (body as { email: string }).email,
        normalized_email: (body as { email: string }).email,
        is_valid: true,
        checks: { syntax: "pass", disposable: "pass", mx: "pass" },
        problems: [],
        suggestion: null,
      },
    }));
    await provide(mock);
  },
  registration: async ({ page }, provide) => {
    await provide(new RegistrationPage(page));
  },
  assistant: async ({ page }, provide) => {
    await provide(new AssistantPanelPage(page));
  },
});

export { expect } from "@playwright/test";

export const CREATED = {
  customer_id: "0192f6a0-7c1e-7d3b-9a52-5a7d3f6c9e10",
  status: "created",
  email: "jane@example.test",
  warnings: [] as unknown[],
  advisory_status: "ok",
};

export function problem(status: number, type: string, extra: Record<string, unknown> = {}) {
  return {
    status,
    body: {
      type: `urn:smart-customer-onboarding:problem:${type}`,
      title: "Problem",
      status,
      detail: "Detail",
      instance: "/api/v1/customers/register",
      request_id: "r1",
      errors: [],
      ...extra,
    },
  };
}

export function chatReply(overrides: Record<string, unknown> = {}) {
  return {
    status: 200,
    body: {
      session_id: "6f1c1bde-3a64-4f2c-9a54-52f7a2d0a111",
      message: "Here is what happened.",
      suggested_actions: [],
      registration: null,
      model: "gemini-2.5-flash",
      used_fallback: false,
      ...overrides,
    },
  };
}
