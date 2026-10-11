import { afterEach, describe, expect, it, vi } from "vitest";
import { auth, logoutUrl, messageFor } from "./auth";

const CONFIG = { region: "ap-southeast-2", user_pool_id: "p", client_id: "client-1", domain: "auth.example.com", google: true };
const json = (status: number, body: unknown) => new Response(JSON.stringify(body), { status });

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("sign-in messages say what to do next", () => {
  it("explains an unconfirmed email on password reset instead of 'check the address'", () => {
    expect(messageFor("InvalidParameterException", "Cannot reset password for the user as there is no registered/verified email", "ForgotPassword")).toMatch(/never confirmed/);
    expect(messageFor("InvalidParameterException", "x", "SignUp")).toBe("Check the email address and try again.");
  });

  it("names the daily email quota when Cognito hits it", () => {
    expect(messageFor("LimitExceededException", "Exceeded daily email limit for the operation or the account.", "ForgotPassword")).toMatch(/email limit/);
    expect(messageFor("LimitExceededException", "Attempt limit exceeded, please try after some time.", "SignIn")).toMatch(/Too many attempts/);
  });
});

describe("Google sign-in and sign-out", () => {
  it("asks Google to show the account chooser every time", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(json(200, CONFIG)));
    const assign = vi.fn();
    // Node test runner: only the browser APIs this flow touches.
    vi.stubGlobal("window", { location: { assign, origin: "https://app.example.com", pathname: "/app/merchant" } });
    vi.stubGlobal("sessionStorage", { setItem: vi.fn() });
    await auth.signInWithGoogle("/app/merchant");
    const url = new URL(assign.mock.calls[0][0] as string);
    expect(url.pathname).toBe("/oauth2/authorize");
    expect(url.searchParams.get("prompt")).toBe("select_account");
    expect(url.searchParams.get("identity_provider")).toBe("Google");
    expect(url.searchParams.get("code_challenge_method")).toBe("S256");
  });

  it("builds Cognito's logout URL back to the console", () => {
    const url = new URL(logoutUrl("auth.example.com", "client-1", "https://app.example.com"));
    expect(url.origin + url.pathname).toBe("https://auth.example.com/logout");
    expect(url.searchParams.get("client_id")).toBe("client-1");
    expect(url.searchParams.get("logout_uri")).toBe("https://app.example.com/app/merchant");
  });
});
