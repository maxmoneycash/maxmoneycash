import React from "react";
import { describe, expect, it, vi, beforeEach } from "vitest";
import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { ResetPasswordPage } from "./ResetPasswordPage.jsx";
import { LocaleProvider } from "../ui/foundation/LocaleProvider.jsx";

let authState;

vi.mock("../contexts/InsforgeAuthContext.jsx", () => ({
  useInsforgeAuth: () => authState,
}));

function renderPage(path = "/reset-password") {
  return render(
    <LocaleProvider>
      <MemoryRouter initialEntries={[path]}>
        <ResetPasswordPage />
      </MemoryRouter>
    </LocaleProvider>,
  );
}

describe("ResetPasswordPage", () => {
  beforeEach(() => {
    authState = {
      enabled: true,
      sendResetPasswordEmail: vi.fn(async () => ({ data: { success: true }, error: null })),
      exchangeResetPasswordToken: vi.fn(async () => ({ data: { token: "otp-from-code" }, error: null })),
      resetPassword: vi.fn(async () => ({ data: { message: "ok" }, error: null })),
      getPublicAuthConfig: vi.fn(async () => ({
        data: { oAuthProviders: ["google", "github"], passwordMinLength: 8 },
        error: null,
      })),
    };
  });

  it("requests a reset email with a reset-password redirect", async () => {
    const user = userEvent.setup();
    renderPage();

    await act(async () => {
      await user.type(screen.getByLabelText("Email"), "user@example.com");
      await user.click(screen.getByRole("button", { name: "Send reset link" }));
    });

    expect(authState.sendResetPasswordEmail).toHaveBeenCalledWith({
      email: "user@example.com",
      redirectTo: expect.stringMatching(/\/reset-password$/),
    });
    expect(await screen.findByText(/Check email for reset link/)).toBeInTheDocument();
  });

  it("resets the password with a token from the reset link", async () => {
    const user = userEvent.setup();
    renderPage("/reset-password?otp=link-token");

    await act(async () => {
      await user.type(screen.getByLabelText("New password"), "new-password-123");
      await user.type(screen.getByLabelText("Confirm password"), "new-password-123");
      await user.click(screen.getByRole("button", { name: "Reset password" }));
    });

    expect(authState.exchangeResetPasswordToken).not.toHaveBeenCalled();
    expect(authState.resetPassword).toHaveBeenCalledWith({
      newPassword: "new-password-123",
      otp: "link-token",
    });
    expect(await screen.findByText(/Password updated/)).toBeInTheDocument();
  });

  it("supports code-based password reset after the request email", async () => {
    const user = userEvent.setup();
    renderPage();

    await act(async () => {
      await user.type(screen.getByLabelText("Email"), "user@example.com");
      await user.click(screen.getByRole("button", { name: "Send reset link" }));
    });
    await act(async () => {
      await user.type(await screen.findByLabelText("Reset code"), "123456");
      await user.type(screen.getByLabelText("New password"), "new-password-123");
      await user.type(screen.getByLabelText("Confirm password"), "new-password-123");
      await user.click(screen.getByRole("button", { name: "Reset password" }));
    });

    expect(authState.exchangeResetPasswordToken).toHaveBeenCalledWith({
      email: "user@example.com",
      code: "123456",
    });
    expect(authState.resetPassword).toHaveBeenCalledWith({
      newPassword: "new-password-123",
      otp: "otp-from-code",
    });
  });
});
