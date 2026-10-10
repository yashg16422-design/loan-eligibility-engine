import { ArrowRight, SignOut, WarningCircle } from "@phosphor-icons/react";
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

type Step = { mode: "signin" | "signup" } | { mode: "confirm"; email: string; password: string };

function SignInFlow() {
  const [step, setStep] = useState<Step>({ mode: pendingSave.peek() ? "signup" : "signin" });
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const afterSignIn = () => navigate(pendingSave.peek() ? "dashboard" : "account");

  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    setError(null);
    setNotice(null);
    setBusy(true);
    try {
      if (step.mode === "confirm") {
        await auth.confirm(step.email, String(f.get("code")));
        await auth.signIn(step.email, step.password);
        afterSignIn();
      } else {
        const email = String(f.get("email")).trim().toLowerCase();
        const password = String(f.get("password"));
        if (step.mode === "signup") {
          await auth.signUp(email, password);
          setStep({ mode: "confirm", email, password });
          setNotice(`We sent a 6-digit code to ${email}. It comes from no-reply@verificationemail.com.`);
        } else {
          await auth.signIn(email, password);
          afterSignIn();
        }
      }
    } catch (err) {
      if (err instanceof AuthError && err.code === "UserNotConfirmedException" && step.mode === "signin") {
        const email = String(f.get("email")).trim().toLowerCase();
        setStep({ mode: "confirm", email, password: String(f.get("password")) });
        await auth.resend(email).catch(() => {});
        setNotice(`Confirm your email first: we sent a new code to ${email}.`);
      } else {
        setError(err instanceof Error ? err.message : "Something went wrong. Try again.");
      }
    } finally {
      setBusy(false);
    }
  }

  const resend = async () => {
    if (step.mode !== "confirm") return;
    setError(null);
    try {
      await auth.resend(step.email);
      setNotice(`A new code is on its way to ${step.email}.`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not send a new code.");
    }
  };

  return (
    <div className="mx-auto grid max-w-[1480px] gap-12 px-5 pt-14 pb-12 sm:px-10 xl:px-16 lg:grid-cols-[minmax(0,480px)_minmax(0,1fr)] lg:gap-24 lg:pt-20">
      <section aria-labelledby="acc-title">
        <h1 id="acc-title" className="text-3xl sm:text-4xl">
          {step.mode === "confirm" ? "Check your email." : step.mode === "signup" ? "Save your results." : "Sign in."}
        </h1>
        <p className="mt-3 text-mute">
          {step.mode === "confirm"
            ? "Enter the code we emailed you to finish creating your account."
            : "Your saved checks open from any device, and your top picks are refreshed every morning."}
        </p>

        {step.mode !== "confirm" && (
          <div role="tablist" aria-label="Account" className="mt-8 grid grid-cols-2 border border-line">
            {(["signin", "signup"] as const).map((m) => (
              <button key={m} role="tab" type="button" aria-selected={step.mode === m} onClick={() => (setStep({ mode: m }), setError(null))}
                className={`h-11 text-sm ${step.mode === m ? "bg-acc-deep text-fg" : "text-mute hover:text-fg"}`}>
                {m === "signin" ? "Sign in" : "Create account"}
              </button>
            ))}
          </div>
        )}

        <form onSubmit={submit} className="box mt-4 grid gap-5 p-7">
          {step.mode === "confirm" ? (
            <label className="grid gap-2">
              <span className="text-sm">Verification code</span>
              <input name="code" required inputMode="numeric" autoComplete="one-time-code" maxLength={6} pattern="[0-9]{6}" className="field tracking-[0.4em]" />
            </label>
          ) : (
            <>
              <label className="grid gap-2">
                <span className="text-sm">Email</span>
                <input name="email" type="email" required autoComplete="email" className="field font-sans" />
              </label>
              <label className="grid gap-2">
                <span className="text-sm">Password</span>
                <input name="password" type="password" required minLength={step.mode === "signup" ? 10 : undefined}
                  autoComplete={step.mode === "signup" ? "new-password" : "current-password"} className="field font-sans" />
                {step.mode === "signup" && <span className="text-xs text-mute">At least 10 characters, with a lowercase letter and a number.</span>}
              </label>
            </>
          )}
          <button type="submit" disabled={busy} className="btn btn-primary">
            {busy ? "One moment" : step.mode === "confirm" ? "Confirm and sign in" : step.mode === "signup" ? "Create account" : "Sign in"}
          </button>
          {step.mode === "confirm" && (
            <p className="flex flex-wrap gap-x-4 text-sm">
              <button type="button" onClick={resend} className="text-mute underline">Send a new code</button>
              <button type="button" onClick={() => setStep({ mode: "signup" })} className="text-mute underline">Use a different email</button>
            </p>
          )}
          {notice && <p role="status" className="text-sm text-acc">{notice}</p>}
          {error && <p role="alert" className="flex items-start gap-2 text-sm text-coral"><WarningCircle size={18} className="mt-0.5 shrink-0" aria-hidden /> {error}</p>}
        </form>
      </section>

      <aside className="grid content-start gap-4 text-sm text-mute lg:pt-24">
        <h2 className="text-lg text-fg">How your account works</h2>
        <p>Accounts run on Amazon Cognito. Your password goes only to Cognito; ClickPar Match never sees or stores it.</p>
        <p>Your saved checks are linked to your account in our database, so you can reopen them from any device.</p>
        <p>Every morning at 06:00 the crawler re-reads lenders' sites. Lenders that change their rules are re-matched against everyone, so your top picks stay current.</p>
      </aside>
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
        <button type="button" onClick={() => (auth.signOut(), navigate("account"))} className="btn btn-ghost">
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
