import { ArrowRight, GoogleLogo, SignOut, WarningCircle } from "@phosphor-icons/react";
import { useCallback, useEffect, useState, type FormEvent } from "react";
import { auth, AuthError } from "../api/auth";
import { api, session } from "../api/client";
import type { Account as AccountData } from "../api/types";
import { EMPLOYMENT_LABEL, rupees } from "../lib/format";
import { pendingSave, useSignedIn } from "../lib/useAccount";
import { navigate } from "../router";
import { ConfirmDelete } from "../ui/Confirm";

export function Account() {
  const email = useSignedIn();
  return email ? <SignedIn email={email} /> : <SignInFlow />;
}

type Step =
  | { mode: "signin" | "signup" | "forgot" }
  | { mode: "confirm"; email: string; password: string }
  | { mode: "reset"; email: string };

const TITLES: Record<Step["mode"], [string, string]> = {
  signin: ["Sign in.", "Your saved checks open from any device, and your top picks are refreshed every morning."],
  signup: ["Create your account.", "Save results and uploads to an account you can open from any device."],
  confirm: ["Check your email.", "Enter the code we emailed you to finish creating your account."],
  forgot: ["Reset your password.", "We will email you a code to choose a new password."],
  reset: ["Choose a new password.", "Enter the code from the email and your new password."],
};

/**
 * Cognito sign-in, sign-up (email code), forgot / reset password, and "Continue with Google".
 * `embedded` renders just the form (merchant console); `onDone` runs after a successful sign-in.
 */
// Cognito's answers to a wrong email or password (also what a Google-only email gets).
const WRONG_LOGIN = new Set(["NotAuthorizedException", "UserNotFoundException"]);

export function SignInFlow({ embedded = false, onDone }: { embedded?: boolean; onDone?: () => void }) {
  const [step, setStep] = useState<Step>({ mode: pendingSave.peek() ? "signup" : "signin" });
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [google, setGoogle] = useState(false);
  const [showPassword, setShowPassword] = useState(false);
  useEffect(() => void auth.googleEnabled().then(setGoogle), []);

  const afterSignIn = () => (onDone ? onDone() : navigate(pendingSave.peek() ? "dashboard" : "account"));
  const go = (next: Step, message: string | null = null) => {
    setStep(next);
    setError(null);
    setNotice(message);
  };

  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    const email = String(f.get("email") ?? "").trim().toLowerCase();
    const password = String(f.get("password") ?? "");
    setError(null);
    setNotice(null);
    setBusy(true);
    try {
      if (step.mode === "confirm") {
        await auth.confirm(step.email, String(f.get("code")));
        await auth.signIn(step.email, step.password);
        afterSignIn();
      } else if (step.mode === "signup") {
        await auth.signUp(email, password);
        startCooldown();
        go({ mode: "confirm", email, password }, `We sent a 6-digit code to ${email}. It comes from no-reply@verificationemail.com; check spam if it is not in your inbox within a minute.`);
      } else if (step.mode === "forgot") {
        await auth.forgotPassword(email);
        startCooldown();
        go({ mode: "reset", email }, `If ${email} has a password, a 6-digit code is on its way from no-reply@verificationemail.com.`);
      } else if (step.mode === "reset") {
        await auth.resetPassword(step.email, String(f.get("code")), password);
        await auth.signIn(step.email, password);
        afterSignIn();
      } else {
        await auth.signIn(email, password);
        afterSignIn();
      }
    } catch (err) {
      if (err instanceof AuthError && err.code === "UserNotConfirmedException" && step.mode === "signin") {
        await auth.resend(email).catch(() => {});
        go({ mode: "confirm", email, password }, `Confirm your email first: we sent a new code to ${email}.`);
      } else if (err instanceof AuthError && google && step.mode === "signin" && WRONG_LOGIN.has(err.code)) {
        // A Google-only account has no password at all: say so instead of only "incorrect".
        setError(`${err.message} If you signed up with Google, use Continue with Google above.`);
      } else {
        setError(err instanceof Error ? err.message : "Something went wrong. Try again.");
      }
    } finally {
      setBusy(false);
    }
  }

  // A new code at most every 30 s: retries must not burn Cognito's daily email quota.
  const [cooldown, setCooldown] = useState(0);
  useEffect(() => {
    if (cooldown <= 0) return;
    const id = window.setTimeout(() => setCooldown((c) => c - 1), 1000);
    return () => window.clearTimeout(id);
  }, [cooldown]);
  const startCooldown = () => setCooldown(30);

  const resend = async () => {
    if (step.mode !== "confirm" && step.mode !== "reset") return;
    if (cooldown > 0) return;
    setError(null);
    try {
      if (step.mode === "confirm") await auth.resend(step.email);
      else await auth.forgotPassword(step.email);
      startCooldown();
      setNotice(`A new code is on its way to ${step.email}.`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not send a new code.");
    }
  };

  const tabs = step.mode === "signin" || step.mode === "signup";
  const newPassword = step.mode === "signup" || step.mode === "reset";
  const label = { signin: "Sign in", signup: "Create account", confirm: "Confirm and sign in", forgot: "Email me a code", reset: "Save password and sign in" }[step.mode];

  const form = (
    <>
      {tabs && (
        <div role="tablist" aria-label="Account" className="grid grid-cols-2 border border-line">
          {(["signin", "signup"] as const).map((m) => (
            <button key={m} role="tab" type="button" aria-selected={step.mode === m} onClick={() => go({ mode: m })}
              className={`h-11 text-sm ${step.mode === m ? "bg-fg text-bg" : "text-mute hover:text-fg"}`}>
              {m === "signin" ? "Sign in" : "Create account"}
            </button>
          ))}
        </div>
      )}
      {embedded && !tabs && <p className="text-lg font-light">{TITLES[step.mode][0]}</p>}

      {tabs && google && (
        <>
          <button type="button" onClick={() => void auth.signInWithGoogle(window.location.pathname)}
            className="btn btn-ghost mt-4 w-full">
            <GoogleLogo size={18} weight="bold" aria-hidden /> Continue with Google
          </button>
          <p className="label my-4 flex items-center gap-3 before:h-px before:flex-1 before:bg-line after:h-px after:flex-1 after:bg-line">or with email</p>
        </>
      )}

      <form onSubmit={submit} className={`box grid gap-5 p-6 ${tabs && google ? "" : "mt-4"}`}>
        {(step.mode === "signin" || step.mode === "signup" || step.mode === "forgot") && (
          <label className="grid gap-2">
            <span className="text-sm">Email</span>
            <input name="email" type="email" required autoComplete={step.mode === "signup" ? "email" : "username"} className="field font-sans" />
          </label>
        )}
        {(step.mode === "confirm" || step.mode === "reset") && (
          <label className="grid gap-2">
            <span className="text-sm">Code from the email</span>
            <input name="code" required inputMode="numeric" autoComplete="one-time-code" maxLength={6} pattern="[0-9]{6}" className="field tracking-[0.4em]" />
          </label>
        )}
        {(step.mode === "signin" || step.mode === "signup" || step.mode === "reset") && (
          <label className="grid gap-2">
            <span className="flex items-center justify-between text-sm">
              {step.mode === "reset" ? "New password" : "Password"}
              <button type="button" onClick={() => setShowPassword((v) => !v)} className="text-xs text-mute hover:text-fg">
                {showPassword ? "Hide" : "Show"}
              </button>
            </span>
            <input name="password" type={showPassword ? "text" : "password"} required minLength={newPassword ? 10 : undefined}
              autoComplete={newPassword ? "new-password" : "current-password"} className="field font-sans" />
            {newPassword && <span className="text-xs text-mute">At least 10 characters, with a lowercase letter and a number.</span>}
          </label>
        )}
        <button type="submit" disabled={busy} className="btn btn-primary">{busy ? "One moment" : label}</button>
        <p className="flex flex-wrap gap-x-5 gap-y-2 text-sm">
          {step.mode === "signin" && <button type="button" onClick={() => go({ mode: "forgot" })} className="text-mute underline underline-offset-4 hover:text-fg">Forgot password?</button>}
          {(step.mode === "confirm" || step.mode === "reset") && (
            <button type="button" onClick={resend} disabled={cooldown > 0} className="text-mute underline underline-offset-4 hover:text-fg disabled:no-underline disabled:opacity-60">
              {cooldown > 0 ? `Send a new code in ${cooldown} s` : "Send a new code"}
            </button>
          )}
          {!tabs && <button type="button" onClick={() => go({ mode: "signin" })} className="text-mute underline underline-offset-4 hover:text-fg">Back to sign in</button>}
        </p>
        {notice && <p role="status" className="text-sm text-acc">{notice}</p>}
        {(step.mode === "reset" || step.mode === "confirm") && (
          <div className="border-t border-line pt-4 text-sm text-mute">
            <p className="text-fg">No email after a minute?</p>
            <ul className="mt-2 grid list-disc gap-1 pl-5">
              <li>Check Spam and Promotions; the sender is no-reply@verificationemail.com.</li>
              {step.mode === "reset" && <li>If you signed up with Google, this email has no password to reset. Go back and use Continue with Google, or choose Create account with the same email to add a password; it stays the same account.</li>}
              <li>Use the newest code; each new request replaces the last one.</li>
            </ul>
          </div>
        )}
        {error && <p role="alert" className="flex items-start gap-2 text-sm text-coral"><WarningCircle size={18} className="mt-0.5 shrink-0" aria-hidden /> {error}</p>}
      </form>
    </>
  );
  if (embedded) return form;

  return (
    <div className="mx-auto grid max-w-[1480px] gap-12 px-5 pt-14 pb-12 sm:px-10 xl:px-16 lg:grid-cols-[minmax(0,480px)_minmax(0,1fr)] lg:gap-24 lg:pt-20">
      <section aria-labelledby="acc-title">
        <h1 id="acc-title" className="text-3xl sm:text-4xl">{TITLES[step.mode][0]}</h1>
        <p className="mt-3 mb-8 text-mute">{TITLES[step.mode][1]}</p>
        {form}
      </section>

      <aside className="grid content-start gap-4 text-sm text-mute lg:pt-24">
        <h2 className="text-lg text-fg">How your account works</h2>
        <p>Accounts run on Amazon Cognito. Your password goes only to Cognito; ClickPar Match never sees or stores it.</p>
        <p>Sign in with email or Google: the same email is the same account, so your saved checks and uploads follow you.</p>
        <p>Every morning at 06:00 the crawler re-reads lenders' sites. Lenders that change their rules are re-matched against everyone, so your top picks stay current.</p>
      </aside>
    </div>
  );
}

/** Back from Google: swap the code for tokens, then return to where sign-in started. */
export function AuthCallback() {
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    auth
      .finishGoogle(new URLSearchParams(window.location.search))
      .then((to) => {
        window.history.replaceState(null, "", to);
        window.dispatchEvent(new PopStateEvent("popstate"));
      })
      .catch((err) => setError(err instanceof Error ? err.message : "Google sign-in failed."));
  }, []);
  return (
    <div className="mx-auto max-w-[620px] px-5 pt-24 sm:px-10" role={error ? "alert" : "status"}>
      <h1 className="text-3xl">{error ? "Sign-in did not finish." : "Signing you in."}</h1>
      <p className="mt-3 text-mute">{error ?? "One moment while we finish signing you in with Google."}</p>
      {error && <button type="button" onClick={() => navigate("merchant")} className="btn btn-ghost mt-6">Back to the console</button>}
    </div>
  );
}

function SignedIn({ email }: { email: string }) {
  const [account, setAccount] = useState<AccountData | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setAccount(await api.account());
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Your account could not be loaded.");
    }
  }, []);
  useEffect(() => void load(), [load]);

  const open = async (userId: string) => {
    try {
      session.set((await api.openProfile(userId)).token);
      navigate("dashboard");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not open that check.");
    }
  };
  const clear = async (userId?: string) => {
    try {
      await api.clearProfiles(userId);
      session.clear(); // the open dashboard link may point at a check that no longer exists
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Nothing was removed. Try again.");
    }
  };
  const toggleDaily = async (on: boolean) => {
    setAccount((a) => (a ? { ...a, daily_picks: on } : a));
    try {
      setAccount(await api.setDailyPicks(on));
    } catch {
      setError("That change was not saved. Try again.");
      void load();
    }
  };

  return (
    <div className="mx-auto max-w-[1000px] px-5 pt-14 pb-12 sm:px-10 xl:px-16 lg:pt-20">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-3xl sm:text-4xl">Your account</h1>
          <p className="mt-2 text-mute">{email}</p>
        </div>
        <button type="button" onClick={() => void auth.signOut().then(() => navigate("account"))} className="btn btn-ghost">
          <SignOut size={16} aria-hidden /> Sign out
        </button>
      </div>
      {error && <p role="alert" className="mt-4 text-sm text-coral">{error}</p>}

      <label className="box tick mt-8 flex cursor-pointer items-center justify-between gap-6 p-7">
        <span>
          <span className="block font-medium">Top picks every morning</span>
          <span className="text-sm text-mute">After the 06:00 lender crawl your matches are refreshed and new ones are emailed (in this demo, emails go to the project's test inboxes).</span>
        </span>
        <input type="checkbox" role="switch" checked={account?.daily_picks ?? true} disabled={!account}
          onChange={(e) => void toggleDaily(e.target.checked)} className="size-5 shrink-0 accent-[var(--color-acc)]" />
      </label>

      <section aria-labelledby="saved-title" className="mt-14">
        <div className="flex flex-wrap items-end justify-between gap-4">
          <h2 id="saved-title" className="text-2xl">Saved checks</h2>
          {account && account.profiles.length > 0 && (
            <ConfirmDelete
              small
              label="Start fresh"
              question={`Remove all ${account.profiles.length} saved checks? Your account and settings stay.`}
              onConfirm={() => clear()}
            />
          )}
        </div>
        {!account ? (
          <div className="mt-5 h-24 border border-line bg-panel" aria-busy="true" />
        ) : account.profiles.length === 0 ? (
          <p className="mt-4 text-mute">Nothing saved yet. Run a check, then choose "Save my results" on your matches.</p>
        ) : (
          <ul className="mt-5 grid gap-px border border-line bg-line">
            {account.profiles.map((p) => (
              <li key={p.user_id} className="flex flex-wrap items-center justify-between gap-4 bg-panel p-6">
                <div>
                  <p className="font-medium">{p.name || "Your check"}</p>
                  <p className="text-sm text-mute">
                    <span className="num">{rupees(p.monthly_income)}</span> a month, score <span className="num">{p.credit_score}</span>,{" "}
                    {EMPLOYMENT_LABEL[p.employment_status].toLowerCase()}, age <span className="num">{p.age}</span>.{" "}
                    <span className="num">{p.eligible}</span> eligible of <span className="num">{p.matches}</span> matches.
                  </p>
                </div>
                <div className="flex flex-wrap items-center gap-3">
                  <ConfirmDelete
                    small
                    label="Remove"
                    question={p.source === "instant_check" ? "Delete this check?" : "Unlink this profile?"}
                    onConfirm={() => clear(p.user_id)}
                  />
                  <button type="button" onClick={() => void open(p.user_id)} className="btn btn-primary">
                    Open <ArrowRight size={16} aria-hidden />
                  </button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
