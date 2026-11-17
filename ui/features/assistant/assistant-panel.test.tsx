import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { CustomerDraft, LastResult } from "@/lib/api";
import { json, mockApi, problem, renderWithProviders } from "@/tests/unit/support";

import { AssistantPanel } from "./assistant-panel";
import { useChat } from "./use-chat";

const CHAT = "POST /api/v1/agent/chat";
const SNAPSHOT: CustomerDraft = { given_name: "Jane", email: "jane@example.test" };
const LAST_RESULT: LastResult = {
  status: 409,
  problem_type: "urn:smart-customer-onboarding:problem:customer-duplicate",
  matched_on: ["email"],
  warnings: [],
};
const SESSION = "6f1c1bde-3a64-4f2c-9a54-52f7a2d0a111";

function reply(overrides: Record<string, unknown> = {}) {
  return json(200, {
    session_id: SESSION,
    message: "Here is what happened.",
    suggested_actions: [],
    registration: null,
    model: "gemini-2.5-flash",
    used_fallback: false,
    ...overrides,
  });
}

function Harness() {
  const chat = useChat({ getSnapshot: () => SNAPSHOT, getLastResult: () => LAST_RESULT });
  return <AssistantPanel chat={chat} onApplyEmailSuggestion={vi.fn()} onReviewField={vi.fn()} />;
}

function renderPanel() {
  renderWithProviders(<Harness />);
  return userEvent.setup();
}

async function say(user: ReturnType<typeof userEvent.setup>, text: string) {
  await user.type(screen.getByLabelText("Message the assistant"), text);
  await user.click(screen.getByRole("button", { name: "Send" }));
}

describe("assistant panel", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("mounts the polite live region empty", () => {
    mockApi({});
    renderPanel();

    const log = screen.getByRole("log", { name: /conversation/i });

    expect(log).toHaveAttribute("aria-live", "polite");
    expect(log).toBeEmptyDOMElement();
  });

  it("sends the form snapshot, the last result, and one conversation id on every turn", async () => {
    const seen = mockApi({ [CHAT]: () => reply() });
    const user = renderPanel();

    await say(user, "Why was I refused?");
    await screen.findByText("Here is what happened.");
    await say(user, "And now?");
    await screen.findAllByText("Here is what happened.");

    const bodies = seen.map((request) => request.body as Record<string, unknown>);
    expect(bodies).toHaveLength(2);
    for (const body of bodies) {
      expect(body.form_snapshot).toEqual(SNAPSHOT);
      expect(body.last_result).toEqual(LAST_RESULT);
      expect(body).not.toHaveProperty("action");
    }
    expect(bodies[0].session_id).toBe(bodies[1].session_id);
    expect(bodies[0].message).toBe("Why was I refused?");
  });

  it("sends the confirm action only after the dialog's confirm button", async () => {
    const seen = mockApi({
      [CHAT]: () => reply({ suggested_actions: ["confirm_registration"] }),
    });
    const user = renderPanel();
    await say(user, "Register me");
    await user.click(await screen.findByRole("button", { name: "Confirm registration" }));

    expect(seen).toHaveLength(1);
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText("Register this customer?")).toBeInTheDocument();
    expect(seen).toHaveLength(1);

    await user.click(within(dialog).getByRole("button", { name: "Confirm registration" }));

    await screen.findAllByText("Here is what happened.");
    expect(seen).toHaveLength(2);
    expect(seen[1].body).toMatchObject({ action: "confirm_registration" });
  });

  it("sends nothing when the confirmation dialog is cancelled", async () => {
    const seen = mockApi({
      [CHAT]: () => reply({ suggested_actions: ["confirm_registration"] }),
    });
    const user = renderPanel();
    await say(user, "Register me");
    await user.click(await screen.findByRole("button", { name: "Confirm registration" }));

    await user.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "Cancel" }));

    expect(seen).toHaveLength(1);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("shows the registration status from the registration field, not from the message text", async () => {
    mockApi({
      [CHAT]: () =>
        reply({
          message: "Great news, you are registered!",
          registration: { status: "needs_confirmation", customer_id: null, matched_on: [] },
        }),
    });
    const user = renderPanel();

    await say(user, "Did it work?");

    expect(await screen.findByText("Great news, you are registered!")).toBeInTheDocument();
    expect(screen.getByText(/Not registered yet/)).toBeInTheDocument();
    expect(screen.queryByText(/^Registered\./)).not.toBeInTheDocument();
  });

  it("shows a created registration with its customer id from the registration field", async () => {
    mockApi({
      [CHAT]: () =>
        reply({
          message: "Done.",
          registration: { status: "created", customer_id: "cust-123", matched_on: [] },
        }),
    });
    const user = renderPanel();

    await say(user, "Confirmed");

    expect(await screen.findByText("Registered. Customer id cust-123.")).toBeInTheDocument();
  });

  it("names the matched fields when the register tool reports a duplicate", async () => {
    mockApi({
      [CHAT]: () =>
        reply({ registration: { status: "duplicate", customer_id: null, matched_on: ["email", "phone"] } }),
    });
    const user = renderPanel();

    await say(user, "Try again");

    expect(await screen.findByText(/the email, phone already belong to another customer/)).toBeInTheDocument();
  });

  it("tells the person the assistant is unavailable on a 503 and keeps the form usable", async () => {
    mockApi({ [CHAT]: () => problem(503, { type: "urn:p:assistant-unavailable" }) });
    const user = renderPanel();

    await say(user, "Hello");

    expect(await screen.findByText(/assistant is unavailable right now/i)).toBeInTheDocument();
  });

  it("offers only the actions the latest answer suggests", async () => {
    mockApi({ [CHAT]: () => reply({ suggested_actions: ["apply_email_suggestion", "review_field"] }) });
    const user = renderPanel();

    await say(user, "Help");

    expect(await screen.findByRole("button", { name: "Use the suggested email" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Review the fields" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Confirm registration" })).not.toBeInTheDocument();
  });
});
