import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError, session } from "../api/client";
import type { CatalogProduct, Match, Me, Preferences } from "../api/types";

export type Load =
  | { state: "loading" }
  | { state: "signed-out" }
  | { state: "queued" }
  | { state: "error"; message: string }
  | { state: "ready"; me: Me; matches: Match[]; catalog: CatalogProduct[] };

const EMPTY: Preferences = { shortlist: [], top3: [], hidden: [], alerts: false, updated_at: null };

export function useDashboard() {
  const [load, setLoad] = useState<Load>(session.get() ? { state: "loading" } : { state: "signed-out" });
  const [prefs, setPrefs] = useState<Preferences>(EMPTY);
  const [saveError, setSaveError] = useState<string | null>(null);
  const saveTimer = useRef<number | undefined>(undefined);

  const fetchAll = useCallback(async () => {
    if (!session.get()) return setLoad({ state: "signed-out" });
    try {
      const { body } = await api.me();
      if (body.matching === "queued" || body.matching === "running") {
        setLoad({ state: "queued" });
        window.setTimeout(fetchAll, 2000);
        return;
      }
      const [matches, catalog, saved] = await Promise.all([api.matches(), api.products(), api.preferences()]);
      setPrefs(saved);
      setLoad({ state: "ready", me: body as Me, matches, catalog });
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        session.clear();
        return setLoad({ state: "signed-out" });
      }
      setLoad({ state: "error", message: err instanceof Error ? err.message : "Could not load your matches." });
    }
  }, []);

  useEffect(() => {
    void fetchAll();
  }, [fetchAll]);

  /** Optimistic update; the full state is saved after a short pause (one PUT per burst). */
  const update = useCallback((change: (p: Preferences) => Preferences) => {
    setPrefs((prev) => {
      const next = change(prev);
      window.clearTimeout(saveTimer.current);
      saveTimer.current = window.setTimeout(async () => {
        try {
          const { shortlist, top3, hidden, alerts } = next;
          await api.savePreferences({ shortlist, top3, hidden, alerts });
          setSaveError(null);
        } catch {
          setSaveError("Your last change was not saved. It will be retried on your next change.");
        }
      }, 500);
      return next;
    });
  }, []);

  return { load, prefs, update, saveError, retry: fetchAll };
}

// Pure preference transitions (the server enforces the same rules: top 3 is a subset of the
// shortlist, and hiding an offer removes it from both).
export const toggleSaved = (id: string) => (p: Preferences): Preferences =>
  p.shortlist.includes(id)
    ? { ...p, shortlist: p.shortlist.filter((x) => x !== id), top3: p.top3.filter((x) => x !== id) }
    : { ...p, shortlist: [...p.shortlist, id] };

export const toggleCompare = (id: string) => (p: Preferences): Preferences => {
  if (p.top3.includes(id)) return { ...p, top3: p.top3.filter((x) => x !== id) };
  if (p.top3.length >= 3) return p;
  return { ...p, shortlist: p.shortlist.includes(id) ? p.shortlist : [...p.shortlist, id], top3: [...p.top3, id] };
};

export const toggleHidden = (id: string) => (p: Preferences): Preferences =>
  p.hidden.includes(id)
    ? { ...p, hidden: p.hidden.filter((x) => x !== id) }
    : { ...p, hidden: [...p.hidden, id], shortlist: p.shortlist.filter((x) => x !== id), top3: p.top3.filter((x) => x !== id) };
