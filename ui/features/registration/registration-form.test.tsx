import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { json, mockApi, problem, renderWithProviders } from "@/tests/unit/support";

import { RegistrationForm } from "./registration-form";
import { DUPLICATE_MESSAGE } from "./map-problem";

const REGISTER = "POST /api/v1/customers/register";
const VALIDATE = "POST /api/v1/customers/validate";
const CREATED = {
  customer_id: "0192f6a0-7c1e-7d3b-9a52-5a7d3f6c9e10",
  status: "created",
  email: "jane@example.test",
  warnings: [],
  advisory_status: "ok",
};

function renderForm() {
  const onResult = vi.fn();
  renderWithProviders(<RegistrationForm apiRef={{ current: null }} onResult={onResult} />);
  return { user: userEvent.setup(), onResult };
}

async function fillRequired(user: ReturnType<typeof userEvent.setup>) {
  await user.type(screen.getByLabelText(/^given name/i), "Jane");
  await user.type(screen.getByLabelText(/^email/i), "jane@example.test");
}

function submit(user: ReturnType<typeof userEvent.setup>) {
  return user.click(screen.getByRole("button", { name: "Register" }));
}

function errorFor(input: HTMLElement): HTMLElement {
  const ids = (input.getAttribute("aria-describedby") ?? "").split(" ");
  const alert = ids
    .map((id) => document.getElementById(id))
    .find((element) => element?.getAttribute("role") === "alert");
  if (!alert) throw new Error("No error is linked to the control through aria-describedby.");
  return alert;
}

describe("registration form", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("shows a missing required field's error under that field, linked by aria-describedby", async () => {
    mockApi({});
    const { user } = renderForm();

    await submit(user);

    const given = screen.getByLabelText(/^given name/i);
    expect(await screen.findByText("Enter a given name.")).toBeInTheDocument();
    expect(given).toHaveAttribute("aria-invalid", "true");
    expect(errorFor(given)).toHaveTextContent("Enter a given name.");
    expect(errorFor(screen.getByLabelText(/^email/i))).toHaveTextContent("Enter an email address.");
  });

  it("puts a duplicate error under every matched field on a 409", async () => {
    mockApi({
      [REGISTER]: () =>
        problem(409, { type: "urn:p:customer-duplicate", matched_on: ["email", "phone"] }),
    });
    const { user, onResult } = renderForm();
    await fillRequired(user);
    await user.type(screen.getByLabelText(/^phone/i), "+1 415 555 0100");

    await submit(user);

    const messages = await screen.findAllByText(DUPLICATE_MESSAGE);
    expect(messages).toHaveLength(2);
    expect(errorFor(screen.getByLabelText(/^email/i))).toHaveTextContent(DUPLICATE_MESSAGE);
    expect(errorFor(screen.getByLabelText(/^phone/i))).toHaveTextContent(DUPLICATE_MESSAGE);
    expect(onResult).toHaveBeenCalledWith(
      expect.objectContaining({ status: 409, matched_on: ["email", "phone"] }),
    );
  });

  it("lands a 422 pointer on its field", async () => {
    mockApi({
      [REGISTER]: () =>
        problem(422, {
          type: "urn:p:tax-id-invalid",
          errors: [
            { pointer: "/address/postal_code", code: "x", message: "That postal code is not valid." },
          ],
        }),
    });
    const { user } = renderForm();
    await fillRequired(user);

    await submit(user);

    const postal = screen.getByLabelText(/^postal code/i);
    await waitFor(() => expect(errorFor(postal)).toHaveTextContent("That postal code is not valid."));
  });

  it("applies the suggested domain when Use is pressed", async () => {
    mockApi({
      [VALIDATE]: () =>
        json(200, {
          email_as_entered: "jane@gmial.com",
          normalized_email: "jane@gmial.com",
          is_valid: true,
          checks: { syntax: "pass", disposable: "pass", mx: "pass" },
          problems: [],
          suggestion: {
            code: "possible_typo",
            message: "Did you mean jane@gmail.com?",
            suggested_email: "jane@gmail.com",
            source: "rules",
          },
        }),
    });
    const { user } = renderForm();
    const email = screen.getByLabelText(/^email/i);
    await user.type(email, "jane@gmial.com");
    await user.tab();

    await user.click(await screen.findByRole("button", { name: "Use jane@gmail.com" }));

    expect(email).toHaveValue("jane@gmail.com");
    expect(screen.queryByText(/did you mean/i)).not.toBeInTheDocument();
  });

  it("shows problems from the email check under the email field", async () => {
    mockApi({
      [VALIDATE]: () =>
        json(200, {
          email_as_entered: "x@mailinator.test",
          normalized_email: "x@mailinator.test",
          is_valid: false,
          checks: { syntax: "pass", disposable: "fail", mx: "skipped" },
          problems: [{ code: "email-disposable", message: "The email domain accepts disposable addresses." }],
          suggestion: null,
        }),
    });
    const { user } = renderForm();
    await user.type(screen.getByLabelText(/^email/i), "x@mailinator.test");
    await user.tab();

    const message = await screen.findByText("The email domain accepts disposable addresses.");

    expect(message).toHaveAttribute("role", "alert");
    expect(screen.getByLabelText(/^email/i).getAttribute("aria-describedby")).toContain(
      message.closest("[id]")!.id,
    );
  });

  it("reveals the company name field when business is chosen", async () => {
    mockApi({});
    const { user } = renderForm();
    expect(screen.queryByLabelText(/company name/i)).not.toBeInTheDocument();

    await user.click(screen.getByRole("radio", { name: "Business" }));

    expect(screen.getByLabelText(/company name/i)).toBeInTheDocument();
  });

  it("sends one idempotency key and a body without blank optional fields, then shows the result", async () => {
    const seen = mockApi({ [REGISTER]: () => json(201, CREATED, { "Idempotent-Replayed": "false" }) });
    const { user, onResult } = renderForm();
    await fillRequired(user);

    await submit(user);

    expect(await screen.findByText("You are registered")).toBeInTheDocument();
    expect(screen.getByText(CREATED.customer_id)).toBeInTheDocument();
    const request = seen.find((item) => item.path.endsWith("/register"))!;
    expect(request.headers.get("Idempotency-Key")).toMatch(/^[0-9a-f-]{36}$/);
    expect(request.body).toEqual({
      customer_type: "individual",
      given_name: "Jane",
      email: "jane@example.test",
      bot_token: "local",
    });
    expect(onResult).toHaveBeenCalledWith({ status: 201, matched_on: [], warnings: [] });
  });

  it("reuses the idempotency key when the same registration is retried", async () => {
    let calls = 0;
    const seen = mockApi({
      [REGISTER]: () => (++calls === 1 ? problem(503, { type: "urn:p:registration-busy" }, { "Retry-After": "60" }) : json(201, CREATED)),
    });
    const { user } = renderForm();
    await fillRequired(user);

    await submit(user);
    await user.click(await screen.findByRole("button", { name: "Try again" }));

    await screen.findByText("You are registered");
    const keys = seen.filter((item) => item.path.endsWith("/register")).map((item) => item.headers.get("Idempotency-Key"));
    expect(keys).toHaveLength(2);
    expect(keys[0]).toBe(keys[1]);
  });

  it("shows the wait time on a 429 and offers no retry", async () => {
    mockApi({ [REGISTER]: () => problem(429, { type: "urn:p:rate-limited" }, { "Retry-After": "42" }) });
    const { user } = renderForm();
    await fillRequired(user);

    await submit(user);

    expect(await screen.findByText(/Try again in 42 seconds/)).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("Too many attempts");
    expect(screen.queryByRole("button", { name: "Try again" })).not.toBeInTheDocument();
  });

  it("offers a retry on a 503", async () => {
    mockApi({ [REGISTER]: () => problem(503, { type: "urn:p:registration-busy" }, { "Retry-After": "60" }) });
    const { user } = renderForm();
    await fillRequired(user);

    await submit(user);

    expect(await screen.findByText("Registration is busy")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument();
  });
});
