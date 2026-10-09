import { Gauge } from "@phosphor-icons/react";
import { Check } from "./pages/Check";
import { Dashboard } from "./pages/Dashboard";
import { Ops } from "./pages/Ops";
import { Link, useRoute } from "./router";

export function App() {
  const route = useRoute();
  return (
    <div className="min-h-dvh">
      <header className="sticky top-0 z-20 border-b border-line bg-ink/90 backdrop-blur-sm">
        <nav className="mx-auto flex h-14 max-w-[1240px] items-center justify-between px-4 sm:px-6">
          <Link to="check" className="flex items-center gap-2 font-medium tracking-tight no-underline">
            <Mark />
            ClickPe Match
          </Link>
          <div className="flex items-center gap-1 text-sm">
            <NavLink to="dashboard" active={route === "dashboard"}>
              My matches
            </NavLink>
            <NavLink to="ops" active={route === "ops"}>
              <Gauge size={16} weight="regular" aria-hidden />
              Engine
            </NavLink>
          </div>
        </nav>
      </header>
      <main id="main">
        {route === "check" && <Check />}
        {route === "dashboard" && <Dashboard />}
        {route === "ops" && <Ops />}
      </main>
      <footer className="mx-auto max-w-[1240px] px-4 py-10 text-xs text-muted sm:px-6">
        Indicative eligibility from criteria lenders publish. Not a loan offer or approval; the lender decides.
      </footer>
    </div>
  );
}

function NavLink({ to, active, children }: { to: "dashboard" | "ops"; active: boolean; children: React.ReactNode }) {
  return (
    <Link
      to={to}
      aria-current={active ? "page" : undefined}
      className={`flex items-center gap-1.5 rounded-[var(--radius-ctl)] px-3 py-1.5 no-underline transition-colors duration-150 ${
        active ? "bg-raise text-text" : "text-muted hover:text-text"
      }`}
    >
      {children}
    </Link>
  );
}

/** Wordmark glyph: a ticked ledger line, one stroke weight, drawn once for the brand. */
function Mark() {
  return (
    <svg width="20" height="20" viewBox="0 0 20 20" aria-hidden className="text-marigold">
      <rect x="1.5" y="1.5" width="17" height="17" rx="4" fill="none" stroke="currentColor" strokeWidth="1.5" />
      <path d="M5.5 10.5l3 3 6-7" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}
