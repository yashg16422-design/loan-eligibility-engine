import { useEffect, useState } from "react";
import { auth } from "../api/auth";
import { api } from "../api/client";

/** The signed-in email (or null), kept in sync across components and tabs. */
export function useSignedIn(): string | null {
  const [email, setEmail] = useState(auth.email);
  useEffect(() => {
    const on = () => setEmail(auth.email());
    window.addEventListener("clickpar-account", on);
    window.addEventListener("storage", on);
    return () => {
      window.removeEventListener("clickpar-account", on);
      window.removeEventListener("storage", on);
    };
  }, []);
  return email;
}

/** True when the signed-in account is in the Cognito `admin` group (may delete uploaded data). */
export function useIsAdmin(): boolean {
  const email = useSignedIn();
  const [admin, setAdmin] = useState(false);
  useEffect(() => {
    if (!email) return setAdmin(false);
    let gone = false;
    api.account().then((a) => !gone && setAdmin(a.is_admin)).catch(() => !gone && setAdmin(false));
    return () => {
      gone = true;
    };
  }, [email]);
  return admin;
}

// A save the visitor asked for before signing in; completed right after sign-in.
const PENDING = "clickpar-pending-save";
export const pendingSave = {
  set: () => {
    try {
      sessionStorage.setItem(PENDING, "1");
    } catch {
      /* ignore */
    }
  },
  peek: (): boolean => {
    try {
      return sessionStorage.getItem(PENDING) === "1";
    } catch {
      return false;
    }
  },
  take: (): boolean => {
    try {
      const had = sessionStorage.getItem(PENDING) === "1";
      sessionStorage.removeItem(PENDING);
      return had;
    } catch {
      return false;
    }
  },
};
