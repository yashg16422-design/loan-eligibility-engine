import { UploadSimple, UserCircle } from "@phosphor-icons/react";
import { UploadProvider, useUpload, isBusy } from "./lib/upload";
import { useSignedIn } from "./lib/useAccount";
import { Account, AuthCallback } from "./pages/Account";
import { Check } from "./pages/Check";
import { Dashboard } from "./pages/Dashboard";
import { Privacy, Terms } from "./pages/Legal";
import { Merchant } from "./pages/Merchant";
import { Link, navigate, useRoute, type Route } from "./router";

export function App() {
  return (
    <UploadProvider>
      <Shell />
    </UploadProvider>
  );
}

function Shell() {
  const route = useRoute();
  return (
    <div className="min-h-dvh">
      <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:z-50 focus:bg-fg focus:px-3 focus:py-2 focus:text-bg">
        Skip to content
      </a>
      <Header route={route} />
      <main id="main">
        {route === "merchant" && <Merchant />}
        {route === "check" && <Check />}
        {route === "dashboard" && <Dashboard />}
        {route === "account" && <Account />}
        {route === "callback" && <AuthCallback />}
        {route === "privacy" && <Privacy />}
        {route === "terms" && <Terms />}
      </main>
      <footer className="mx-auto mt-10 max-w-[1480px] border-t border-line px-5 py-8 text-xs text-mute sm:px-10 xl:px-16">
        Indicative eligibility from criteria lenders publish. Not a loan offer or approval; the lender decides.{" "}
        <a href="/" className="underline">ClickPar Match home</a>{" "}
        · <Link to="privacy" className="underline">Privacy</Link> · <Link to="terms" className="underline">Terms</Link>
      </footer>
    </div>
  );
}

const NAV: { to: Route; label: string; short: string }[] = [
  { to: "check", label: "Check eligibility", short: "Check" },
  { to: "dashboard", label: "My matches", short: "Matches" },
  { to: "merchant", label: "Merchant console", short: "Merchant" },
];

function Header({ route }: { route: Route }) {
  const { pick, state } = useUpload();
  const email = useSignedIn();
  const busy = isBusy(state);
  return (
    <header className="sticky top-0 z-20 border-b border-line bg-bg/90 backdrop-blur-md">
      <div className="mx-auto grid h-16 max-w-[1480px] grid-cols-[auto_1fr_auto] items-center gap-4 px-5 sm:px-10 xl:px-16">
        <a href="/" className="flex items-center gap-3 no-underline" aria-label="ClickPar Match home">
          <svg viewBox="0 0 32 32" aria-hidden className="size-7 text-fg">
            <path d="M16 2 30 16 16 30 2 16Z" fill="none" stroke="currentColor" strokeWidth="1.4" />
            <path d="M16 8 24 16 16 24 8 16Z" fill="currentColor" />
          </svg>
          <span className="hidden leading-none sm:grid">
            <b className="text-[0.86rem] font-bold tracking-[0.22em]">CLICKPAR</b>
            <small className="mt-1 font-mono text-[0.56rem] tracking-[0.34em] text-mute">MATCH</small>
          </span>
        </a>
        <nav aria-label="App" className="flex justify-center">
          <ul className="hidden gap-1 md:flex">
            {NAV.map((n) => (
              <li key={n.to}>
                <Link to={n.to} aria-current={route === n.to ? "page" : undefined}
                  className={`grid min-h-11 place-items-center px-3 text-[0.95rem] no-underline transition-colors duration-200 ${
                    route === n.to ? "text-fg" : "text-mute hover:text-fg"
                  }`}>
                  <span className={route === n.to ? "border-b border-fg pb-1" : "pb-0.5"}>{n.label}</span>
                </Link>
              </li>
            ))}
          </ul>
        </nav>
        <div className="flex items-center gap-2">
          {/* Uploads belong to a signed-in merchant: signed out, this opens the console's sign-in. */}
          {email ? (
            <button type="button" onClick={pick} disabled={busy} className="btn btn-primary min-h-10 px-4">
              <UploadSimple size={16} aria-hidden />
              {busy ? "Uploading" : "Upload CSV"}
            </button>
          ) : (
            route !== "merchant" && (
              <button type="button" onClick={() => navigate("merchant")} className="btn btn-ghost min-h-10 px-4">
                Merchant login
              </button>
            )
          )}
          <Link to="account" aria-current={route === "account" ? "page" : undefined}
            className="btn btn-ghost min-h-10 px-3 no-underline" aria-label={email ? `Account: ${email}` : "Sign in"}>
            <UserCircle size={18} aria-hidden />
            <span className="hidden max-w-[150px] truncate lg:inline">{email ?? "Sign in"}</span>
          </Link>
        </div>
      </div>
      {/* Phones: the three destinations as a second row. */}
      <ul className="flex border-t border-line md:hidden">
        {NAV.map((n) => (
          <li key={n.to} className="flex-1">
            <Link to={n.to} aria-current={route === n.to ? "page" : undefined}
              className={`grid h-11 place-items-center text-sm no-underline ${route === n.to ? "text-fg" : "text-mute"}`}>
              {n.short}
            </Link>
          </li>
        ))}
      </ul>
    </header>
  );
}
