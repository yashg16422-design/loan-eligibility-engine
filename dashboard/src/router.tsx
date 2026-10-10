// Four routes do not need a router library: History API + one hook.
import { useEffect, useState, type AnchorHTMLAttributes, type MouseEvent } from "react";

export const BASE = "/app";
export type Route = "overview" | "check" | "dashboard" | "account";

const PATHS: Record<Route, string> = { overview: "", check: "check", dashboard: "dashboard", account: "account" };

export function routeFromPath(pathname: string): Route {
  const path = pathname.replace(BASE, "").replace(/^\/+|\/+$/g, "");
  if (path === "check" || path === "dashboard" || path === "account") return path;
  return "overview"; // "", "ops" (old links) and anything unknown
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
