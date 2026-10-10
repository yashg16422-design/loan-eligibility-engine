// A handful of routes do not need a router library: History API + one hook.
import { useEffect, useState, type AnchorHTMLAttributes, type MouseEvent } from "react";

export const BASE = "/app";
export type Route = "merchant" | "check" | "dashboard" | "account" | "callback" | "privacy" | "terms";

const PATHS: Record<Route, string> = { merchant: "merchant", check: "check", dashboard: "dashboard", account: "account", callback: "auth/callback", privacy: "privacy", terms: "terms" };

export function routeFromPath(pathname: string): Route {
  const path = pathname.replace(BASE, "").replace(/^\/+|\/+$/g, "");
  if (path === "check" || path === "dashboard" || path === "account" || path === "privacy" || path === "terms") return path;
  if (path === "auth/callback") return "callback"; // back from Google (OAuth code flow)
  return "merchant"; // "", "merchant", "ops" (old links) and anything unknown: the console
}

export const href = (to: Route) => `${BASE}/${PATHS[to]}`;

export function navigate(to: Route) {
  if (window.location.pathname !== href(to)) window.history.pushState(null, "", href(to));
  window.dispatchEvent(new PopStateEvent("popstate"));
  window.scrollTo({ top: 0 });
}

export function useRoute(): Route {
  const [route, setRoute] = useState(() => routeFromPath(window.location.pathname));
  useEffect(() => {
    const on = () => setRoute(routeFromPath(window.location.pathname));
    window.addEventListener("popstate", on);
    return () => window.removeEventListener("popstate", on);
  }, []);
  return route;
}

export function Link({ to, ...rest }: { to: Route } & AnchorHTMLAttributes<HTMLAnchorElement>) {
  const onClick = (e: MouseEvent<HTMLAnchorElement>) => {
    if (e.metaKey || e.ctrlKey || e.shiftKey || e.button !== 0) return; // let new-tab work
    e.preventDefault();
    navigate(to);
  };
  return <a href={href(to)} onClick={onClick} {...rest} />;
}
