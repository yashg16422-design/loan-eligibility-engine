// Accounts via Amazon Cognito, called directly from the browser (no SDK): email + password
// (sign up, confirm, sign in, forgot / reset password) and "Continue with Google" through
// Cognito's OAuth 2.0 code flow with PKCE. Passwords go only to Cognito over HTTPS; our API and
// database never see them. API calls carry the Cognito ID token, which API Gateway's JWT
// authorizer verifies before our code runs.

interface AuthConfig {
  region: string;
  user_pool_id: string;
  client_id: string;
  domain: string; // managed-login domain for OAuth; "" when Google is off
  google: boolean;
}

interface Session {
  idToken: string;
  refreshToken: string;
  email: string;
  expiresAt: number; // epoch seconds of the ID token
  method?: "password" | "google"; // how this session signed in (sign-out differs)
}

const KEY = "clickpar-account";
let config: Promise<AuthConfig> | null = null;

export class AuthError extends Error {
  constructor(
    readonly code: string,
    message: string,
  ) {
    super(message);
  }
}

// Cognito error names -> sentences a person can act on.
const MESSAGES: Record<string, string> = {
  UsernameExistsException: "An account with this email already exists. Sign in instead.",
  InvalidPasswordException: "Use at least 10 characters, with a lowercase letter and a number.",
  CodeMismatchException: "That code doesn't match. Check the latest email from Cognito.",
  ExpiredCodeException: "That code has expired. Send a new one.",
  NotAuthorizedException: "Email or password is incorrect.",
  UserNotConfirmedException: "Confirm your email first: enter the code we sent.",
  LimitExceededException: "Too many attempts. Wait a few minutes and try again.",
  UserNotFoundException: "Email or password is incorrect.",
  PasswordResetRequiredException: "Reset your password first: choose \"Forgot password\".",
  TooManyRequestsException: "Too many attempts. Wait a few minutes and try again.",
  InvalidParameterException: "Check the email address and try again.",
};

/** The sentence to show for a Cognito error, specific to what the person was doing. */
export function messageFor(code: string, raw: string, action: string): string {
  // Cognito's own sender has a daily quota; say so instead of a vague "too many attempts".
  if (code === "LimitExceededException" && /daily|email/i.test(raw)) {
    return "Today's email limit for sign-in codes is reached. Try again tomorrow, or sign in with Google.";
  }
  if (action === "ForgotPassword" && code === "InvalidParameterException") {
    return "This account's email was never confirmed, so a reset code can't be sent. Create the account again with this email, or sign in with Google.";
  }
  if (action === "ForgotPassword" && code === "UserNotConfirmedException") {
    return "This email is not confirmed yet. Choose Create account with it, then enter the code we email you.";
  }
  return MESSAGES[code] ?? raw ?? "Something went wrong. Try again.";
}

function getConfig(): Promise<AuthConfig> {
  config ??= fetch("/auth/config").then((r) => {
    if (!r.ok) throw new AuthError("Config", "Sign-in is unavailable right now.");
    return r.json() as Promise<AuthConfig>;
  });
  return config;
}

async function cognito<T>(action: string, body: Record<string, unknown>): Promise<T> {
  const { region } = await getConfig();
  const res = await fetch(`https://cognito-idp.${region}.amazonaws.com/`, {
    method: "POST",
    headers: {
      "Content-Type": "application/x-amz-json-1.1",
      "X-Amz-Target": `AWSCognitoIdentityProviderService.${action}`,
    },
    body: JSON.stringify(body),
  });
  const data = (await res.json().catch(() => ({}))) as T & { __type?: string; message?: string };
  if (!res.ok) {
    const code = String(data.__type ?? "Unknown").split("#").pop() ?? "Unknown";
    throw new AuthError(code, messageFor(code, data.message ?? "", action));
  }
  return data;
}

function claims(jwt: string): Record<string, unknown> {
  const part = jwt.split(".")[1] ?? "";
  const json = atob(part.replace(/-/g, "+").replace(/_/g, "/").padEnd(Math.ceil(part.length / 4) * 4, "="));
  return JSON.parse(decodeURIComponent(escape(json))) as Record<string, unknown>;
}

function store(s: Session | null) {
  try {
    if (s) localStorage.setItem(KEY, JSON.stringify(s));
    else localStorage.removeItem(KEY);
  } catch {
    /* private mode: the session lasts for this page only */
  }
  window.dispatchEvent(new Event("clickpar-account"));
}

function load(): Session | null {
  try {
    const raw = localStorage.getItem(KEY);
    return raw ? (JSON.parse(raw) as Session) : null;
  } catch {
    return null;
  }
}

/** Session from an OAuth token response (Google via Cognito). */
function fromTokens(t: { id_token: string; refresh_token?: string }): Session {
  const c = claims(t.id_token);
  return {
    idToken: t.id_token,
    refreshToken: t.refresh_token ?? "",
    email: String(c.email ?? ""),
    expiresAt: Number(c.exp ?? 0),
    method: "google",
  };
}

const OAUTH = "clickpar-oauth"; // PKCE verifier + state + where to return, for one round trip
const b64url = (bytes: Uint8Array) => btoa(String.fromCharCode(...bytes)).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
const callbackUrl = () => `${window.location.origin}/app/auth/callback`;

function fromResult(
  r: { AuthenticationResult: { IdToken: string; RefreshToken?: string } },
  refresh?: string,
  method: Session["method"] = "password",
): Session {
  const c = claims(r.AuthenticationResult.IdToken);
  return {
    idToken: r.AuthenticationResult.IdToken,
    refreshToken: r.AuthenticationResult.RefreshToken ?? refresh ?? "",
    email: String(c.email ?? ""),
    expiresAt: Number(c.exp ?? 0),
    method,
  };
}

/** Cognito's sign-out URL: ends its one-hour sign-in cookie, then comes back to the console. */
export function logoutUrl(domain: string, clientId: string, origin: string): string {
  const q = new URLSearchParams({ client_id: clientId, logout_uri: `${origin}/app/merchant` });
  return `https://${domain}/logout?${q}`;
}

export const auth = {
  /** The signed-in email, or null. */
  email(): string | null {
    return load()?.email ?? null;
  },

  async signUp(email: string, password: string): Promise<void> {
    const { client_id } = await getConfig();
    await cognito("SignUp", {
      ClientId: client_id,
      Username: email,
      Password: password,
      UserAttributes: [{ Name: "email", Value: email }],
    });
  },

  async confirm(email: string, code: string): Promise<void> {
    const { client_id } = await getConfig();
    await cognito("ConfirmSignUp", { ClientId: client_id, Username: email, ConfirmationCode: code.trim() });
  },

  async resend(email: string): Promise<void> {
    const { client_id } = await getConfig();
    await cognito("ResendConfirmationCode", { ClientId: client_id, Username: email });
  },

  async signIn(email: string, password: string): Promise<void> {
    const { client_id } = await getConfig();
    const r = await cognito<{ AuthenticationResult: { IdToken: string; RefreshToken: string } }>("InitiateAuth", {
      ClientId: client_id,
      AuthFlow: "USER_PASSWORD_AUTH",
      AuthParameters: { USERNAME: email, PASSWORD: password },
    });
    store(fromResult(r));
  },

  /**
   * Sign out everywhere this app can: revoke the refresh token (best effort) and forget the
   * session. After a Google sign-in, also end Cognito's one-hour sign-in cookie, so the next
   * "Continue with Google" asks which Google account to use instead of reusing the last one.
   */
  async signOut(): Promise<void> {
    const s = load();
    store(null);
    if (!s) return;
    try {
      const { client_id, domain } = await getConfig();
      if (s.refreshToken) await cognito("RevokeToken", { Token: s.refreshToken, ClientId: client_id }).catch(() => {});
      if (s.method === "google" && domain) window.location.assign(logoutUrl(domain, client_id, window.location.origin));
    } catch {
      /* already signed out locally */
    }
  },

  /** Is "Continue with Google" available on this deployment? */
  async googleEnabled(): Promise<boolean> {
    try {
      const c = await getConfig();
      return c.google && !!c.domain;
    } catch {
      return false;
    }
  },

  /** Leave for Google (via Cognito); `returnTo` is the app path to come back to. */
  async signInWithGoogle(returnTo: string): Promise<void> {
    const { domain, client_id } = await getConfig();
    const verifier = b64url(crypto.getRandomValues(new Uint8Array(32)));
    const state = b64url(crypto.getRandomValues(new Uint8Array(16)));
    const challenge = b64url(new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(verifier))));
    sessionStorage.setItem(OAUTH, JSON.stringify({ verifier, state, returnTo }));
    const q = new URLSearchParams({
      identity_provider: "Google",
      response_type: "code",
      client_id,
      redirect_uri: callbackUrl(),
      scope: "openid email profile",
      state,
      code_challenge: challenge,
      code_challenge_method: "S256",
      // Forwarded to Google by Cognito's managed login: always show the account chooser, so
      // someone with several Google accounts picks one instead of getting the last one used.
      prompt: "select_account",
    });
    window.location.assign(`https://${domain}/oauth2/authorize?${q}`);
  },

  /** On /app/auth/callback: swap the code for tokens. Returns the path to go back to. */
  async finishGoogle(params: URLSearchParams): Promise<string> {
    const saved = JSON.parse(sessionStorage.getItem(OAUTH) ?? "null") as { verifier: string; state: string; returnTo: string } | null;
    sessionStorage.removeItem(OAUTH);
    const error = params.get("error_description") ?? params.get("error");
    if (error) throw new AuthError("OAuth", `Google sign-in was cancelled or refused (${error}).`);
    if (!saved || params.get("state") !== saved.state) throw new AuthError("OAuth", "That sign-in link is stale. Try again.");
    const { domain, client_id } = await getConfig();
    const res = await fetch(`https://${domain}/oauth2/token`, {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: new URLSearchParams({
        grant_type: "authorization_code",
        client_id,
        code: params.get("code") ?? "",
        redirect_uri: callbackUrl(),
        code_verifier: saved.verifier,
      }),
    });
    if (!res.ok) throw new AuthError("OAuth", "Google sign-in could not be completed. Try again.");
    store(fromTokens((await res.json()) as { id_token: string; refresh_token?: string }));
    return saved.returnTo || "/app/merchant";
  },

  /** Email a reset code (always "succeeds": Cognito never reveals whether an email exists). */
  async forgotPassword(email: string): Promise<void> {
    const { client_id } = await getConfig();
    await cognito("ForgotPassword", { ClientId: client_id, Username: email });
  },

  async resetPassword(email: string, code: string, password: string): Promise<void> {
    const { client_id } = await getConfig();
    await cognito("ConfirmForgotPassword", { ClientId: client_id, Username: email, ConfirmationCode: code.trim(), Password: password });
  },

  /** A valid ID token, refreshed when it is within a minute of expiry; null when signed out. */
  async idToken(): Promise<string | null> {
    const s = load();
    if (!s) return null;
    if (s.expiresAt - 60 > Date.now() / 1000) return s.idToken;
    try {
      const { client_id } = await getConfig();
      const r = await cognito<{ AuthenticationResult: { IdToken: string } }>("InitiateAuth", {
        ClientId: client_id,
        AuthFlow: "REFRESH_TOKEN_AUTH",
        AuthParameters: { REFRESH_TOKEN: s.refreshToken },
      });
      const next = fromResult(r, s.refreshToken, s.method);
      store(next);
      return next.idToken;
    } catch {
      store(null); // refresh token expired or revoked: sign in again
      return null;
    }
  },
};
