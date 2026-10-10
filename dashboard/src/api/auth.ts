// Accounts via Amazon Cognito, called directly from the browser (no SDK: five JSON calls).
// Passwords go only to Cognito over HTTPS; our API and database never see them. API calls
// carry the Cognito ID token, which API Gateway's JWT authorizer verifies before our code.

interface AuthConfig {
  region: string;
  user_pool_id: string;
  client_id: string;
}

interface Session {
  idToken: string;
  refreshToken: string;
  email: string;
  expiresAt: number; // epoch seconds of the ID token
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
  TooManyRequestsException: "Too many attempts. Wait a few minutes and try again.",
  InvalidParameterException: "Check the email address and try again.",
};

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
    throw new AuthError(code, MESSAGES[code] ?? data.message ?? "Something went wrong. Try again.");
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

function fromResult(r: { AuthenticationResult: { IdToken: string; RefreshToken?: string } }, refresh?: string): Session {
  const c = claims(r.AuthenticationResult.IdToken);
  return {
    idToken: r.AuthenticationResult.IdToken,
    refreshToken: r.AuthenticationResult.RefreshToken ?? refresh ?? "",
    email: String(c.email ?? ""),
    expiresAt: Number(c.exp ?? 0),
  };
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

  signOut() {
    store(null);
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
      const next = fromResult(r, s.refreshToken);
      store(next);
      return next.idToken;
    } catch {
      store(null); // refresh token expired or revoked: sign in again
      return null;
    }
  },
};
