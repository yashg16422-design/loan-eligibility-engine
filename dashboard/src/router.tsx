// A three-route app does not need a router library: History API + one hook.
import { useEffect, useState, type AnchorHTMLAttributes, type MouseEvent } from "react";

export const BASE = "/app";
export type Route = "check" | "dashboard" | "ops";

function current(): Route {
  const path = window.location.pathname.replace(BASE, "").replace(/^\/+|\/+$/g, "");
  return path === "dashboard" || path === "ops" ? path : "check";
}

export function navigate(to: Route) {
  window.history.pushState(null, "", `${BASE}/${to === "check" ? "" : to}`);
  window.dispatchEvent(new PopStateEvent("popstate"));
  window.scrollTo({ top: 0 });
}

export function useRoute(): Route {
  const [route, setRoute] = useState(current);
  useEffect(() => {
    const on = () => setRoute(current());
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
  return <a href={`${BASE}/${to === "check" ? "" : to}`} onClick={onClick} {...rest} />;
}
