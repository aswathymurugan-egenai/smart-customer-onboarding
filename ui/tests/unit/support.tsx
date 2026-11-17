import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import type { ReactElement } from "react";
import { vi } from "vitest";

import { RuntimeConfigProvider, type RuntimeConfig } from "@/lib/runtime-config";

export const TEST_CONFIG: RuntimeConfig = {
  apiBaseUrl: "http://api.test",
  assistantEnabled: true,
  botCheckToken: "local",
};

export type RecordedRequest = {
  method: string;
  path: string;
  headers: Headers;
  body: unknown;
};

type Handler = (request: RecordedRequest) => Response | Promise<Response>;

/** Replace `fetch` with routes keyed by "METHOD /path". Returns every request seen, in order. */
export function mockApi(routes: Record<string, Handler>): RecordedRequest[] {
  const seen: RecordedRequest[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: Request) => {
      const url = new URL(input.url);
      const text = await input.clone().text();
      const recorded: RecordedRequest = {
        method: input.method,
        path: url.pathname,
        headers: input.headers,
        body: text ? JSON.parse(text) : undefined,
      };
      seen.push(recorded);
      const handler = routes[`${input.method} ${url.pathname}`];
      if (!handler) throw new Error(`Unexpected request: ${input.method} ${url.pathname}`);
      return handler(recorded);
    }),
  );
  return seen;
}

export function problem(status: number, body: Record<string, unknown>, headers: Record<string, string> = {}) {
  return new Response(
    JSON.stringify({
      title: "Problem",
      detail: "Something is wrong.",
      instance: "/x",
      request_id: "r1",
      status,
      errors: [],
      ...body,
    }),
    { status, headers: { "content-type": "application/problem+json", ...headers } },
  );
}

export function json(status: number, body: unknown, headers: Record<string, string> = {}) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json", ...headers },
  });
}

export function renderWithProviders(ui: ReactElement, config: RuntimeConfig = TEST_CONFIG) {
  const client = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
  return render(
    <RuntimeConfigProvider value={config}>
      <QueryClientProvider client={client}>{ui}</QueryClientProvider>
    </RuntimeConfigProvider>,
  );
}
